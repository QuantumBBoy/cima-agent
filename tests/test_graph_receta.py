"""Integración (mcp-aemps mockeado): el flujo completo de "¿necesito receta para
X?" resuelve el fármaco, lee el campo `receta` y responde con su fuente."""

from __future__ import annotations

import pytest

from pharma_agent.graph import build_graph
from pharma_agent.nodes.triage import TriageResult
from pharma_agent.nodes.verify import Verification
from pharma_agent.state import MAX_ITERATIONS, VerifiedClaim, initial_state
from pharma_agent.testing import FakeLLM, FakeTool


@pytest.mark.asyncio
async def test_flujo_receta_resuelve_lee_y_cita_fuente(cima_ibuprofeno):
    buscar = FakeTool("buscar_medicamentos", cima_ibuprofeno["hit"], accepted=["nombre"])
    obtener = FakeTool(
        "obtener_medicamento", cima_ibuprofeno["detalle"], accepted=["nregistro", "cn"]
    )
    tools = {"buscar_medicamentos": buscar, "obtener_medicamento": obtener}

    fake = FakeLLM(
        structured={
            "TriageResult": TriageResult(intent="receta", nombre="ibuprofeno", dosis="600 mg"),
            "Verification": Verification(
                medicine_found=True,
                claims=[
                    VerifiedClaim(
                        statement="El medicamento necesita receta médica",
                        supported=True,
                        value="Sí, con receta",
                        evidence='"receta": true',
                    )
                ],
            ),
        },
        prose="El ibuprofeno 600 mg necesita receta médica.",
    )

    agent = build_graph(fake, tools)
    final = await agent.ainvoke(initial_state("¿necesito receta para el ibuprofeno 600 mg?"))

    # El planificador resolvió el fármaco y luego leyó su detalle.
    assert buscar.calls == [{"nombre": "ibuprofeno"}]
    assert obtener.calls == [{"nregistro": "51347"}]  # 'cn' se filtró: el plan solo pasó nregistro

    # Respuesta fundamentada y con fuente.
    assert final["medicine_found"] is True
    assert final["structured_answer"].sources, "debe citar al menos una fuente CIMA"
    assert final["answer"].startswith("⚠️")
    assert "Fuentes:" in final["answer"]
    assert final["iterations"] <= MAX_ITERATIONS


@pytest.mark.asyncio
async def test_farmaco_inexistente_no_inventa(cima_ibuprofeno):
    buscar = FakeTool("buscar_medicamentos", {"resultados": []}, accepted=["nombre"])
    obtener = FakeTool("obtener_medicamento", cima_ibuprofeno["detalle"], accepted=["nregistro"])
    tools = {"buscar_medicamentos": buscar, "obtener_medicamento": obtener}

    fake = FakeLLM(
        structured={
            "TriageResult": TriageResult(intent="receta", nombre="farmacoinventado"),
            "Verification": Verification(medicine_found=False, claims=[]),
        },
        prose="No aparece en CIMA ningún medicamento con ese nombre.",
    )

    agent = build_graph(fake, tools)
    final = await agent.ainvoke(initial_state("¿necesito receta para farmacoinventado?"))

    # Buscó una vez y NO insistió ni leyó el detalle de un fármaco que no existe.
    assert len(buscar.calls) == 1
    assert obtener.calls == []
    assert final["medicine_found"] is False
