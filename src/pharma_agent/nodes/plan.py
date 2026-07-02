"""Nodo PLANIFICADOR: decide la secuencia de tools según la intención y lo ya
recuperado. Es el nodo que demuestra que el agente RAZONA sobre herramientas,
no solo las invoca.

Es determinista (sin LLM): dado el estado, elige el siguiente paso. Esto lo hace
fácil de testear ("el planificador elige las tools correctas para cada intent")
y soporta de forma natural el bucle de suficiencia: mientras devuelva pasos,
se ejecutan; cuando devuelve ``[]``, el agente da por suficiente la información.

Los nombres y argumentos de las tools están VERIFICADOS EN VIVO contra
mcp-aemps (introspección de schemas + sondeo real), no copiados del README:
- ``problemas_suministro`` acepta ``nregistro``/``cn`` como LISTAS.
- ``doc_contenido`` usa ``tipo_doc`` (1=ficha técnica), no ``tipo``.
- ``buscar_vmpp`` filtra por ``practiv1`` (principio activo); ``nombre``
  devuelve 0 resultados para nombres comerciales.
- ``buscar_en_ficha_tecnica`` exige reglas ``{seccion, texto, contiene}``
  (la sección es obligatoria; 6.1 = lista de excipientes).
El detalle de ``obtener_medicamento`` ya trae ``excipientes``, ``psum`` y
``vtm``/``pactivos``, así que varias preguntas se responden sin tools extra.
"""

from __future__ import annotations

from ..state import Entities, GraphState, PlannedCall
from ._helpers import (
    parse_content,
    resolve_medicine,
    results_for,
    search_returned_empty,
    tool_was_run,
)


def _entities(state: GraphState) -> Entities:
    return state.get("entities") or Entities()


def _resolve_and_update(state: GraphState) -> tuple[dict | None, Entities]:
    """Resuelve el medicamento (prefiriendo nombre buscado + dosis pedida) y
    propaga nregistro/cn a las entidades."""
    ents = _entities(state)
    med = resolve_medicine(state, prefer=ents.nombre, prefer_dosis=ents.dosis)
    if med:
        if med.get("nregistro") and not ents.nregistro:
            ents = ents.model_copy(update={"nregistro": str(med["nregistro"])})
        if med.get("cn") and not ents.cn:
            ents = ents.model_copy(update={"cn": str(med["cn"])})
    return med, ents


def _detail(state: GraphState) -> dict | None:
    """El detalle completo (obtener_medicamento), si ya se recuperó."""
    for result in results_for(state, "obtener_medicamento"):
        payload = parse_content(result)
        if isinstance(payload, dict) and payload.get("nregistro"):
            return payload
    return None


def _resolve_step(ents: Entities) -> list[PlannedCall]:
    """Paso de resolución del fármaco por nombre."""
    return [
        PlannedCall(
            tool="buscar_medicamentos",
            args={"nombre": ents.nombre},
            purpose=f"Resolver el medicamento '{ents.nombre}' en CIMA",
        )
    ]


def _detail_step(ents: Entities, purpose: str) -> list[PlannedCall]:
    args = {"nregistro": ents.nregistro} if ents.nregistro else {"cn": ents.cn}
    return [PlannedCall(tool="obtener_medicamento", args=args, purpose=purpose)]


def plan_node(state: GraphState) -> GraphState:
    intent = state.get("intent", "desconocido")
    ents = _entities(state)

    # Fuera de alcance: no se llama a ninguna tool; respond emitirá el mensaje.
    if intent == "desconocido":
        return {"plan": [], "entities": ents}

    # Sin nombre de fármaco no hay nada que consultar.
    if not ents.nombre:
        return {"plan": [], "entities": ents}

    # Si ya buscamos y CIMA no devolvió nada, no insistimos: respond dirá
    # "no aparece en CIMA con ese nombre".
    if search_returned_empty(state):
        return {"plan": [], "entities": ents}

    med, ents = _resolve_and_update(state)

    if intent == "receta":
        plan = _plan_receta(state, ents, med)
    elif intent == "suministro":
        plan = _plan_suministro(state, ents, med)
    elif intent == "ficha_tecnica":
        plan = _plan_ficha_tecnica(state, ents, med)
    elif intent == "alternativa":
        plan = _plan_alternativa(state, ents, med)
    else:  # pragma: no cover - defensivo
        plan = []

    return {"plan": plan, "entities": ents}


