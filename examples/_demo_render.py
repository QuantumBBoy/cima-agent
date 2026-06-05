"""Renderizador compartido para las demos: imprime el flujo del grafo nodo a nodo.

Usado por offline_demo.py (mockeado) y live_demo.py (mcp-aemps + LLM reales).
"""

from __future__ import annotations

import time
from typing import Any

DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
RESET = "\033[0m"


def render(node: str, update: dict, delay: float = 0.0) -> None:
    if delay:
        time.sleep(delay)
    if node == "triage":
        ents = update["entities"]
        print(f"{CYAN}● triage{RESET}   intención={BOLD}{update['intent']}{RESET}  "
              f"{DIM}fármaco={ents.nombre!r} dosis={ents.dosis!r}{RESET}")
    elif node == "plan":
        if update.get("plan"):
            for call in update["plan"]:
                print(f"{MAGENTA}● plan{RESET}     → {BOLD}{call.tool}{RESET}({call.args})  "
                      f"{DIM}{call.purpose}{RESET}")
        else:
            print(f"{MAGENTA}● plan{RESET}     → suficiente, a verificar")
    elif node == "execute":
        for res in update["tool_results"]:
            status = f"{GREEN}OK{RESET}" if res.ok else f"{RED}ERROR{RESET}"
            print(f"{YELLOW}● execute{RESET}  {res.tool} [{status}]  "
                  f"{DIM}fuente={res.source.endpoint or 'mcp-aemps:' + res.tool}{RESET}")
    elif node == "verify":
        for claim in update.get("verified_claims", []):
            mark = f"{GREEN}✔{RESET}" if claim.supported else f"{RED}✖{RESET}"
            print(f"{CYAN}● verify{RESET}   [{mark}] {claim.statement} → {claim.value}")
    elif node == "respond":
        print(f"{GREEN}● respond{RESET}  respuesta redactada\n")


async def stream_agent(agent: Any, query: str, initial: dict, delay: float = 0.0) -> dict:
    """Ejecuta el agente en streaming, renderizando cada nodo. Devuelve el estado final."""
    print(f"\n{BOLD}pharma-agent{RESET} {DIM}· capa de consumo sobre mcp-aemps (AEMPS/CIMA){RESET}")
    print(f"{BOLD}❯{RESET} {query}\n")
    final: dict = {}
    async for chunk in agent.astream(initial, stream_mode="updates"):
        for node, update in chunk.items():
            render(node, update, delay)
            final.update(update)
    if delay:
        time.sleep(delay)
    print("─" * 70)
    print(final.get("answer", "(sin respuesta)"))
    print("─" * 70)
    return final
