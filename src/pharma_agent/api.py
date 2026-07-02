"""API HTTP para consumo programático (la semilla de la feature de PharmaFast).

Expone el agente como servicio FastAPI:

- ``POST /consulta`` — consulta en lenguaje natural → ``PharmaAnswer`` (JSON
  estructurado con disclaimer, claims verificados y fuentes).
- ``GET /health`` — liveness + si el agente está inicializado.

El grafo y la conexión MCP se construyen UNA vez en el arranque (lifespan),
no por petición: lanzar mcp-aemps por stdio cuesta segundos.

Arranque:  pharma-agent-api
       (o: uvicorn "pharma_agent.api:create_app" --factory)
Requiere el extra 'api':  uv sync --extra api
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Optional

from pydantic import BaseModel, Field

from .graph import build_graph
from .mcp_client import MCPUnavailableError
from .state import PharmaAnswer, initial_state


class ConsultaRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500, description="Consulta en lenguaje natural")


class HealthResponse(BaseModel):
    status: str
    agent_ready: bool


def create_app(llm: Any = None, tools: Optional[dict[str, Any]] = None):
    """Construye la app FastAPI. ``llm``/``tools`` se inyectan en tests."""
    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as exc:  # pragma: no cover - extra declarado
        raise RuntimeError(
            "Falta el extra 'api'. Instálalo con:  uv sync --extra api"
        ) from exc

    runtime: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(_app):
        from dotenv import load_dotenv

        load_dotenv()
        _llm = llm
        if _llm is None:
            from .llm import get_llm

            _llm = get_llm()
        _tools = tools
        if _tools is None:
            from .mcp_client import load_aemps_tools

            _tools = await load_aemps_tools()
        runtime["agent"] = build_graph(_llm, _tools)
        yield
        runtime.clear()

    app = FastAPI(
        title="pharma-agent",
        description=(
            "Agente LangGraph sobre mcp-aemps (AEMPS/CIMA). Información oficial "
            "de medicamentos con fuentes; NO consejo médico."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", agent_ready="agent" in runtime)

    @app.post("/consulta", response_model=PharmaAnswer)
    async def consulta(req: ConsultaRequest) -> PharmaAnswer:
        agent = runtime.get("agent")
        if agent is None:  # pragma: no cover - lifespan garantiza esto
            raise HTTPException(status_code=503, detail="Agente no inicializado")
        try:
            final = await agent.ainvoke(initial_state(req.query))
        except MCPUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - error del LLM/grafo en runtime
            raise HTTPException(
                status_code=502, detail=f"Fallo ejecutando el agente: {exc}"
            ) from exc
        answer = final.get("structured_answer")
        if answer is None:
            raise HTTPException(status_code=500, detail="El agente no produjo respuesta")
        return answer

    return app


def main() -> None:
    """Entry point del script ``pharma-agent-api``.

    Para opciones de uvicorn (reload, workers, puerto), usa el modo factory:
        uvicorn "pharma_agent.api:create_app" --factory --port 8000
    """
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
