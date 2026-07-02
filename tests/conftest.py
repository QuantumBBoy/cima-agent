"""Fixtures comunes: dobles de LLM/tools y constructores de datos CIMA.

Las formas de los payloads están tomadas de respuestas REALES de mcp-aemps
(sondeo en vivo), recortadas: `metadata` con fuente/fecha/versión, detalle con
`excipientes`/`psum`/`vtm`, suministro como `{"data": {cn: {...}}}` y VMPP con
`vmpDesc`/`vmppDesc`.
"""

from __future__ import annotations

import json

import pytest

from pharma_agent.state import ToolResult
from pharma_agent.testing import FakeLLM, FakeTool

__all__ = ["FakeLLM", "FakeTool"]


def tool_result(tool: str, payload: dict | list, ok: bool = True) -> ToolResult:
    """Construye un ToolResult con contenido JSON, como lo haría el executor."""
    return ToolResult(tool=tool, ok=ok, content=json.dumps(payload, ensure_ascii=False))


@pytest.fixture
def make_tool_result():
    return tool_result


# --- Datos CIMA de ejemplo (forma real de mcp-aemps, recortada) -------------

METADATA = {
    "fuente": "CIMA (AEMPS)",
    "fecha_consulta": "02/07/2026 08:30 UTC",
    "version_api": "1.23",
}

IBUPROFENO_HIT = {
    "totalFilas": 2,
    "pagina": 1,
    "tamanioPagina": 200,
    "resultados": [
        {
            "nregistro": "51347",
            "nombre": "IBUPROFENO CINFA 600 mg COMPRIMIDOS",
            "cn": "712345",
            "labtitular": "CINFA",
        }
    ],
    "metadata": METADATA,
}

IBUPROFENO_DETALLE = {
    "nregistro": "51347",
    "nombre": "IBUPROFENO CINFA 600 mg COMPRIMIDOS",
    "cn": "712345",
    "pactivos": "IBUPROFENO",
    "vtm": {"id": 387207008, "nombre": "ibuprofeno"},
    "receta": True,
    "comerc": True,
    "psum": False,
    "excipientes": [
        {"id": 1, "nombre": "LACTOSA MONOHIDRATO", "cantidad": "50", "unidad": "mg", "orden": 1},
        {"id": 2, "nombre": "ALMIDON DE MAIZ", "cantidad": None, "unidad": None, "orden": 2},
    ],
    "presentaciones": [
        {"cn": "712345", "nombre": "IBUPROFENO CINFA 600 mg, 40 comprimidos", "psum": False}
    ],
    "metadata": METADATA,
}

SUMINISTRO_PAYLOAD = {
    "data": {
        "712345": {
            "cn": 712345,
            "nombre": "IBUPROFENO CINFA 600 mg, 40 comprimidos",
            "comerc": True,
            "observ": "Sin problemas de suministro reportados",
            "tipoProblemaSuministro_descripcion": "No existen problemas detectados",
            "fecha_inicio": None,
            "fecha_fin": None,
        }
    },
    "metadata": METADATA,
}

VMPP_PAYLOAD = {
    "totalFilas": 2,
    "pagina": 1,
    "tamanioPagina": 200,
    "resultados": [
        {
            "vmp": "329738003",
            "vmpDesc": "Ibuprofeno 600 mg comprimido",
            "vmpp": "329739006",
            "vmppDesc": "Ibuprofeno 600 mg 40 comprimidos",
            "presComerc": 12,
        }
    ],
    "metadata": METADATA,
}


@pytest.fixture
def cima_ibuprofeno():
    return {
        "hit": IBUPROFENO_HIT,
        "detalle": IBUPROFENO_DETALLE,
        "suministro": SUMINISTRO_PAYLOAD,
        "vmpp": VMPP_PAYLOAD,
        "metadata": METADATA,
    }
