"""Estado del grafo LangGraph y modelos Pydantic compartidos entre nodos.

El estado se extiende de forma incremental: cada nodo devuelve un dict parcial
que LangGraph fusiona. Las listas que se acumulan a lo largo del bucle
(``tool_results``) usan el reducer ``operator.add``; el resto de campos se
reemplazan.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field

# Tope de iteraciones del bucle plan -> execute -> plan. Evita bucles infinitos
# cuando una consulta es demasiado ambigua. Un revisor senior busca este control.
MAX_ITERATIONS = 4

# Intenciones que sabe atender este agente. "desconocido" se reserva para
# consultas fuera de alcance (consejo médico, datos de paciente, etc.).
Intent = Literal["receta", "suministro", "ficha_tecnica", "alternativa", "desconocido"]


class Entities(BaseModel):
    """Entidades extraídas de la consulta por el nodo de triaje."""

    nombre: Optional[str] = Field(None, description="Nombre comercial o principio activo")
    dosis: Optional[str] = Field(None, description="Dosis, p. ej. '500 mg'")
    forma: Optional[str] = Field(None, description="Forma farmacéutica, p. ej. 'comprimidos'")
    seccion: Optional[str] = Field(
        None, description="Sección de la FT pedida, p. ej. '4.8' o 'reacciones adversas'"
    )
    excipiente: Optional[str] = Field(
        None, description="Excipiente de interés, p. ej. 'lactosa'"
    )
    termino_busqueda: Optional[str] = Field(
        None, description="Término libre a buscar dentro de la ficha técnica"
    )
    # Se rellenan durante el bucle al resolver el medicamento contra CIMA.
    nregistro: Optional[str] = Field(None, description="Nº de registro resuelto en CIMA")
    cn: Optional[str] = Field(None, description="Código Nacional resuelto en CIMA")


class PlannedCall(BaseModel):
    """Una llamada a herramienta que el planificador decide ejecutar."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    purpose: str = ""


class Source(BaseModel):
    """Procedencia de un dato: endpoint oficial CIMA + fecha de consulta."""

    endpoint: Optional[str] = None
    consulted_at: Optional[str] = None


class ToolResult(BaseModel):
    """Resultado de una llamada a una tool de mcp-aemps, con su procedencia."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    content: str = ""  # respuesta serializada del servidor
    source: Source = Field(default_factory=Source)
    retrieved_at: Optional[str] = None
    error: Optional[str] = None


class VerifiedClaim(BaseModel):
    """Una afirmación candidata para la respuesta, con su veredicto de respaldo."""

    statement: str = Field(description="La afirmación, redactada de forma neutra")
    supported: bool = Field(description="¿Está respaldada por un dato recuperado de AEMPS?")
    value: Optional[str] = Field(
        None, description="El valor/dato concreto, o 'no disponible en CIMA' si falta"
    )
    evidence: Optional[str] = Field(
        None, description="Cita textual o referencia al resultado que la respalda"
    )


class MedicinePhoto(BaseModel):
    """Foto de un medicamento obtenida de CIMA (envase o ficha)."""

    tipo: int = Field(1, description="Tipo CIMA: 1=envase, 2=ficha")
    url: str = Field(description="URL pública de la imagen en CIMA/AEMPS")
    fecha: Optional[str] = None


class PharmaAnswer(BaseModel):
    """Salida estructurada para que PharmaFast la consuma programáticamente."""

    disclaimer: str
    medicine_found: bool
    answer: str
    claims: list[VerifiedClaim] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    photos: list[MedicinePhoto] = Field(default_factory=list)


class GraphState(TypedDict, total=False):
    """Estado del StateGraph. ``total=False`` -> todos los campos son opcionales
    salvo ``query``, que se aporta al invocar."""

    query: str
    intent: Intent
    entities: Entities
    plan: list[PlannedCall]
    tool_results: Annotated[list[ToolResult], operator.add]
    iterations: int
    verified_claims: list[VerifiedClaim]
    medicine_found: bool
    answer: str
    sources: list[Source]
    photos: list[MedicinePhoto]
    structured_answer: PharmaAnswer


def initial_state(query: str) -> GraphState:
    """Estado de arranque para una consulta."""
    return {
        "query": query,
        "tool_results": [],
        "iterations": 0,
    }
