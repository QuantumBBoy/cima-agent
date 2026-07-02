"""Utilidades compartidas entre nodos: parseo de resultados y procedencia.

Las respuestas de mcp-aemps llegan como texto/JSON. Estas funciones son
defensivas a propósito: si el formato cambia, degradan a "no encontrado" en
lugar de romper o inventar.
"""

from __future__ import annotations

import json
import re
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


def _dose_token(dosis: Optional[str]) -> Optional[str]:
    """Extrae el número de la dosis ("600 mg" -> "600") para casarlo con el nombre."""
    if not dosis:
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", dosis)
    return match.group(0) if match else None


def resolve_medicine(
    state: GraphState,
    prefer: Optional[str] = None,
    prefer_dosis: Optional[str] = None,
) -> Optional[dict]:
    """Devuelve el registro de medicamento resuelto, o None.

    Prioriza ``obtener_medicamento`` (detalle completo) sobre ``buscar_medicamentos``.
    Entre los hits de búsqueda elige por relevancia real, no por orden de CIMA
    (que ordena por similitud: "omeprazol" devuelve ESOMEPRAZOL primero, e
    "ibuprofeno cinfa" devuelve la suspensión 20 mg/ml antes que los 600 mg):
    1º nombre que empieza por lo buscado Y contiene la dosis pedida,
    2º nombre que empieza por lo buscado, 3º primer hit.
    """
    prefer_upper = prefer.upper() if prefer else None
    dose = _dose_token(prefer_dosis)
    dose_re = re.compile(rf"\b{re.escape(dose)}\b") if dose else None

    # El detalle ya recuperado gana siempre: fue elegido en una vuelta anterior.
    for result in results_for(state, "obtener_medicamento"):
        for record in _iter_records(parse_content(result)):
            if record.get("nregistro") or record.get("nombre"):
                return record

    fallback: Optional[dict] = None
    name_match: Optional[dict] = None
    for result in results_for(state, "buscar_medicamentos"):
        for record in _iter_records(parse_content(result)):
            if not (record.get("nregistro") or record.get("nombre")):
                continue
            if fallback is None:
                fallback = record
            nombre = str(record.get("nombre", "")).upper()
            if prefer_upper and nombre.startswith(prefer_upper):
                if dose_re is None or dose_re.search(nombre):
                    return record  # nombre + dosis: el mejor candidato posible
                if name_match is None:
                    name_match = record
            elif prefer_upper is None:
                return record
    return name_match or fallback


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
    """Extrae la procedencia (fuente + fecha de consulta) de una respuesta de mcp-aemps.

    mcp-aemps la anida en ``metadata``: ``{"fuente": "CIMA (AEMPS)",
    "fecha_consulta": "02/07/2026 08:30 UTC", "version_api": "1.23", ...}``
    (verificado en vivo). Mantenemos los fallbacks top-level por si alguna tool
    la emite plana, y caemos al timestamp local si no hay nada.
    """
    endpoint = None
    consulted = None
    if isinstance(payload, dict):
        meta = payload.get("metadata")
        if isinstance(meta, dict):
            fuente = meta.get("fuente")
            if isinstance(fuente, str):
                version = meta.get("version_api")
                endpoint = f"{fuente} REST v{version}" if version else fuente
            if isinstance(meta.get("fecha_consulta"), str):
                consulted = meta["fecha_consulta"]
        if endpoint is None:
            for key in ("endpoint", "fuente", "source", "url"):
                if isinstance(payload.get(key), str):
                    endpoint = payload[key]
                    break
        if consulted is None:
            for key in ("fecha_consulta", "consulta", "timestamp", "fecha"):
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
        if src.endpoint:
            # "CIMA (AEMPS) REST v1.23 · obtener_medicamento"
            src = Source(
                endpoint=f"{src.endpoint} · {result.tool}", consulted_at=src.consulted_at
            )
        else:
            # Sin procedencia en el payload: etiquetamos con la tool usada.
            src = Source(endpoint=f"mcp-aemps:{result.tool}", consulted_at=src.consulted_at)
        sources.append(src)
    return sources


# Claves ruidosas del payload que no aportan evidencia y desplazan lo relevante
# (los 'docs' con URLs largas van ANTES que 'excipientes' en el detalle real).
_NOISY_KEYS = ("docs", "fotos", "materialesInf", "descargo_responsabilidad")
_MAX_LIST_ITEMS = 8


def _compact_payload(value: Any, depth: int = 0) -> Any:
    """Versión compacta de un payload para la vista del verificador."""
    if isinstance(value, dict):
        return {
            k: _compact_payload(v, depth + 1)
            for k, v in value.items()
            if k not in _NOISY_KEYS
        }
    if isinstance(value, list) and len(value) > _MAX_LIST_ITEMS:
        return [
            _compact_payload(v, depth + 1) for v in value[:_MAX_LIST_ITEMS]
        ] + [f"… ({len(value) - _MAX_LIST_ITEMS} elementos más omitidos)"]
    if isinstance(value, list):
        return [_compact_payload(v, depth + 1) for v in value]
    return value


def results_as_text(state: GraphState, max_chars_per_result: int = 4000) -> str:
    """Serializa los resultados recuperados para dárselos al nodo de verificación.

    Compacta cada payload (quita docs/fotos, recorta listas largas) y aplica el
    tope POR RESULTADO — un detalle enorme no puede desplazar al resto de la
    evidencia (los 'excipientes' del detalle real van después de bloques largos).
    """
    chunks: list[str] = []
    for result in state.get("tool_results", []):
        status = "OK" if result.ok else f"ERROR: {result.error}"
        src = result.source.endpoint or "—"
        payload = parse_content(result)
        if payload is not None and not isinstance(payload, str):
            body = json.dumps(_compact_payload(payload), ensure_ascii=False)
        else:
            body = result.content or "(sin contenido)"
        chunks.append(
            f"### tool={result.tool} args={result.args} ({status}) fuente={src}\n"
            f"{body[:max_chars_per_result]}"
        )
    return "\n\n".join(chunks)
