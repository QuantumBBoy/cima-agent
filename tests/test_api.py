"""Integración de la API HTTP (FastAPI) con LLM y mcp-aemps mockeados.

El TestClient ejecuta el lifespan (carga del grafo) al entrar en el `with`.
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi", reason="requiere el extra 'api'")

from fastapi.testclient import TestClient  # noqa: E402

from pharma_agent.api import create_app  # noqa: E402
from pharma_agent.nodes.triage import TriageResult  # noqa: E402
from pharma_agent.nodes.verify import Verification  # noqa: E402
from pharma_agent.state import VerifiedClaim  # noqa: E402
from pharma_agent.testing import FakeLLM, FakeTool  # noqa: E402


def _fake_llm() -> FakeLLM:
    return FakeLLM(
        structured={
            "TriageResult": TriageResult(intent="receta", nombre="ibuprofeno", dosis="600 mg"),
            "Verification": Verification(
                medicine_found=True,
                claims=[
                    VerifiedClaim(
                        statement="El medicamento necesita receta",
                        supported=True,
                        value="Sí, con receta",
                        evidence='"receta": true',
                    )
                ],
            ),
        },
        prose="Según CIMA, necesita receta médica.",
    )


def _fake_tools(cima) -> dict:
    return {
        "buscar_medicamentos": FakeTool("buscar_medicamentos", cima["hit"], accepted=["nombre"]),
        "obtener_medicamento": FakeTool(
            "obtener_medicamento", cima["detalle"], accepted=["nregistro", "cn"]
        ),
    }


def test_health_y_consulta_estructurada(cima_ibuprofeno):
    app = create_app(llm=_fake_llm(), tools=_fake_tools(cima_ibuprofeno))
    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health == {"status": "ok", "agent_ready": True}

        resp = client.post(
            "/consulta", json={"query": "¿necesito receta para el ibuprofeno 600 mg?"}
        )
        assert resp.status_code == 200
        body = resp.json()
        # Contrato PharmaAnswer: disclaimer + claims verificados + fuentes.
        assert body["medicine_found"] is True
        assert body["disclaimer"].startswith("⚠️")
        assert body["claims"][0]["supported"] is True
        assert body["sources"], "debe citar fuentes CIMA"


def test_consulta_fuera_de_alcance_no_da_consejo(cima_ibuprofeno):
    llm = FakeLLM(
        structured={
            "TriageResult": TriageResult(intent="desconocido"),
            # build_graph crea el nodo verify (y su salida estructurada) aunque
            # el camino fuera-de-alcance nunca lo invoque.
            "Verification": Verification(medicine_found=False, claims=[]),
        },
        prose="(no debería usarse)",
    )
    app = create_app(llm=llm, tools=_fake_tools(cima_ibuprofeno))
    with TestClient(app) as client:
        resp = client.post("/consulta", json={"query": "¿qué dosis me tomo para el dolor?"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["medicine_found"] is False
        assert "no puede dar" in body["answer"]
        assert body["sources"] == []


def test_query_invalida_devuelve_422(cima_ibuprofeno):
    app = create_app(llm=_fake_llm(), tools=_fake_tools(cima_ibuprofeno))
    with TestClient(app) as client:
        assert client.post("/consulta", json={"query": "ab"}).status_code == 422
        assert client.post("/consulta", json={}).status_code == 422
