"""Nodo de TRIAJE: clasifica la intención y extrae entidades (salida estructurada).

Dirige qué herramientas tienen sentido y evita llamadas a ciegas.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..prompts import TRIAGE_PROMPT
from ..state import Entities, GraphState, Intent


class TriageResult(BaseModel):
    """Salida estructurada del triaje (Pydantic)."""

    intent: Intent = Field(description="Tipo de consulta")
    nombre: str | None = None
    dosis: str | None = None
    forma: str | None = None
    seccion: str | None = None
    excipiente: str | None = None
    termino_busqueda: str | None = None


def make_triage_node(llm):
    structured = llm.with_structured_output(TriageResult)

    async def triage_node(state: GraphState) -> GraphState:
        result: TriageResult = await structured.ainvoke(
            [SystemMessage(content=TRIAGE_PROMPT), HumanMessage(content=state["query"])]
        )
        entities = Entities(
            nombre=result.nombre,
            dosis=result.dosis,
            forma=result.forma,
            seccion=result.seccion,
            excipiente=result.excipiente,
            termino_busqueda=result.termino_busqueda,
        )
        return {"intent": result.intent, "entities": entities, "iterations": 0}

    return triage_node
