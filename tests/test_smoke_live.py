"""Smoke en vivo contra mcp-aemps REAL. Marcado 'live': no corre en CI por defecto.

Ejecútalo con:  pytest -m live   (requiere 'uvx mcp-aemps@latest stdio' y una API key
del proveedor LLM configurada en el entorno).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_smoke_receta_ibuprofeno_en_vivo():
    from dotenv import load_dotenv

    from pharma_agent import run_query

    load_dotenv()
    final = await run_query("¿necesita receta el ibuprofeno 600 mg?")

    assert final.get("answer")
    assert final["answer"].startswith("⚠️")  # disclaimer por delante
    # Debe haber consultado CIMA y citar alguna fuente.
    assert final.get("sources")
