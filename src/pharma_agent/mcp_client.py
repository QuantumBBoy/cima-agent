"""Conexión stdio a mcp-aemps vía langchain-mcp-adapters.

Este módulo NO reimplementa mcp-aemps: lo lanza como subproceso MCP
(``uvx mcp-aemps@latest stdio``) y carga sus 21 tools como tools de LangChain,
listas para que los nodos del grafo las invoquen. Ese puente oficial es lo que
nos ahorra escribir el pegamento del protocolo.
"""

from __future__ import annotations

import os
import shlex
from typing import Any

# Comando por defecto para arrancar el servidor (cliente MCP normal por stdio).
DEFAULT_COMMAND = "uvx"
DEFAULT_ARGS = ["mcp-aemps@latest", "stdio"]

# Tools de mcp-aemps relevantes para el caso de uso "consulta de medicación con
# verificación de receta y suministro". No necesitamos las 21.
RELEVANT_TOOLS = {
    "obtener_medicamento",
    "buscar_medicamentos",
    "doc_contenido",
    "doc_secciones",
    "problemas_suministro_dcpf",
    "buscar_vmpp",
    "buscar_en_ficha_tecnica",
}


class MCPUnavailableError(RuntimeError):
    """mcp-aemps no se pudo lanzar (no instalado, uvx falla, etc.).

    Se eleva con un mensaje de setup accionable, no con un stack trace crudo.
    """


def _server_config() -> dict[str, dict[str, Any]]:
    """Config del servidor, sobreescribible por variables de entorno."""
    command = os.getenv("MCP_AEMPS_COMMAND", DEFAULT_COMMAND)
    raw_args = os.getenv("MCP_AEMPS_ARGS")
    args = shlex.split(raw_args) if raw_args else list(DEFAULT_ARGS)
    return {
        "aemps": {
            "command": command,
            "args": args,
            "transport": "stdio",
        }
    }


async def load_aemps_tools(only_relevant: bool = True) -> dict[str, Any]:
    """Carga las tools de mcp-aemps y las devuelve indexadas por nombre.

    Devuelve un dict ``{nombre_tool: StructuredTool}``. Cada tool abre su propia
    sesión MCP al invocarse (comportamiento de MultiServerMCPClient sin sesión
    explícita), lo que encaja con nuestro patrón petición-respuesta.
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError as exc:  # pragma: no cover - dependencia declarada
        raise MCPUnavailableError(
            "Falta 'langchain-mcp-adapters'. Instala las dependencias del proyecto:\n"
            "    uv sync   (o)   pip install -e ."
        ) from exc

    client = MultiServerMCPClient(_server_config())
    try:
        tools = await client.get_tools()
    except Exception as exc:  # noqa: BLE001 - queremos un mensaje de setup claro
        raise MCPUnavailableError(
            "No se pudo lanzar el servidor mcp-aemps.\n"
            "Comprueba que tienes 'uv' instalado y que este comando funciona:\n"
            "    uvx mcp-aemps@latest stdio\n"
            f"Detalle: {exc}"
        ) from exc

    registry = {t.name: t for t in tools}
    if only_relevant:
        registry = {
            name: tool for name, tool in registry.items() if name in RELEVANT_TOOLS
        }
    if not registry:
        raise MCPUnavailableError(
            "mcp-aemps respondió pero no expuso ninguna de las tools esperadas "
            f"({sorted(RELEVANT_TOOLS)}). ¿Versión incompatible del servidor?"
        )
    return registry
