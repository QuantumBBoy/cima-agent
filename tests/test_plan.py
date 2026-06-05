"""Unit: el planificador elige las tools correctas para cada intent y soporta
el bucle (no repite pasos, no busca en bucle un fármaco inexistente)."""

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


def test_alternativa_busca_vmpp_y_luego_excipiente(cima_ibuprofeno):
    ents = Entities(nombre="ibuprofeno", excipiente="lactosa")
    # Primer paso: equivalentes clínicos.
    state = _state("alternativa", ents)
    plan = plan_node(state)["plan"]
    assert [c.tool for c in plan] == ["buscar_vmpp"]

    # Tras buscar_vmpp: filtrar por el excipiente en la FT.
    state = _state(
        "alternativa",
        ents,
        [tool_result("buscar_vmpp", {"resultados": [{"vmp": "ibuprofeno 600 mg oral"}]})],
    )
    plan = plan_node(state)["plan"]
    assert [c.tool for c in plan] == ["buscar_en_ficha_tecnica"]
    assert plan[0].args == {"texto": "lactosa"}


def test_ficha_tecnica_con_excipiente_usa_busqueda_en_ft(cima_ibuprofeno):
    state = _state(
        "ficha_tecnica",
        Entities(nombre="ibuprofeno", excipiente="lactosa"),
        [tool_result("buscar_medicamentos", cima_ibuprofeno["hit"])],
    )
    plan = plan_node(state)["plan"]
    assert [c.tool for c in plan] == ["buscar_en_ficha_tecnica"]
    assert plan[0].args["texto"] == "lactosa"
    assert plan[0].args["nregistro"] == "51347"


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
