"""Demo EN VIVO: mismo flujo, pero contra mcp-aemps real y un LLM real.

Requiere 'uvx' y, en tu .env, PHARMA_AGENT_MODEL + la API key del proveedor
(p. ej. un modelo de Ollama Cloud: PHARMA_AGENT_MODEL=ollama:gpt-oss:20b y
OLLAMA_API_KEY=...). Silencia los logs del servidor para una salida limpia.

    python examples/live_demo.py "¿necesita receta el omeprazol 20 mg?"
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _demo_render import stream_agent  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from pharma_agent.graph import build_graph  # noqa: E402
from pharma_agent.llm import get_llm  # noqa: E402
from pharma_agent.mcp_client import MCPUnavailableError, load_aemps_tools  # noqa: E402
from pharma_agent.state import initial_state  # noqa: E402

DEFAULT_QUERY = "¿necesita receta el omeprazol 20 mg?"


async def main() -> None:
    load_dotenv()
    logging.disable(logging.WARNING)  # silencia logs de mcp/httpx para el GIF
    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY

    try:
        tools = await load_aemps_tools()
    except MCPUnavailableError as exc:
        print(f"[setup] {exc}", file=sys.stderr)
        return

    agent = build_graph(get_llm(), tools)
    delay = float(os.getenv("DEMO_DELAY", "0"))  # la latencia real ya marca el ritmo
    await stream_agent(agent, query, initial_state(query), delay=delay)


if __name__ == "__main__":
    asyncio.run(main())
