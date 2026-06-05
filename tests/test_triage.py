"""Unit: el triaje clasifica la intención y extrae las entidades correctas."""

from __future__ import annotations

import pytest

from pharma_agent.nodes.triage import TriageResult, make_triage_node
from pharma_agent.testing import FakeLLM


@pytest.mark.asyncio
async def test_triage_clasifica_receta_y_extrae_entidades():
    fake = FakeLLM(
        structured={
            "TriageResult": TriageResult(
                intent="receta",
                nombre="ibuprofeno",
                dosis="600 mg",
                forma="comprimidos",
            )
        }
    )
    node = make_triage_node(fake)

    out = await node({"query": "¿necesito receta para el ibuprofeno 600 mg comprimidos?"})

    assert out["intent"] == "receta"
    assert out["entities"].nombre == "ibuprofeno"
    assert out["entities"].dosis == "600 mg"
    assert out["entities"].forma == "comprimidos"
    assert out["iterations"] == 0


@pytest.mark.asyncio
async def test_triage_marca_fuera_de_alcance():
    fake = FakeLLM(structured={"TriageResult": TriageResult(intent="desconocido")})
    node = make_triage_node(fake)

    out = await node({"query": "¿qué dosis de ibuprofeno me tomo para mi dolor de cabeza?"})

    assert out["intent"] == "desconocido"
