"""Nodo EJECUTOR de tools: llama a mcp-aemps por el protocolo MCP y recoge los
resultados con su procedencia (endpoint + timestamp).

Patrón ToolNode + estado compartido: las tools cargadas por
langchain-mcp-adapters se invocan con ``ainvoke(args)``. Filtramos los args a
las claves que cada tool acepta, de modo que las pistas extra del planificador
(p. ej. añadir ``cn`` además de ``nregistro``) nunca rompen la llamada.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..state import GraphState, PlannedCall, ToolResult
from ._helpers import extract_source


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _accepted_keys(tool: Any) -> set[str] | None:
    """Claves que la tool declara aceptar, o None si no podemos introspeccionar."""
    schema = getattr(tool, "args", None)
    if isinstance(schema, dict) and schema:
        return set(schema.keys())
    return None


def _filter_args(tool: Any, args: dict) -> dict:
    accepted = _accepted_keys(tool)
    if accepted is None:
        return args
    return {k: v for k, v in args.items() if k in accepted and v is not None}


def _unwrap_blocks(value: Any) -> str | None:
    """Si ``value`` es una lista de bloques de contenido MCP, junta sus textos.

    El resultado real de mcp-aemps mezcla un bloque de texto (con el JSON de CIMA)
    y varios bloques de recurso (``{type, id, url, mime_type}``) sin ``text``. Nos
    quedamos con el/los bloque(s) de texto, no exigimos que todos lo tengan.
    """
    if isinstance(value, list) and value:
        texts = [str(b["text"]) for b in value if isinstance(b, dict) and "text" in b]
        if texts:
            return "".join(texts)
    return None


def _normalize_content(raw: Any) -> str:
    """Normaliza el resultado de una tool MCP a la cadena de datos real.

    langchain-mcp-adapters devuelve el resultado como una lista de bloques de
    contenido MCP: ``[{"type": "text", "text": "<JSON real>", "id": ...}]`` (a
    veces ya serializada a string). El payload de CIMA viene como string JSON
    dentro de ``text``. Desempaquetamos esa capa —tanto si llega como lista como
    si llega como string— para que el resto del agente vea directamente el JSON
    de CIMA (p. ej. ``{"resultados": [...]}``).
    """
    unwrapped = _unwrap_blocks(raw)
    if unwrapped is not None:
        return unwrapped
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return raw
        return _unwrap_blocks(parsed) or raw
    try:
        return json.dumps(raw, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(raw)


def make_execute_node(tools: dict[str, Any]):
    async def execute_node(state: GraphState) -> GraphState:
        results: list[ToolResult] = []
        for call in state.get("plan", []):
            results.append(await _run_call(tools, call))
        return {
            "tool_results": results,
            "iterations": state.get("iterations", 0) + 1,
            "plan": [],
        }

    return execute_node


async def _run_call(tools: dict[str, Any], call: PlannedCall) -> ToolResult:
    retrieved_at = _now_iso()
    tool = tools.get(call.tool)
    if tool is None:
        return ToolResult(
            tool=call.tool,
            args=call.args,
            ok=False,
            error=f"tool '{call.tool}' no disponible en el servidor mcp-aemps",
            retrieved_at=retrieved_at,
        )
    args = _filter_args(tool, call.args)
    try:
        raw = await tool.ainvoke(args)
    except Exception as exc:  # noqa: BLE001 - registramos el fallo, no rompemos el grafo
        return ToolResult(
            tool=call.tool,
            args=args,
            ok=False,
            error=str(exc),
            retrieved_at=retrieved_at,
        )

    payload: Any
    content = _normalize_content(raw)
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        payload = raw
    return ToolResult(
        tool=call.tool,
        args=args,
        ok=True,
        content=content,
        source=extract_source(payload, retrieved_at),
        retrieved_at=retrieved_at,
    )
