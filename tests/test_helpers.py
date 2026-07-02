"""Unit: procedencia desde `metadata` (forma real de mcp-aemps) y compactación
de payloads para el verificador."""

from __future__ import annotations

from pharma_agent.nodes._helpers import (
    _compact_payload,
    collect_sources,
    extract_source,
    results_as_text,
)
from pharma_agent.state import Source, ToolResult

from conftest import tool_result


def test_extract_source_lee_metadata_real():
    payload = {
        "resultados": [],
        "metadata": {
            "fuente": "CIMA (AEMPS)",
            "fecha_consulta": "02/07/2026 08:30 UTC",
            "version_api": "1.23",
        },
    }
    src = extract_source(payload, retrieved_at="2026-07-02T08:30:00+00:00")
    assert src.endpoint == "CIMA (AEMPS) REST v1.23"
    assert src.consulted_at == "02/07/2026 08:30 UTC"


def test_extract_source_cae_al_timestamp_local_sin_metadata():
    src = extract_source({"resultados": []}, retrieved_at="2026-07-02T09:00:00+00:00")
    assert src.endpoint is None
    assert src.consulted_at == "2026-07-02T09:00:00+00:00"


def test_collect_sources_etiqueta_con_fuente_y_tool():
    result = ToolResult(
        tool="obtener_medicamento",
        ok=True,
        content="{}",
        source=Source(endpoint="CIMA (AEMPS) REST v1.23", consulted_at="02/07/2026"),
    )
    sources = collect_sources({"tool_results": [result]})
    assert sources[0].endpoint == "CIMA (AEMPS) REST v1.23 · obtener_medicamento"


def test_compact_payload_quita_ruido_y_recorta_listas():
    payload = {
        "nombre": "X",
        "docs": [{"url": "https://..."}],  # ruido: fuera
        "fotos": [],
        "excipientes": [{"nombre": f"E{i}"} for i in range(20)],  # se recorta
    }
    compact = _compact_payload(payload)
    assert "docs" not in compact and "fotos" not in compact
    assert len(compact["excipientes"]) == 9  # 8 + marcador de omisión
    assert "omitidos" in compact["excipientes"][-1]


def test_results_as_text_no_deja_que_un_detalle_enorme_desplace_al_resto():
    grande = tool_result("obtener_medicamento", {"relleno": "x" * 10_000})
    clave = tool_result(
        "problemas_suministro",
        {"data": {"712345": {"observ": "Sin problemas de suministro reportados"}}},
    )
    text = results_as_text({"tool_results": [grande, clave]})
    # El segundo resultado sigue visible pese al tamaño del primero.
    assert "Sin problemas de suministro reportados" in text


def test_results_as_text_serializa_compactado():
    detalle = {
        "nregistro": "51347",
        "docs": [{"url": "u"}],
        "excipientes": [{"nombre": "LACTOSA MONOHIDRATO"}],
    }
    text = results_as_text({"tool_results": [tool_result("obtener_medicamento", detalle)]})
    assert "LACTOSA MONOHIDRATO" in text
    assert '"docs"' not in text  # el ruido se eliminó de la vista del verificador
