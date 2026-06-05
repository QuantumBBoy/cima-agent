"""Unit: el nodo de verificación y la redacción NO afirman lo no respaldado.

Este es el test que justifica el nodo de verificación: dado un resultado de tool
que NO contiene cierto dato, el agente lo marca "no disponible en CIMA" en vez de
inventarlo, y la salida estructurada solo arrastra lo que verify produjo.
"""

from __future__ import annotations

import pytest

from pharma_agent.nodes.respond import make_respond_node
from pharma_agent.nodes.verify import Verification, make_verify_node
from pharma_agent.state import VerifiedClaim
from pharma_agent.testing import FakeLLM


@pytest.mark.asyncio
async def test_verify_fuerza_medicine_found_false_si_no_hay_medicamento():
    # El LLM "afirma" que encontró medicamento, pero no hay ningún tool_result:
    # el nodo lo corrige a False (cinturón y tirantes contra alucinaciones).
    fake = FakeLLM(
        structured={
            "Verification": Verification(
                medicine_found=True,
                claims=[
                    VerifiedClaim(
                        statement="El medicamento necesita receta",
                        supported=False,
                        value="no disponible en CIMA",
                    )
                ],
            )
        }
    )
    node = make_verify_node(fake)

    out = await node({"query": "q", "intent": "receta", "tool_results": []})

    assert out["medicine_found"] is False
    assert out["verified_claims"][0].supported is False


@pytest.mark.asyncio
async def test_respond_marca_dato_no_respaldado_como_no_disponible():
    fake = FakeLLM(prose="Según CIMA, el dato solicitado no consta en la ficha técnica.")
    node = make_respond_node(fake)

    state = {
        "query": "¿qué dice la sección 4.8?",
        "intent": "ficha_tecnica",
        "medicine_found": True,
        "verified_claims": [
            VerifiedClaim(
                statement="La FT incluye la sección 4.8",
                supported=False,
                value="no disponible en CIMA",
            )
        ],
        "tool_results": [],
    }
    out = await node(state)

    sa = out["structured_answer"]
    # La salida estructurada solo arrastra lo verificado, sin fabricar nada.
    assert len(sa.claims) == 1
    assert sa.claims[0].supported is False
    assert sa.claims[0].value == "no disponible en CIMA"
    # El disclaimer va por delante.
    assert out["answer"].startswith("⚠️")


@pytest.mark.asyncio
async def test_respond_fuera_de_alcance_no_llama_al_llm():
    # prose lanzaría si se invocase: confirmamos que el camino "desconocido" no usa LLM.
    def _boom(_):
        raise AssertionError("no debería invocarse el LLM en fuera de alcance")

    fake = FakeLLM(prose=_boom)
    node = make_respond_node(fake)

    out = await node({"query": "¿puedo tomar esto?", "intent": "desconocido", "tool_results": []})

    assert out["structured_answer"].medicine_found is False
    assert "no puede dar" in out["answer"]
