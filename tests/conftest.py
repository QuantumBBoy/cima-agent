"""Fixtures comunes: dobles de LLM/tools y constructores de datos CIMA."""

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


# --- Datos CIMA de ejemplo (forma aproximada de la CIMA REST API) ----------

IBUPROFENO_HIT = {
    "resultados": [
        {
            "nregistro": "51347",
            "nombre": "IBUPROFENO CINFA 600 mg COMPRIMIDOS",
            "cn": "712345",
            "labtitular": "CINFA",
        }
    ],
    "endpoint": "https://cima.aemps.es/cima/rest/medicamentos",
    "fecha_consulta": "2026-06-05",
}

IBUPROFENO_DETALLE = {
    "nregistro": "51347",
    "nombre": "IBUPROFENO CINFA 600 mg COMPRIMIDOS",
    "cn": "712345",
    "receta": True,
    "comerc": True,
    "endpoint": "https://cima.aemps.es/cima/rest/medicamento",
    "fecha_consulta": "2026-06-05",
}


@pytest.fixture
def cima_ibuprofeno():
    return {"hit": IBUPROFENO_HIT, "detalle": IBUPROFENO_DETALLE}
