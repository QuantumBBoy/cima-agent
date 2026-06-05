"""Dobles de prueba reutilizables: un LLM y unas tools falsas.

Permiten ejecutar el grafo sin red ni claves, tanto en los tests como en el
ejemplo offline. NO se usan en producción.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.messages import AIMessage


class _FakeStructured:
    def __init__(self, value: Any):
        self._value = value

    async def ainvoke(self, _messages: Any) -> Any:
        return self._value(_messages) if callable(self._value) else self._value


class FakeLLM:
    """LLM falso. ``structured`` mapea el nombre del modelo Pydantic esperado por
    ``with_structured_output`` a la instancia (o callable) que debe devolver.
    ``prose`` es el texto que devuelve ``ainvoke`` (para el nodo de redacción)."""

    def __init__(
        self,
        structured: dict[str, Any] | None = None,
        prose: str | Callable[[Any], str] = "Respuesta de prueba.",
    ):
        self.structured = structured or {}
        self.prose = prose

    def with_structured_output(self, model: type) -> _FakeStructured:
        name = model.__name__
        if name not in self.structured:
            raise AssertionError(f"FakeLLM no tiene respuesta configurada para {name}")
        return _FakeStructured(self.structured[name])

    async def ainvoke(self, messages: Any) -> AIMessage:
        content = self.prose(messages) if callable(self.prose) else self.prose
        return AIMessage(content=content)


class FakeTool:
    """Tool falsa al estilo de las que carga langchain-mcp-adapters.

    Expone ``name``, ``args`` (esquema de claves aceptadas) y ``ainvoke``, y
    registra cada llamada en ``calls`` para poder afirmar qué se invocó.
    """

    def __init__(
        self,
        name: str,
        response: Any,
        accepted: list[str] | None = None,
    ):
        self.name = name
        self._response = response
        self.calls: list[dict] = []
        # _accepted_keys() lee tool.args; dict no vacío => filtra por esas claves.
        self.args = {k: {} for k in accepted} if accepted else {}

    async def ainvoke(self, args: dict) -> str:
        self.calls.append(args)
        payload = self._response(args) if callable(self._response) else self._response
        if isinstance(payload, str):
            return payload
        return json.dumps(payload, ensure_ascii=False)
