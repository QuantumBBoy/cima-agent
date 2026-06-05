# Guion VHS para regenerar el GIF de la demo EN VIVO.
#   vhs docs/demo.tape        (desde la raíz del repo)
# Requiere:
#   - vhs (brew install vhs)
#   - 'uvx' (lanza mcp-aemps real)
#   - .env con PHARMA_AGENT_MODEL + la API key del proveedor
#     (en la grabación: ollama:gpt-oss:20b vía Ollama Cloud, contra CIMA real)
# Sin claves, usa la demo offline equivalente:  python examples/offline_demo.py

Output docs/demo.gif

Set FontSize 17
Set Width 1120
Set Height 760
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

# Preparación (oculta): activar venv y exponer el paquete.
Hide
Type "source .venv/bin/activate" Enter
Type "export PYTHONPATH=src" Enter
Type "clear" Enter
Show

# La consulta por defecto del script es "¿necesita receta el omeprazol 20 mg?";
# la pasamos así para evitar problemas de quoting con '¿'/'?' en el tape.
Sleep 700ms
Type "python examples/live_demo.py 2>/dev/null"
Sleep 500ms
Enter

# Deja correr el flujo real: triage -> CIMA -> verify -> respond (latencia real).
Sleep 24s
Sleep 1500ms
