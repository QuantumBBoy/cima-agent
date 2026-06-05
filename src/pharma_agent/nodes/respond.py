"""Nodo RESPUESTA + FUENTES: redacta en lenguaje natural, antepone el disclaimer
de no-consejo-médico y lista las fuentes (endpoint AEMPS + fecha de consulta).

La salida estructurada (``PharmaAnswer``) queda disponible para que PharmaFast la
consuma programáticamente. La prosa la escribe el LLM, pero ceñida EXCLUSIVAMENTE
a los claims verificados; el ensamblado (disclaimer + claims + fuentes) es
determinista en código para que la salida estructurada esté siempre fundamentada.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from ..prompts import DISCLAIMER, OUT_OF_SCOPE_MESSAGE, RESPOND_PROMPT
from ..state import GraphState, PharmaAnswer
from ._helpers import collect_sources


def _render_claims(state: GraphState) -> str:
    lines = []
    for claim in state.get("verified_claims", []):
        mark = "✔" if claim.supported else "✖"
        val = claim.value or ("respaldado" if claim.supported else "no disponible en CIMA")
        lines.append(f"- [{mark}] {claim.statement} -> {val}")
    return "\n".join(lines) if lines else "(sin claims)"


def _format_sources(sources) -> str:
    if not sources:
        return ""
    items = []
    for s in sources:
        ep = s.endpoint or "fuente CIMA"
        when = f" (consultado: {s.consulted_at})" if s.consulted_at else ""
        items.append(f"- {ep}{when}")
    return "Fuentes:\n" + "\n".join(items)


def make_respond_node(llm):
    async def respond_node(state: GraphState) -> GraphState:
        intent = state.get("intent")
        sources = collect_sources(state)

        # Fuera de alcance: mensaje fijo, sin LLM, sin fuentes.
        if intent == "desconocido":
            answer = f"{DISCLAIMER}\n\n{OUT_OF_SCOPE_MESSAGE}"
            structured = PharmaAnswer(
                disclaimer=DISCLAIMER, medicine_found=False, answer=OUT_OF_SCOPE_MESSAGE
            )
            return {"answer": answer, "sources": [], "structured_answer": structured}

        context = (
            f"CONSULTA: {state['query']}\n"
            f"MEDICAMENTO ENCONTRADO EN CIMA: {state.get('medicine_found', False)}\n\n"
            f"CLAIMS VERIFICADOS:\n{_render_claims(state)}"
        )
        msg = await llm.ainvoke(
            [SystemMessage(content=RESPOND_PROMPT), HumanMessage(content=context)]
        )
        prose = getattr(msg, "content", str(msg)).strip()

        parts = [DISCLAIMER, "", prose]
        sources_block = _format_sources(sources)
        if sources_block:
            parts += ["", sources_block]
        answer = "\n".join(parts)

        structured = PharmaAnswer(
            disclaimer=DISCLAIMER,
            medicine_found=state.get("medicine_found", False),
            answer=prose,
            claims=state.get("verified_claims", []),
            sources=sources,
        )
        return {"answer": answer, "sources": sources, "structured_answer": structured}

    return respond_node
