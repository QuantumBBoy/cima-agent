"""Unit: el planificador elige las tools correctas (args REALES verificados en
vivo) para cada intent y soporta el bucle sin repetir pasos."""

from __future__ import annotations

from pharma_agent.nodes.plan import plan_node
from pharma_agent.state import Entities

from conftest import tool_result


def _state(intent, entities, results=None):
    return {
        "intent": intent,
        "entities": entities,
        "tool_results": results or [],
        "iterations": 0,
    }


# --- receta ------------------------------------------------------------------

def test_receta_sin_resultados_resuelve_el_farmaco():
    state = _state("receta", Entities(nombre="ibuprofeno"))
    plan = plan_node(state)["plan"]
    assert [c.tool for c in plan] == ["buscar_medicamentos"]
    assert plan[0].args == {"nombre": "ibuprofeno"}


def test_receta_con_farmaco_resuelto_lee_obtener_medicamento(cima_ibuprofeno):
    state = _state(
        "receta",
        Entities(nombre="ibuprofeno"),
        [tool_result("buscar_medicamentos", cima_ibuprofeno["hit"])],
    )
    out = plan_node(state)
    plan = out["plan"]
    assert [c.tool for c in plan] == ["obtener_medicamento"]
    assert plan[0].args == {"nregistro": "51347"}
    # El nregistro resuelto se propaga a las entidades.
    assert out["entities"].nregistro == "51347"


def test_receta_con_detalle_ya_leido_termina(cima_ibuprofeno):
    state = _state(
        "receta",
        Entities(nombre="ibuprofeno"),
        [
            tool_result("buscar_medicamentos", cima_ibuprofeno["hit"]),
            tool_result("obtener_medicamento", cima_ibuprofeno["detalle"]),
        ],
    )
    assert plan_node(state)["plan"] == []


# --- suministro ---------------------------------------------------------------

def test_suministro_secuencia_detalle_y_problemas(cima_ibuprofeno):
    ents = Entities(nombre="ibuprofeno")
    # Tras resolver: primero el detalle (flag psum)...
    state = _state(
        "suministro", ents, [tool_result("buscar_medicamentos", cima_ibuprofeno["hit"])]
    )
    plan = plan_node(state)["plan"]
    assert [c.tool for c in plan] == ["obtener_medicamento"]

    # ...luego problemas_suministro con nregistro como LISTA (schema real).
    state = _state(
        "suministro",
        ents,
        [
            tool_result("buscar_medicamentos", cima_ibuprofeno["hit"]),
            tool_result("obtener_medicamento", cima_ibuprofeno["detalle"]),
        ],
    )
    plan = plan_node(state)["plan"]
    assert [c.tool for c in plan] == ["problemas_suministro"]
    assert plan[0].args == {"nregistro": ["51347"]}

    # ...y con todo recuperado, suficiente.
    state = _state(
        "suministro",
        ents,
        [
            tool_result("buscar_medicamentos", cima_ibuprofeno["hit"]),
            tool_result("obtener_medicamento", cima_ibuprofeno["detalle"]),
            tool_result("problemas_suministro", cima_ibuprofeno["suministro"]),
        ],
    )
    assert plan_node(state)["plan"] == []


# --- ficha_tecnica -------------------------------------------------------------

def test_ficha_tecnica_excipiente_usa_el_detalle(cima_ibuprofeno):
    # El detalle real ya trae la lista `excipientes`: no hace falta otra tool.
    state = _state(
        "ficha_tecnica",
        Entities(nombre="ibuprofeno", excipiente="lactosa"),
        [tool_result("buscar_medicamentos", cima_ibuprofeno["hit"])],
    )
    plan = plan_node(state)["plan"]
    assert [c.tool for c in plan] == ["obtener_medicamento"]
    assert plan[0].args == {"nregistro": "51347"}

    # Con el detalle recuperado, suficiente.
    state["tool_results"].append(
        tool_result("obtener_medicamento", cima_ibuprofeno["detalle"])
    )
    assert plan_node(state)["plan"] == []


def test_ficha_tecnica_seccion_usa_doc_contenido_con_tipo_doc(cima_ibuprofeno):
    state = _state(
        "ficha_tecnica",
        Entities(nombre="ibuprofeno", seccion="4.8"),
        [tool_result("buscar_medicamentos", cima_ibuprofeno["hit"])],
    )
    plan = plan_node(state)["plan"]
    assert [c.tool for c in plan] == ["doc_contenido"]
    # Args reales: tipo_doc (no 'tipo'), 1 = ficha técnica.
    assert plan[0].args == {"tipo_doc": 1, "seccion": "4.8", "nregistro": "51347"}


# --- alternativa ---------------------------------------------------------------

