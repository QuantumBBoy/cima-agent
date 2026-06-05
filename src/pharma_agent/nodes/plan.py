"""Nodo PLANIFICADOR: decide la secuencia de tools según la intención y lo ya
recuperado. Es el nodo que demuestra que el agente RAZONA sobre herramientas,
no solo las invoca.

Es determinista (sin LLM): dado el estado, elige el siguiente paso. Esto lo hace
fácil de testear ("el planificador elige las tools correctas para cada intent")
y soporta de forma natural el bucle de suficiencia: mientras devuelva pasos,
se ejecutan; cuando devuelve ``[]``, el agente da por suficiente la información.

Los nombres y argumentos de las tools siguen el README de mcp-aemps. Las claves
"núcleo" (nombre / nregistro / cn) son las de la CIMA REST API; el executor filtra
las claves que cada tool no acepte, así que añadir pistas extra es seguro.
"""

from __future__ import annotations

from ..state import Entities, GraphState, PlannedCall
from ._helpers import (
    resolve_medicine,
    results_for,
    search_returned_empty,
    tool_was_run,
)


def _entities(state: GraphState) -> Entities:
    return state.get("entities") or Entities()


def _resolve_and_update(state: GraphState) -> tuple[dict | None, Entities]:
    """Resuelve el medicamento y propaga nregistro/cn a las entidades."""
    ents = _entities(state)
    med = resolve_medicine(state)
    if med:
        if med.get("nregistro") and not ents.nregistro:
            ents = ents.model_copy(update={"nregistro": str(med["nregistro"])})
        if med.get("cn") and not ents.cn:
            ents = ents.model_copy(update={"cn": str(med["cn"])})
    return med, ents


def _resolve_step(ents: Entities) -> list[PlannedCall]:
    """Paso de resolución del fármaco por nombre."""
    return [
        PlannedCall(
            tool="buscar_medicamentos",
            args={"nombre": ents.nombre},
            purpose=f"Resolver el medicamento '{ents.nombre}' en CIMA",
        )
    ]


def plan_node(state: GraphState) -> GraphState:
    intent = state.get("intent", "desconocido")
    ents = _entities(state)

    # Fuera de alcance: no se llama a ninguna tool; respond emitirá el mensaje.
    if intent == "desconocido":
        return {"plan": [], "entities": ents}

    # Sin nombre de fármaco no hay nada que consultar.
    if not ents.nombre and intent in ("receta", "suministro", "ficha_tecnica", "alternativa"):
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
    args = {"nregistro": ents.nregistro} if ents.nregistro else {"cn": ents.cn}
    return [
        PlannedCall(
            tool="obtener_medicamento",
            args=args,
            purpose="Leer el campo 'receta' (condiciones de dispensación) del medicamento",
        )
    ]


def _plan_suministro(state: GraphState, ents: Entities, med: dict | None) -> list[PlannedCall]:
    if not med:
        return _resolve_step(ents)
    if tool_was_run(state, "problemas_suministro_dcpf"):
        return []
    args: dict = {"nombre": ents.nombre}
    if ents.nregistro:
        args["nregistro"] = ents.nregistro
    if ents.cn:
        args["cn"] = ents.cn
    return [
        PlannedCall(
            tool="problemas_suministro_dcpf",
            args=args,
            purpose="Comprobar problemas de suministro del medicamento",
        )
    ]


def _plan_ficha_tecnica(state: GraphState, ents: Entities, med: dict | None) -> list[PlannedCall]:
    if not med:
        return _resolve_step(ents)

    # Si pide un excipiente o término concreto -> buscar_en_ficha_tecnica.
    termino = ents.excipiente or ents.termino_busqueda
    if termino and not tool_was_run(state, "buscar_en_ficha_tecnica"):
        args: dict = {"texto": termino}
        if ents.nregistro:
            args["nregistro"] = ents.nregistro
        return [
            PlannedCall(
                tool="buscar_en_ficha_tecnica",
                args=args,
                purpose=f"Buscar '{termino}' en la ficha técnica",
            )
        ]

    # Si pide una sección concreta -> doc_contenido (tipo 1 = ficha técnica).
    if ents.seccion and not tool_was_run(state, "doc_contenido"):
        args = {"tipo": 1}
        if ents.nregistro:
            args["nregistro"] = ents.nregistro
        if ents.cn:
            args["cn"] = ents.cn
        args["seccion"] = ents.seccion
        return [
            PlannedCall(
                tool="doc_contenido",
                args=args,
                purpose=f"Leer la sección {ents.seccion} de la ficha técnica",
            )
        ]

    # Sin término ni sección: con el detalle del medicamento basta.
    if not tool_was_run(state, "obtener_medicamento"):
        args = {"nregistro": ents.nregistro} if ents.nregistro else {"cn": ents.cn}
        return [
            PlannedCall(
                tool="obtener_medicamento",
                args=args,
                purpose="Recuperar el detalle del medicamento y su documentación",
            )
        ]
    return []


def _plan_alternativa(state: GraphState, ents: Entities, med: dict | None) -> list[PlannedCall]:
    # "Equivalente sin lactosa" -> buscar_vmpp + buscar_en_ficha_tecnica("lactosa").
    if not tool_was_run(state, "buscar_vmpp"):
        args: dict = {"nombre": ents.nombre}
        if ents.nregistro:
            args["nregistro"] = ents.nregistro
        return [
            PlannedCall(
                tool="buscar_vmpp",
                args=args,
                purpose="Buscar equivalentes clínicos (mismo VMP)",
            )
        ]
    # Si hay restricción por excipiente, filtramos buscándolo en la FT.
    if ents.excipiente and not tool_was_run(state, "buscar_en_ficha_tecnica"):
        return [
            PlannedCall(
                tool="buscar_en_ficha_tecnica",
                args={"texto": ents.excipiente},
                purpose=f"Detectar '{ents.excipiente}' como excipiente entre los equivalentes",
            )
        ]
    return []
