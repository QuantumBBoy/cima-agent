"""Construcción del StateGraph: nodos + edges condicionales.

Flujo (mapa con el diagrama del spec):

    START → triage → plan ─┬─(hay pasos)→ execute ─┬─(¿suficiente?)→ plan
                           │                        └─(tope o fin)──→ verify → respond → END
                           └─(nada que hacer)──────────────────────→ verify

- "plan" decide el siguiente paso; cuando devuelve ``[]`` da por suficiente.
- "¿Suficiente?" es la arista condicional tras execute: vuelve a plan salvo que
  se alcance MAX_ITERATIONS, en cuyo caso pasa a verify con lo que haya.
"""

from __future__ import annotations

from typing import Any, Optional

from langgraph.graph import END, START, StateGraph

from .nodes import (
    make_execute_node,
    make_respond_node,
    make_triage_node,
    make_verify_node,
    plan_node,
)
from .state import MAX_ITERATIONS, GraphState


def _route_after_plan(state: GraphState) -> str:
    """¿Hay tools que ejecutar? Si no, pasamos a verificar."""
    return "execute" if state.get("plan") else "verify"


def _is_sufficient(state: GraphState) -> str:
    """Nodo condicional '¿Suficiente?': re-planifica salvo que toquemos el tope."""
    if state.get("iterations", 0) >= MAX_ITERATIONS:
        return "verify"
    return "plan"


def build_graph(llm: Any, tools: dict[str, Any], *, checkpointer: Optional[Any] = None):
    """Construye y compila el grafo.

    ``llm`` y ``tools`` se inyectan para poder testear sin red ni claves.
    """
    graph = StateGraph(GraphState)

    graph.add_node("triage", make_triage_node(llm))
    graph.add_node("plan", plan_node)
    graph.add_node("execute", make_execute_node(tools))
    graph.add_node("verify", make_verify_node(llm))
    graph.add_node("respond", make_respond_node(llm))

    graph.add_edge(START, "triage")
    graph.add_edge("triage", "plan")
    graph.add_conditional_edges(
        "plan", _route_after_plan, {"execute": "execute", "verify": "verify"}
    )
    graph.add_conditional_edges(
        "execute", _is_sufficient, {"plan": "plan", "verify": "verify"}
    )
    graph.add_edge("verify", "respond")
    graph.add_edge("respond", END)

    return graph.compile(checkpointer=checkpointer)
