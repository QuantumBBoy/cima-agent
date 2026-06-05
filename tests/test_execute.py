"""Unit: el executor desempaqueta los bloques de contenido MCP y sella procedencia.

Regresión del bug real encontrado integrando mcp-aemps: langchain-mcp-adapters
devuelve ``[{"type":"text","text":"<JSON>"}]`` y el JSON de CIMA vive dentro de
``text``. Si no se desempaqueta, el agente no encuentra ``resultados`` y entra en
bucle reportando "no encontrado".
"""

from __future__ import annotations

import json

import pytest

from pharma_agent.nodes.execute import _normalize_content, make_execute_node
from pharma_agent.state import PlannedCall
from pharma_agent.testing import FakeTool


def test_normalize_desempaqueta_bloques_mcp():
    cima = {"totalFilas": 1, "resultados": [{"nregistro": "80298", "nombre": "X"}]}
    blocks = [{"type": "text", "text": json.dumps(cima), "id": "abc"}]
    assert json.loads(_normalize_content(blocks)) == cima


def test_normalize_desempaqueta_bloques_mcp_serializados_a_string():
    # langchain-mcp-adapters a veces entrega la lista de bloques ya serializada.
    cima = {"resultados": [{"nregistro": "80298", "nombre": "X"}]}
    blocks_str = json.dumps([{"type": "text", "text": json.dumps(cima), "id": "abc"}])
    assert json.loads(_normalize_content(blocks_str)) == cima


def test_normalize_ignora_bloques_de_recurso_sin_texto():
    # Caso real: 1 bloque de texto (JSON de CIMA) + N bloques de recurso sin 'text'.
    cima = {"resultados": [{"nregistro": "80298", "nombre": "X"}]}
    blocks = [
        {"type": "text", "text": json.dumps(cima), "id": "1"},
        {"type": "resource", "id": "2", "url": "https://cima/doc", "mime_type": "application/pdf"},
    ]
    assert json.loads(_normalize_content(blocks)) == cima


def test_normalize_pasa_strings_y_serializa_otros():
    assert _normalize_content('{"a":1}') == '{"a":1}'
    assert json.loads(_normalize_content({"a": 1})) == {"a": 1}


@pytest.mark.asyncio
async def test_execute_guarda_el_json_de_cima_desde_bloques_mcp():
    cima = {"resultados": [{"nregistro": "80298", "nombre": "IBUPROFENO X"}]}

    class MCPBlockTool(FakeTool):
        async def ainvoke(self, args):
            self.calls.append(args)
            return [{"type": "text", "text": json.dumps(cima), "id": "1"}]

    tools = {"buscar_medicamentos": MCPBlockTool("buscar_medicamentos", None, accepted=["nombre"])}
    node = make_execute_node(tools)

    out = await node(
        {
            "plan": [PlannedCall(tool="buscar_medicamentos", args={"nombre": "ibuprofeno"})],
            "iterations": 0,
            "tool_results": [],
        }
    )
    result = out["tool_results"][0]
    assert result.ok
    assert json.loads(result.content) == cima
    assert out["iterations"] == 1
