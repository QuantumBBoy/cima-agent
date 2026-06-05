"""Utilidades compartidas entre nodos: parseo de resultados y procedencia.

Las respuestas de mcp-aemps llegan como texto/JSON. Estas funciones son
defensivas a propósito: si el formato cambia, degradan a "no encontrado" en
lugar de romper o inventar.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from ..state import GraphState, Source, ToolResult


def parse_content(result: ToolResult) -> Any:
    """Intenta interpretar el contenido de un ToolResult como JSON; si no, str."""
    if not result.ok or not result.content:
        return None
    try:
        return json.loads(result.content)
    except (json.JSONDecodeError, TypeError):
        return result.content


def _iter_records(payload: Any):
    """Itera registros de medicamento dentro de una respuesta heterogénea de CIMA.

    CIMA REST devuelve a veces ``{"resultados": [...]}`` (búsquedas paginadas) y
    a veces el objeto medicamento directamente. Cubrimos ambos.
    """
    if isinstance(payload, dict):
        if isinstance(payload.get("resultados"), list):
            yield from (r for r in payload["resultados"] if isinstance(r, dict))
        else:
            yield payload
    elif isinstance(payload, list):
        yield from (r for r in payload if isinstance(r, dict))


def results_for(state: GraphState, tool: str) -> list[ToolResult]:
    """Todos los ToolResult OK de una tool concreta."""
    return [r for r in state.get("tool_results", []) if r.tool == tool and r.ok]


def tool_was_run(state: GraphState, tool: str) -> bool:
    return any(r.tool == tool for r in state.get("tool_results", []))


def resolve_medicine(state: GraphState) -> Optional[dict]:
    """Devuelve el registro de medicamento resuelto, o None.

    Prioriza ``obtener_medicamento`` (detalle completo) sobre el primer hit de
    ``buscar_medicamentos``.
    """
    for tool in ("obtener_medicamento", "buscar_medicamentos"):
        for result in results_for(state, tool):
            for record in _iter_records(parse_content(result)):
                if record.get("nregistro") or record.get("nombre"):
                    return record
    return None


def search_returned_empty(state: GraphState) -> bool:
    """True si ya se hizo una búsqueda y CIMA no devolvió ningún medicamento.

    Evita re-buscar en bucle un fármaco que no existe en CIMA.
    """
    runs = results_for(state, "buscar_medicamentos")
    if not runs:
        return False
    for result in runs:
        if any(True for _ in _iter_records(parse_content(result))):
            return False
    return True


def extract_source(payload: Any, retrieved_at: Optional[str]) -> Source:
    """Extrae endpoint + fecha de consulta de una respuesta de mcp-aemps.

    mcp-aemps cita el endpoint REST oficial y la fecha en cada respuesta; los
    nombres de campo varían, así que probamos varios y caemos al timestamp local.
    """
    endpoint = None
    consulted = None
    if isinstance(payload, dict):
        for key in ("endpoint", "fuente", "source", "url", "_endpoint", "_source"):
            if isinstance(payload.get(key), str):
                endpoint = payload[key]
                break
        for key in ("fecha_consulta", "consulta", "timestamp", "fecha", "_timestamp"):
            if isinstance(payload.get(key), str):
                consulted = payload[key]
                break
    return Source(endpoint=endpoint, consulted_at=consulted or retrieved_at)


def collect_sources(state: GraphState) -> list[Source]:
    """Fuentes únicas de todos los resultados OK, para listarlas en la respuesta."""
    seen: set[tuple] = set()
    sources: list[Source] = []
    for result in state.get("tool_results", []):
        if not result.ok:
            continue
        src = result.source
        key = (src.endpoint, src.consulted_at, result.tool)
        if key in seen:
            continue
        seen.add(key)
        # Si el endpoint no vino en el payload, etiquetamos con la tool usada.
        if not src.endpoint:
            src = Source(endpoint=f"mcp-aemps:{result.tool}", consulted_at=src.consulted_at)
        sources.append(src)
    return sources


def results_as_text(state: GraphState, max_chars: int = 6000) -> str:
    """Serializa los resultados recuperados para dárselos al nodo de verificación."""
    chunks: list[str] = []
    for result in state.get("tool_results", []):
        status = "OK" if result.ok else f"ERROR: {result.error}"
        src = result.source.endpoint or "—"
        chunks.append(
            f"### tool={result.tool} args={result.args} ({status}) fuente={src}\n"
            f"{result.content or '(sin contenido)'}"
        )
    text = "\n\n".join(chunks)
    return text[:max_chars]
