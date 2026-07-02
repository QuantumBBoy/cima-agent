# pharma-agent

[![CI](https://github.com/QuantumBBoy/cima-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/QuantumBBoy/cima-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Agente [LangGraph](https://langchain-ai.github.io/langgraph/) que responde consultas sobre medicamentos **citando siempre la fuente oficial AEMPS/CIMA**. No reimplementa nada: es una **capa de consumo** sobre el servidor MCP [`mcp-aemps`](https://github.com/romanpert/mcp-aemps).

Caso de uso, acotado y terminable: **"consulta de medicación con verificación de receta y suministro"**. El usuario pregunta en lenguaje natural; el agente responde con datos oficiales, alternativas si las hay, y el aviso legal por delante.

![Demo del agente: flujo triage → plan → execute → verify → respond](docs/demo.gif)

> Ejecución **real**: `mcp-aemps` sobre CIMA + un LLM de **Ollama Cloud** (`gpt-oss:20b`). El agente resuelve el medicamento, lee el campo `receta` y responde citando la fuente. Regenerable con `vhs docs/demo.tape`. Sin claves, la demo offline equivalente: `python examples/offline_demo.py`.

## Qué hace y qué NO

**Hace:** consulta la ficha técnica (secciones y excipientes), si necesita receta, problemas de suministro y equivalentes clínicos (mismo VMP).

**NO hace:** consejo médico, decisión clínica, ni nada que toque datos de paciente. No es solo prudencia — es el posicionamiento que el propio `mcp-aemps` exige (read-only, sin clinical decision support, MDR no aplica). Respetarlo es parte de la calidad del trabajo.

## El grafo

```
START → triage → plan ─┬─(hay pasos)→ execute ─┬─(¿suficiente?)→ plan
                       │                        └─(tope o fin)──→ verify → respond → END
                       └─(nada que hacer)──────────────────────→ verify
```

| Nodo | Qué hace |
|------|----------|
| **triage** | Clasifica la intención (receta / suministro / ficha_tecnica / alternativa / desconocido) y extrae entidades (fármaco, dosis, forma…) con salida estructurada Pydantic. Dirige qué tools tienen sentido y evita llamadas a ciegas. |
| **plan** | Decide la secuencia de tools según la intención y lo ya recuperado. Determinista y testeable. Demuestra que el agente *razona* sobre herramientas, no solo las invoca. |
| **execute** | Llama a `mcp-aemps` por el protocolo MCP y recoge resultados con su procedencia (fuente + timestamp de consulta). |
| **¿suficiente?** | Arista condicional: si faltan datos vuelve a *plan*; con tope de **4 iteraciones** para evitar bucles infinitos. |
| **verify** | Comprueba que cada afirmación está respaldada por un dato recuperado de AEMPS. Lo no respaldado se marca "no disponible en CIMA" en vez de alucinarse. Es el diferenciador de calidad. |
| **respond** | Redacta en lenguaje natural, antepone el disclaimer de no-consejo-médico y lista las fuentes. Salida también estructurada (`PharmaAnswer`) para consumo programático. |

El estado (`GraphState`, en [state.py](src/pharma_agent/state.py)) lleva `query`, `intent`, `entities`, `tool_results` (dato + fuente + timestamp), `iterations`, `verified_claims`, `answer` y `sources`. Cada nodo lo extiende; `tool_results` se acumula vía reducer.

## Built on `mcp-aemps`

Este agente es una capa de consumo sobre el servidor [`mcp-aemps`](https://github.com/romanpert/mcp-aemps) de [@romanpert](https://github.com/romanpert), que expone la [CIMA REST API](https://www.aemps.gob.es/) de la AEMPS como 21 tools MCP. Nos conectamos por **stdio** lanzando `uvx mcp-aemps@latest stdio`, como un cliente MCP normal, mediante [`langchain-mcp-adapters`](https://github.com/langchain-ai/langchain-mcp-adapters) (el puente oficial que convierte tools MCP en tools de LangChain — así no escribimos el pegamento del protocolo).

De sus 21 tools, este caso de uso usa 6:

| Tool | Para qué (args verificados en vivo) |
|------|----------|
| `buscar_medicamentos` | Resolver el fármaco por `nombre` |
| `obtener_medicamento` | Detalle por `nregistro`/`cn`: campos `receta`, `excipientes`, `psum`, `vtm`/`pactivos` |
| `doc_contenido` | Secciones de la FT (`tipo_doc=1`, `seccion="4.8"`, `nregistro`) |
| `buscar_en_ficha_tecnica` | Reglas `{seccion, texto, contiene}` (p. ej. sin "lactosa" en §6.1) |
| `problemas_suministro` | Problemas de suministro por `nregistro`/`cn` (listas) |
| `buscar_vmpp` | Equivalentes clínicos (mismo VMP) por `practiv1` + `dosis` |

## Instalación

```bash
uv sync --extra dev        # o: pip install -e ".[dev]"
cp .env.example .env       # añade tu API key y el modelo
```

Requisitos: Python ≥ 3.11 y [`uv`](https://docs.astral.sh/uv/) (para lanzar `mcp-aemps` vía `uvx`).

## Uso

```bash
# CLI
pharma-agent "¿necesito receta para el ibuprofeno 600 mg?"
pharma-agent --json "¿el paracetamol lleva lactosa?"

# Demo offline (sin red ni API key — todo mockeado)
python examples/offline_demo.py

# Demo en vivo con streaming del flujo (mcp-aemps real + LLM real)
python examples/live_demo.py "¿necesita receta el omeprazol 20 mg?"

# Varias consultas en vivo seguidas
python examples/live_queries.py
```

Programáticamente:

```python
import asyncio
from pharma_agent import run_query

final = asyncio.run(run_query("¿hay problemas de suministro con el Adiro 100 mg?"))
print(final["answer"])              # texto con disclaimer + fuentes
print(final["structured_answer"])   # PharmaAnswer para consumo programático
```

## Modelo LLM (Anthropic u Ollama Cloud)

El modelo se elige con `PHARMA_AGENT_MODEL` (formato `provider:modelo`):

- `anthropic:claude-sonnet-4-5` (por defecto) — usa `init_chat_model` de LangChain.
- `ollama:gpt-oss:20b` — Ollama Cloud (endpoint OpenAI-compatible). Requiere
  `OLLAMA_API_KEY` y el extra `ollama` (`uv sync --extra ollama`).

## Fricción real integrando (notas de integración)

Lo que costó integrar de verdad — documentado para quien construya sobre `mcp-aemps` con LangChain:

1. **El resultado de cada tool llega como bloques de contenido MCP.**
   `langchain-mcp-adapters` devuelve `[{"type":"text","text":"<JSON de CIMA>"}, …]`,
   y junto al bloque de texto vienen N bloques de recurso (`{type,id,url,mime_type}`)
   sin `text`. Hay que quedarse con el bloque de texto y parsear el JSON de CIMA
   que lleva dentro (ver [`_normalize_content`](src/pharma_agent/nodes/execute.py)).
   Si no, el agente no encuentra `resultados` y entra en bucle reportando "no encontrado".
2. **La provenance viaja anidada en `metadata`, no en claves top-level.** Cada
   respuesta incluye `{"metadata": {"fuente": "CIMA (AEMPS)", "fecha_consulta":
   …, "version_api": "1.23"}}` — al principio la buscamos plana y la dimos por
   ausente. De ahí salen las fuentes citadas (ver
   [`extract_source`](src/pharma_agent/nodes/_helpers.py)).
3. **Structured output con modelos open (Ollama Cloud).** Esos modelos **no**
   respetan el structured output constrained (ni `format` json-schema, ni
   `response_format`, ni tool-calling de forma fiable). El agente lo resuelve con
   una envoltura que fuerza JSON por prompt + parseo tolerante + reintento de
   validación (ver [`JSONCoercedChat`](src/pharma_agent/llm.py)). Con un modelo
   con structured output nativo (p. ej. Claude) este paso sobra.
4. **Los schemas reales difieren del README del servidor** — verifícalos por
   introspección (`tool.args`) antes de planificar llamadas:
   `problemas_suministro_dcpf` exige un código clínico `cod_dcpf` (usamos
   `problemas_suministro`, que acepta `nregistro`/`cn` como listas);
   `buscar_vmpp` filtra por `practiv1` (con `nombre` comercial devuelve 0);
   `buscar_en_ficha_tecnica` exige reglas `{seccion, texto, contiene}` con
   sección obligatoria; `doc_contenido` usa `tipo_doc`, no `tipo`.
5. **CIMA ordena por similitud, no por relevancia clínica.** "omeprazol"
   devuelve ESOMEPRAZOL primero, e "ibuprofeno cinfa" la suspensión 20 mg/ml
   antes que los comprimidos de 600 mg. El agente re-ordena prefiriendo el
   prefijo del nombre buscado + la dosis pedida (ver
   [`resolve_medicine`](src/pharma_agent/nodes/_helpers.py)).

## Manejo de errores

- **`mcp-aemps` no disponible** (no instalado / `uvx` falla) → mensaje de setup claro, no un stack trace.
- **Fármaco no encontrado** → "no aparece en CIMA con ese nombre…", sin inventar ni reintentar en bucle.
- **Tope de iteraciones** → responde con lo que tiene.
- **Dato recuperado pero sin la sección pedida** → "no disponible en CIMA" en vez de rellenar.

## Tests

```bash
pytest              # unit + integración con mcp-aemps mockeado
pytest -m live      # smoke opcional contra mcp-aemps real (no en CI por defecto)
```

- **Unit por nodo**: el triaje clasifica bien; el planificador elige las tools correctas por intent.
- **Integración** (`mcp-aemps` mockeado): el flujo "¿necesito receta para X?" devuelve el campo `receta` con su fuente.
- **El test que justifica la verificación**: dado un resultado que NO contiene cierto dato, el agente NO lo afirma.

## Licencia

MIT — ver [LICENSE](LICENSE).
