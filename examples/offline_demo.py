"""Demo OFFLINE: ejecuta el grafo completo con mcp-aemps y el LLM mockeados.

No necesita red, ni 'uvx', ni API key. Muestra el flujo nodo a nodo
(triage -> plan -> execute -> verify -> respond) y la respuesta final.

    python examples/offline_demo.py

Variable opcional:  DEMO_DELAY=0  -> sin pausas entre nodos (por defecto 0.7s).
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _demo_render import stream_agent  # noqa: E402

from pharma_agent.graph import build_graph  # noqa: E402
from pharma_agent.nodes.triage import TriageResult  # noqa: E402
from pharma_agent.nodes.verify import Verification  # noqa: E402
from pharma_agent.state import VerifiedClaim, initial_state  # noqa: E402
from pharma_agent.testing import FakeLLM, FakeTool  # noqa: E402

HIT = {
    "resultados": [{"nregistro": "51347", "nombre": "IBUPROFENO CINFA 600 mg", "cn": "712345"}],
    "endpoint": "https://cima.aemps.es/cima/rest/medicamentos",
    "fecha_consulta": "2026-06-05",
}
DETALLE = {
    "nregistro": "51347",
    "nombre": "IBUPROFENO CINFA 600 mg COMPRIMIDOS",
    "receta": True,
    "endpoint": "https://cima.aemps.es/cima/rest/medicamento",
    "fecha_consulta": "2026-06-05",
}
QUERY = "¿necesito receta para el ibuprofeno 600 mg?"


async def main() -> None:
    tools = {
        "buscar_medicamentos": FakeTool("buscar_medicamentos", HIT, accepted=["nombre"]),
        "obtener_medicamento": FakeTool(
            "obtener_medicamento", DETALLE, accepted=["nregistro", "cn"]
        ),
    }
    llm = FakeLLM(
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
        prose="Según CIMA, el ibuprofeno 600 mg se dispensa con receta médica.",
    )

    agent = build_graph(llm, tools)
    delay = float(os.getenv("DEMO_DELAY", "0.7"))
    await stream_agent(agent, QUERY, initial_state(QUERY), delay=delay)


if __name__ == "__main__":
    asyncio.run(main())
