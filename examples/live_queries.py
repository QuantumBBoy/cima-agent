"""Consultas EN VIVO contra mcp-aemps real.

Requiere:
  - 'uvx' instalado (se lanza 'uvx mcp-aemps@latest stdio' automáticamente).
  - una API key del proveedor LLM y PHARMA_AGENT_MODEL en tu .env.

    python examples/live_queries.py
"""

from __future__ import annotations

import asyncio

from dotenv import load_dotenv

from pharma_agent import run_query
from pharma_agent.mcp_client import MCPUnavailableError

CONSULTAS = [
    "¿necesita receta el ibuprofeno 600 mg?",
    "¿hay problemas de suministro con el Adiro 100 mg?",
    "¿el paracetamol comprimidos lleva lactosa?",
    "busca un equivalente clínico del omeprazol 20 mg",
]


async def main() -> None:
    load_dotenv()
    for consulta in CONSULTAS:
        print("\n" + "#" * 72)
        print(f"CONSULTA: {consulta}")
        print("#" * 72)
        try:
            final = await run_query(consulta)
        except MCPUnavailableError as exc:
            print(f"[setup] {exc}")
            return
        print(final.get("answer", "(sin respuesta)"))


if __name__ == "__main__":
    asyncio.run(main())
