"""CLI: ``pharma-agent "¿necesito receta para el ibuprofeno 600 mg?"``

Conecta a mcp-aemps por stdio, ejecuta el grafo y muestra la respuesta con sus
fuentes. Los errores de setup se muestran como mensajes claros, no como tracebacks.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv

from .graph import build_graph
from .llm import get_llm
from .mcp_client import MCPUnavailableError, load_aemps_tools
from .state import initial_state


async def _run(query: str, structured: bool) -> int:
    try:
        tools = await load_aemps_tools()
    except MCPUnavailableError as exc:
        print(f"[setup] {exc}", file=sys.stderr)
        return 2

    try:
        llm = get_llm()
    except Exception as exc:  # noqa: BLE001
        print(
            "[setup] No se pudo inicializar el modelo LLM. Revisa PHARMA_AGENT_MODEL "
            f"y la API key del proveedor en tu .env.\nDetalle: {exc}",
            file=sys.stderr,
        )
        return 2

    agent = build_graph(llm, tools)
    try:
        final = await agent.ainvoke(initial_state(query))
    except Exception as exc:  # noqa: BLE001 - error en runtime del grafo (p. ej. LLM)
        print(
            "[error] Falló la ejecución del agente. Si es un problema de "
            "autenticación del LLM, revisa la API key del proveedor en tu .env.\n"
            f"Detalle: {exc}",
            file=sys.stderr,
        )
        return 1

    if structured:
        sa = final.get("structured_answer")
        if sa is not None:
            print(sa.model_dump_json(indent=2))
            return 0

    print(final.get("answer", "(sin respuesta)"))
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="pharma-agent",
        description="Agente farmacéutico sobre mcp-aemps (AEMPS/CIMA).",
    )
    parser.add_argument("query", help="Consulta en lenguaje natural")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime la salida estructurada (PharmaAnswer) en JSON",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.query, args.json))


if __name__ == "__main__":
    raise SystemExit(main())
