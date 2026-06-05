"""Fábrica del modelo LLM usado por los nodos de triaje/verificación/redacción.

El modelo es inyectable (``build_graph(llm=...)``) para que los tests no necesiten
red ni claves: aquí solo vive el modelo real por defecto.

Soporta dos backends según ``PHARMA_AGENT_MODEL``:
- ``"anthropic:claude-..."`` (o cualquier provider de init_chat_model) → nativo.
- ``"ollama:<modelo>"`` → Ollama Cloud (https://ollama.com) vía su endpoint
  OpenAI-compatible. OJO: los modelos open de Ollama Cloud NO respetan el
  *structured output* constrained (ni ``format`` json-schema ni ``response_format``
  ni tool-calling de forma fiable). Por eso envolvemos el modelo en
  ``JSONCoercedChat``, que fuerza salida estructurada por prompt + parseo
  tolerante + reintento de validación. Esa fue la fricción real integrando
  Ollama Cloud con LangChain.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

OLLAMA_BASE_URL = "https://ollama.com/v1"


def get_llm():
    """Devuelve un chat model configurado vía PHARMA_AGENT_MODEL ("provider:modelo")."""
    spec = os.getenv("PHARMA_AGENT_MODEL", "anthropic:claude-sonnet-4-5")
    provider, _, model = spec.partition(":")

    if provider == "ollama":
        from langchain_openai import ChatOpenAI

        api_key = os.getenv("OLLAMA_API_KEY") or os.getenv("OLLAMA_CLOUD_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Falta OLLAMA_API_KEY en el entorno para usar un modelo 'ollama:'."
            )
        base = ChatOpenAI(
            model=model or "gpt-oss:20b",
            base_url=os.getenv("OLLAMA_BASE_URL", OLLAMA_BASE_URL),
            api_key=api_key,
            temperature=0,
            timeout=120,
        )
        return JSONCoercedChat(base)

    from langchain.chat_models import init_chat_model

    return init_chat_model(spec, temperature=0)


# --- Coerción de salida estructurada por prompt (para modelos sin structured
#     output nativo fiable, como los de Ollama Cloud) ------------------------

def _extract_json(text: str) -> Any:
    """Extrae el primer objeto JSON de un texto, tolerando fences y prosa."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("no se encontró un objeto JSON en la respuesta")


class _StructuredRunnable:
    """Runnable devuelto por ``with_structured_output``: pide JSON, parsea, valida."""

    def __init__(self, base: Any, model_cls: type[BaseModel]):
        self._base = base
        self._model_cls = model_cls

    def _instruction(self) -> SystemMessage:
        schema = json.dumps(self._model_cls.model_json_schema(), ensure_ascii=False)
        return SystemMessage(
            content=(
                "Devuelve EXCLUSIVAMENTE un objeto JSON válido que cumpla este "
                "JSON Schema. Sin texto adicional, sin explicaciones, sin markdown, "
                "sin ```. Usa null para los campos que no apliquen.\n"
                f"JSON Schema:\n{schema}"
            )
        )

    async def ainvoke(self, messages: Any, config: Any = None) -> BaseModel:
        msgs = list(messages) + [self._instruction()]
        last_err: Exception | None = None
        for _ in range(3):
            resp = await self._base.ainvoke(msgs)
            text = getattr(resp, "content", str(resp))
            try:
                return self._model_cls.model_validate(_extract_json(text))
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                last_err = exc
                msgs = msgs + [
                    AIMessage(content=text),
                    HumanMessage(
                        content=f"Eso no es JSON válido para el esquema ({exc}). "
                        "Devuelve SOLO el JSON corregido."
                    ),
                ]
        raise RuntimeError(f"El modelo no produjo JSON válido tras 3 intentos: {last_err}")

    def invoke(self, messages: Any, config: Any = None) -> BaseModel:
        import asyncio

        return asyncio.run(self.ainvoke(messages, config))


class JSONCoercedChat:
    """Envoltura de un chat model que añade structured-output por prompt.

    Mantiene la interfaz que usan los nodos: ``with_structured_output`` y
    ``ainvoke`` (esta última delega tal cual para la redacción en prosa)."""

    def __init__(self, base: Any):
        self._base = base

    def with_structured_output(self, model_cls: type[BaseModel]) -> _StructuredRunnable:
        return _StructuredRunnable(self._base, model_cls)

    async def ainvoke(self, messages: Any, config: Any = None) -> Any:
        return await self._base.ainvoke(messages, config)

    def invoke(self, messages: Any, config: Any = None) -> Any:
        return self._base.invoke(messages, config)