def _plan_receta(state: GraphState, ents: Entities, med: dict | None) -> list[PlannedCall]:
    # "¿necesito receta para X?" -> resolver el fármaco -> leer el campo `receta`.
    if not med:
        return _resolve_step(ents)
    if tool_was_run(state, "obtener_medicamento"):
        return []  # ya tenemos el detalle con el campo `receta`
    return _detail_step(
        ents, "Leer el campo 'receta' (condiciones de dispensación) del medicamento"
    )


def _plan_suministro(state: GraphState, ents: Entities, med: dict | None) -> list[PlannedCall]:
    # Resolver -> detalle (flag `psum` global y por presentación) -> detalle por CN
    # con `problemas_suministro` (acepta nregistro/cn como LISTAS).
    if not med:
        return _resolve_step(ents)
    if not tool_was_run(state, "obtener_medicamento"):
        return _detail_step(ents, "Leer el flag 'psum' (problema de suministro) del detalle")
    if not tool_was_run(state, "problemas_suministro") and ents.nregistro:
        return [
            PlannedCall(
                tool="problemas_suministro",
                args={"nregistro": [ents.nregistro]},
                purpose="Detalle de problemas de suministro por presentación (CN)",
            )
        ]
    return []


def _plan_ficha_tecnica(state: GraphState, ents: Entities, med: dict | None) -> list[PlannedCall]:
    if not med:
        return _resolve_step(ents)

    # Excipientes o término concreto: el detalle ya trae la lista `excipientes`.
    if (ents.excipiente or ents.termino_busqueda) and not tool_was_run(
        state, "obtener_medicamento"
    ):
        que = ents.excipiente or ents.termino_busqueda
        return _detail_step(ents, f"Comprobar '{que}' en la lista de excipientes del detalle")

    # Sección concreta de la FT -> doc_contenido (tipo_doc=1 = ficha técnica).
    if ents.seccion and not tool_was_run(state, "doc_contenido"):
        args: dict = {"tipo_doc": 1, "seccion": ents.seccion}
        if ents.nregistro:
            args["nregistro"] = ents.nregistro
        elif ents.cn:
            args["cn"] = ents.cn
        return [
            PlannedCall(
                tool="doc_contenido",
                args=args,
                purpose=f"Leer la sección {ents.seccion} de la ficha técnica",
            )
        ]

    # Sin sección ni término: con el detalle del medicamento basta.
    if not tool_was_run(state, "obtener_medicamento"):
        return _detail_step(ents, "Recuperar el detalle del medicamento y su documentación")
    return []


def _plan_alternativa(state: GraphState, ents: Entities, med: dict | None) -> list[PlannedCall]:
    # "Equivalente de X" -> resolver -> detalle (principio activo) ->
    # buscar_vmpp(practiv1=...) -> (si hay excipiente a evitar) reglas en la FT.
    if not med:
        return _resolve_step(ents)
    if not tool_was_run(state, "obtener_medicamento"):
        return _detail_step(ents, "Obtener el principio activo (vtm/pactivos) del medicamento")

    if not tool_was_run(state, "buscar_vmpp"):
        detail = _detail(state) or med
        vtm = detail.get("vtm") or {}
        practiv = (vtm.get("nombre") if isinstance(vtm, dict) else None) or detail.get(
            "pactivos"
        )
        if not practiv:
            return []  # sin principio activo no hay búsqueda de equivalentes posible
        args: dict = {"practiv1": str(practiv)}
        if ents.dosis:
            args["dosis"] = ents.dosis
        return [
            PlannedCall(
                tool="buscar_vmpp",
                args=args,
                purpose=f"Buscar equivalentes clínicos (mismo VMP) de '{practiv}'",
            )
        ]

    # Restricción por excipiente: medicamentos SIN él en la sección 6.1 de la FT.
    if ents.excipiente and not tool_was_run(state, "buscar_en_ficha_tecnica"):
        return [
            PlannedCall(
                tool="buscar_en_ficha_tecnica",
                args={"reglas": [{"seccion": "6.1", "texto": ents.excipiente, "contiene": 0}]},
                purpose=f"Medicamentos sin '{ents.excipiente}' en la lista de excipientes",
            )
        ]
    return []