def test_alternativa_secuencia_detalle_vmpp_y_excipiente(cima_ibuprofeno):
    ents = Entities(nombre="ibuprofeno", dosis="600 mg", excipiente="lactosa")

    # 1) resolver
    plan = plan_node(_state("alternativa", ents))["plan"]
    assert [c.tool for c in plan] == ["buscar_medicamentos"]

    # 2) detalle para conocer el principio activo
    state = _state(
        "alternativa", ents, [tool_result("buscar_medicamentos", cima_ibuprofeno["hit"])]
    )
    plan = plan_node(state)["plan"]
    assert [c.tool for c in plan] == ["obtener_medicamento"]

    # 3) vmpp por practiv1 (del vtm del detalle), NO por nombre comercial
    state["tool_results"].append(
        tool_result("obtener_medicamento", cima_ibuprofeno["detalle"])
    )
    plan = plan_node(state)["plan"]
    assert [c.tool for c in plan] == ["buscar_vmpp"]
    assert plan[0].args == {"practiv1": "ibuprofeno", "dosis": "600 mg"}

    # 4) restricción de excipiente -> reglas reales (seccion 6.1, contiene=0)
    state["tool_results"].append(tool_result("buscar_vmpp", cima_ibuprofeno["vmpp"]))
    plan = plan_node(state)["plan"]
    assert [c.tool for c in plan] == ["buscar_en_ficha_tecnica"]
    assert plan[0].args == {
        "reglas": [{"seccion": "6.1", "texto": "lactosa", "contiene": 0}]
    }


# --- casos límite ----------------------------------------------------------------

def test_no_reintenta_si_el_farmaco_no_existe_en_cima():
    state = _state(
        "receta",
        Entities(nombre="medicamentoinexistente"),
        [tool_result("buscar_medicamentos", {"resultados": []})],
    )
    # No vuelve a buscar: deja que respond diga "no aparece en CIMA".
    assert plan_node(state)["plan"] == []


def test_sin_nombre_no_planifica_nada():
    assert plan_node(_state("receta", Entities()))["plan"] == []


def test_fuera_de_alcance_no_planifica_nada():
    assert plan_node(_state("desconocido", Entities(nombre="ibuprofeno")))["plan"] == []


def test_resolucion_prefiere_nombre_y_dosis():
    # Caso real: "ibuprofeno cinfa" devuelve la suspensión 20 mg/ml como primer
    # hit; si el usuario pidió 600 mg, hay que elegir los comprimidos de 600.
    hit = {
        "resultados": [
            {"nregistro": "66020", "nombre": "IBUPROFENO CINFA 20 MG/ML SUSPENSIÓN ORAL EFG"},
            {"nregistro": "77857", "nombre": "IBUPROFENO CINFA 40 MG/ML SUSPENSION ORAL EFG"},
            {"nregistro": "70039", "nombre": "IBUPROFENO CINFA 600 mg COMPRIMIDOS"},
        ],
        "metadata": {"fuente": "CIMA (AEMPS)"},
    }
    state = _state(
        "ficha_tecnica",
        Entities(nombre="ibuprofeno cinfa", dosis="600 mg", excipiente="lactosa"),
        [tool_result("buscar_medicamentos", hit)],
    )
    plan = plan_node(state)["plan"]
    assert plan[0].args == {"nregistro": "70039"}  # los 600 mg, no la suspensión


def test_resolucion_sin_dosis_cae_al_primer_match_de_nombre():
    hit = {
        "resultados": [
            {"nregistro": "66020", "nombre": "IBUPROFENO CINFA 20 MG/ML SUSPENSIÓN ORAL EFG"},
            {"nregistro": "70039", "nombre": "IBUPROFENO CINFA 600 mg COMPRIMIDOS"},
        ],
    }
    state = _state(
        "receta",
        Entities(nombre="ibuprofeno cinfa"),
        [tool_result("buscar_medicamentos", hit)],
    )
    plan = plan_node(state)["plan"]
    assert plan[0].args == {"nregistro": "66020"}


def test_resolucion_prefiere_el_nombre_buscado():
    # CIMA ordena por similitud: "omeprazol" devuelve ESOMEPRAZOL primero.
    hit = {
        "resultados": [
            {"nregistro": "82921", "nombre": "ESOMEPRAZOL CINFA 20 MG CAPSULAS"},
            {"nregistro": "65973", "nombre": "OMEPRAZOL CINFA 20 MG CAPSULAS"},
        ],
        "metadata": {"fuente": "CIMA (AEMPS)"},
    }
    state = _state(
        "receta",
        Entities(nombre="omeprazol"),
        [tool_result("buscar_medicamentos", hit)],
    )
    plan = plan_node(state)["plan"]
    assert plan[0].args == {"nregistro": "65973"}  # el OMEPRAZOL, no el ESO-
