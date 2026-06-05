"""Servidor AG-UI: expone el agente vía FastAPI + Server-Sent Events.

Arquitectura AGUI — el frontend se conecta al endpoint SSE y recibe eventos
en el formato del protocolo AG-UI (https://docs.ag-ui.com/), que define un
estándar abierto para conectar agentes a interfaces gráficas. Los eventos
permiten mostrar en tiempo real el progreso del agente: triaje, llamadas a
tools de CIMA, y finalmente las fotos + respuesta del medicamento.

Eventos implementados (subconjunto AG-UI):
  RUN_STARTED         → la ejecución ha comenzado
  TEXT_MESSAGE_*      → el agente emite texto (streaming)
  TOOL_CALL_START/END → el agente llama a una tool de mcp-aemps
  STATE_SNAPSHOT      → snapshot del estado final (fotos, claims, fuentes)
  RUN_FINISHED        → la ejecución ha terminado
  RUN_ERROR           → error en la ejecución

Uso:
    uv run uvicorn pharma_agent.agui_server:app --reload
    # Luego abre examples/agui_demo.html en el navegador.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Pharma Agent — AGUI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    query: str
    thread_id: str = ""


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _stream_agent(query: str, thread_id: str, run_id: str) -> AsyncIterator[str]:
    """Ejecuta el agente y transforma los eventos LangGraph al protocolo AG-UI."""
    yield _sse({"type": "RUN_STARTED", "threadId": thread_id, "runId": run_id})

    try:
        from .mcp_client import MCPUnavailableError, load_aemps_tools
        from .llm import get_llm
        from .graph import build_graph
        from .state import initial_state
    except Exception as exc:
        yield _sse({"type": "RUN_ERROR", "message": str(exc)})
        return

    try:
        tools = await load_aemps_tools()
        llm = get_llm()
        graph = build_graph(llm, tools)
    except Exception as exc:
        yield _sse({"type": "RUN_ERROR", "message": f"Setup: {exc}"})
        return

    msg_id = str(uuid.uuid4())
    final_state: dict[str, Any] = {}

    try:
        async for event in graph.astream_events(
            initial_state(query), version="v2", config={"run_name": "pharma-agui"}
        ):
            kind = event.get("event", "")
            name = event.get("name", "")
            data = event.get("data", {})

            # Inicio de un nodo del grafo → informar al frontend.
            if kind == "on_chain_start" and name in (
                "triage", "plan", "execute", "verify", "respond"
            ):
                yield _sse({
                    "type": "TOOL_CALL_START",
                    "toolCallId": f"{name}-{run_id}",
                    "toolCallName": name,
                    "parentMessageId": msg_id,
                })

            # Fin de nodo → cerrar la tool call y capturar estado.
            elif kind == "on_chain_end" and name in (
                "triage", "plan", "execute", "verify", "respond"
            ):
                output = data.get("output") or {}
                yield _sse({
                    "type": "TOOL_CALL_END",
                    "toolCallId": f"{name}-{run_id}",
                    "result": json.dumps(
                        {k: v for k, v in (output.items() if isinstance(output, dict) else {})
                         if k in ("intent", "medicine_found", "iterations")},
                        ensure_ascii=False,
                    ),
                })
                if isinstance(output, dict):
                    final_state.update(output)

            # Streaming de tokens del LLM → TEXT_MESSAGE_CONTENT.
            elif kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                token = getattr(chunk, "content", "") if chunk else ""
                if token:
                    if not getattr(_stream_agent, "_msg_started", False):
                        yield _sse({
                            "type": "TEXT_MESSAGE_START",
                            "messageId": msg_id,
                            "role": "assistant",
                        })
                        _stream_agent._msg_started = True  # type: ignore[attr-defined]
                    yield _sse({
                        "type": "TEXT_MESSAGE_CONTENT",
                        "messageId": msg_id,
                        "delta": token,
                    })

    except Exception as exc:
        yield _sse({"type": "RUN_ERROR", "message": str(exc)})
        return

    # Cierre del mensaje de texto.
    yield _sse({"type": "TEXT_MESSAGE_END", "messageId": msg_id})

    # STATE_SNAPSHOT con fotos, claims y fuentes.
    photos_data = []
    for p in final_state.get("photos", []):
        if hasattr(p, "model_dump"):
            photos_data.append(p.model_dump())
        elif isinstance(p, dict):
            photos_data.append(p)

    structured = final_state.get("structured_answer")
    snapshot: dict[str, Any] = {
        "answer": final_state.get("answer", ""),
        "medicine_found": final_state.get("medicine_found", False),
        "photos": photos_data,
        "sources": [
            (s.model_dump() if hasattr(s, "model_dump") else s)
            for s in final_state.get("sources", [])
        ],
    }
    if structured and hasattr(structured, "model_dump"):
        snapshot["structured"] = structured.model_dump()

    yield _sse({"type": "STATE_SNAPSHOT", "snapshot": snapshot})
    yield _sse({"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id})


@app.post("/runs")
async def run_agent(req: RunRequest) -> StreamingResponse:
    """Endpoint AG-UI: acepta una consulta y devuelve un stream SSE de eventos."""
    thread_id = req.thread_id or str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    return StreamingResponse(
        _stream_agent(req.query, thread_id, run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/", response_class=HTMLResponse)
async def demo_ui() -> str:
    """Sirve la interfaz AGUI embebida para demo rápida."""
    import importlib.resources as ir
    try:
        path = ir.files("pharma_agent") / "agui_demo.html"
        return path.read_text(encoding="utf-8")
    except Exception:
        return "<h1>Pharma Agent AGUI</h1><p>Coloca agui_demo.html en src/pharma_agent/</p>"
