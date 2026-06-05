"""Nodo de VERIFICACIÓN: antes de redactar, comprueba que cada afirmación está
respaldada por un dato recuperado de AEMPS. Lo no respaldado se marca como
"no disponible en CIMA" en vez de alucinarse.

Este es el diferenciador de calidad: convierte "un chatbot que habla de
medicinas" en "un agente que solo afirma lo que la fuente oficial dice".
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..prompts import VERIFY_PROMPT
from ..state import GraphState, VerifiedClaim
from ._helpers import resolve_medicine, results_as_text


class Verification(BaseModel):
    """Salida estructurada del verificador."""

    medicine_found: bool = Field(description="¿Se resolvió algún medicamento en CIMA?")
    claims: list[VerifiedClaim] = Field(default_factory=list)


def make_verify_node(llm):
    structured = llm.with_structured_output(Verification)

    async def verify_node(state: GraphState) -> GraphState:
        # Caso fuera de alcance: nada que verificar.
        if state.get("intent") == "desconocido":
            return {"verified_claims": [], "medicine_found": False}

        evidence = results_as_text(state)
        context = (
            f"CONSULTA: {state['query']}\n"
            f"INTENCIÓN: {state.get('intent')}\n\n"
            f"RESULTADOS RECUPERADOS DE CIMA:\n{evidence or '(no se recuperó nada)'}"
        )
        result: Verification = await structured.ainvoke(
            [SystemMessage(content=VERIFY_PROMPT), HumanMessage(content=context)]
        )

        # Cinturón y tirantes: si no hubo medicamento resuelto, lo forzamos a False
        # aunque el LLM diga lo contrario.
        medicine_found = result.medicine_found and resolve_medicine(state) is not None
        return {"verified_claims": result.claims, "medicine_found": medicine_found}

    return verify_node
