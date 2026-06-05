"""Interfaz de terminal mejorada para el agente (arquitectura ATUI).

ATUI — Agent Tool Use Interface: muestra en tiempo real el progreso del agente
mediante Rich: pipeline de nodos, llamadas a tools de CIMA, y un panel final
con la respuesta + URLs de fotos del medicamento (con hipervínculo si el
terminal las soporta, p. ej. iTerm2, Kitty o WezTerm).

La diferencia clave frente al CLI básico: en vez de esperar al resultado final,
el usuario ve cada nodo activarse y cada tool de mcp-aemps ejecutarse mientras
el agente trabaja — el mismo principio que AG-UI, pero en el terminal.

Uso directo:
    python -m pharma_agent.atui "¿necesita receta el omeprazol 20 mg?"
    python -m pharma_agent.atui --json "¿el paracetamol lleva lactosa?"
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

STEP_LABELS = {
    "triage":  ("🔍", "Triaje"),
    "plan":    ("🗂 ", "Plan"),
    "execute": ("⚙ ", "Execute"),
    "verify":  ("✅", "Verify"),
    "respond": ("📝", "Respond"),
}
STEP_ORDER = list(STEP_LABELS.keys())


def _try_rich():
    try:
        from rich.console import Console
        from rich.live import Live
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
        return Console, Live, Panel, Table, Text
    except ImportError:
        return None


async def run_atui(query: str, output_json: bool = False) -> None:
    rich_mods = _try_rich()
    if rich_mods is None:
        # Fallback sin Rich: comportamiento similar al CLI básico.
        await _run_plain(query, output_json)
        return

    Console, Live, Panel, Table, Text = rich_mods
    console = Console()

    from .mcp_client import load_aemps_tools
    from .llm import get_llm
    from .graph import build_graph
    from .state import initial_state

    console.print(Panel(
        f"[bold cyan]Consulta:[/] {query}",
        title="[bold]Pharma Agent · ATUI[/]",
        border_style="blue",
    ))

    step_state: dict[str, str] = {s: "pending" for s in STEP_ORDER}
    current_tool_calls: list[str] = []
    final_state: dict[str, Any] = {}

    def _build_panel(streaming_text: str = "") -> Panel:
        table = Table.grid(padding=(0, 1))
        for step in STEP_ORDER:
            icon, label = STEP_LABELS[step]
            state = step_state[step]
            if state == "done":
                style = "bold green"
                marker = "✓"
            elif state == "active":
                style = "bold yellow"
                marker = "▶"
            else:
                style = "dim"
                marker = "·"
            table.add_row(Text(marker, style=style), Text(f"{icon} {label}", style=style))

        if current_tool_calls:
            table.add_row("", Text("  tools: " + ", ".join(current_tool_calls), style="cyan"))

        if streaming_text:
            table.add_row("", Text(""))
            table.add_row("", Text(streaming_text[:300] + ("…" if len(streaming_text) > 300 else ""), style="italic"))

        return Panel(table, title="[bold blue]Pipeline[/]", border_style="blue")

    try:
        tools = await load_aemps_tools()
        llm = get_llm()
        graph = build_graph(llm, tools)
    except Exception as exc:
        console.print(f"[red]Error al inicializar: {exc}[/]")
        return

    streaming_text = ""

    with Live(_build_panel(), console=console, refresh_per_second=8) as live:
        try:
            async for event in graph.astream_events(
                initial_state(query), version="v2", config={"run_name": "pharma-atui"}
            ):
                kind = event.get("event", "")
                name = event.get("name", "")
                data = event.get("data", {})

                if kind == "on_chain_start" and name in STEP_LABELS:
                    step_state[name] = "active"
                    live.update(_build_panel(streaming_text))

                elif kind == "on_chain_end" and name in STEP_LABELS:
                    step_state[name] = "done"
                    output = data.get("output") or {}
                    if isinstance(output, dict):
                        final_state.update(output)
                    if name == "execute":
                        current_tool_calls.clear()
                    live.update(_build_panel(streaming_text))

                elif kind == "on_tool_start":
                    current_tool_calls.append(name)
                    live.update(_build_panel(streaming_text))

                elif kind == "on_tool_end":
                    if name in current_tool_calls:
                        current_tool_calls.remove(name)
                    live.update(_build_panel(streaming_text))

                elif kind == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    token = getattr(chunk, "content", "") if chunk else ""
                    if token:
                        streaming_text += token
                        live.update(_build_panel(streaming_text))

        except Exception as exc:
            console.print(f"[red]Error durante la ejecución: {exc}[/]")
            return

    # --- Resultado final ---
    answer = final_state.get("answer", "")
    photos = final_state.get("photos", [])

    console.print()
    console.print(Panel(answer, title="[bold green]Respuesta[/]", border_style="green"))

    if photos:
        console.print()
        photo_table = Table(title="📸 Fotos del medicamento (CIMA)", show_header=True, header_style="bold blue")
        photo_table.add_column("Tipo", style="cyan", width=10)
        photo_table.add_column("URL", style="blue")
        photo_table.add_column("Fecha", style="dim", width=12)
        tipo_labels = {1: "Envase", 2: "Ficha", 3: "Prospecto"}
        for photo in photos:
            tipo = tipo_labels.get(getattr(photo, "tipo", 1), f"Tipo {getattr(photo, 'tipo', '?')}")
            url = getattr(photo, "url", str(photo))
            fecha = getattr(photo, "fecha", None) or "—"
            # Rich renderiza URLs como hipervínculos en terminales compatibles.
            photo_table.add_row(tipo, f"[link={url}]{url}[/link]", fecha)
        console.print(photo_table)

    if output_json:
        structured = final_state.get("structured_answer")
        if structured and hasattr(structured, "model_dump"):
            data_out = structured.model_dump()
        else:
            data_out = {"answer": answer}
        print(json.dumps(data_out, ensure_ascii=False, indent=2))


async def _run_plain(query: str, output_json: bool) -> None:
    """Fallback sin Rich: imprime progreso básico por stderr."""
    from .mcp_client import load_aemps_tools
    from .llm import get_llm
    from .graph import build_graph
    from .state import initial_state

    print(f"[pharma-agent] consulta: {query}", file=sys.stderr)

    tools = await load_aemps_tools()
    llm = get_llm()
    graph = build_graph(llm, tools)

    result = await graph.ainvoke(initial_state(query))
    answer = result.get("answer", "")
    photos = result.get("photos", [])

    if output_json:
        structured = result.get("structured_answer")
        data_out = structured.model_dump() if (structured and hasattr(structured, "model_dump")) else {"answer": answer}
        print(json.dumps(data_out, ensure_ascii=False, indent=2))
    else:
        print(answer)
        for photo in photos:
            url = getattr(photo, "url", str(photo))
            tipo = getattr(photo, "tipo", 1)
            label = {1: "Envase", 2: "Ficha"}.get(tipo, f"Tipo {tipo}")
            print(f"  📸 {label}: {url}", file=sys.stderr)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Pharma Agent ATUI — terminal con Rich")
    parser.add_argument("query", help="Consulta sobre medicamentos")
    parser.add_argument("--json", dest="json_out", action="store_true", help="Salida JSON estructurada")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(run_atui(args.query, output_json=args.json_out))


if __name__ == "__main__":
    main()
