"""pharma_agent: agente LangGraph que consume mcp-aemps (AEMPS/CIMA).

Capa de CONSUMO sobre el servidor MCP mcp-aemps (https://github.com/romanpert/mcp-aemps).
No reimplementa nada del servidor: lo lanza por stdio y orquesta sus tools.
"""

from .graph import build_graph
from .state import GraphState, MedicinePhoto, PharmaAnswer, initial_state

__all__ = ["build_graph", "GraphState", "MedicinePhoto", "PharmaAnswer", "initial_state", "run_query"]

__version__ = "0.1.0"


async def run_query(query: str, *, llm=None, tools=None):
    """Atajo de alto nivel: conecta a mcp-aemps (si no se inyectan tools), construye
    el grafo y resuelve una consulta. Devuelve el estado final.
    """
    from .llm import get_llm
    from .mcp_client import load_aemps_tools
    from .state import initial_state

    llm = llm or get_llm()
    tools = tools if tools is not None else await load_aemps_tools()
    agent = build_graph(llm, tools)
    return await agent.ainvoke(initial_state(query))
