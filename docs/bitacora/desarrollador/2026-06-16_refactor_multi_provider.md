# Refactor multi-proveedor en brain.py

**Fecha:** 2026-06-16
**Fase:** 2 (cerebro)
**Archivos modificados:** `src/brain.py`, `requirements.txt`, `.env.example`, `scripts/fase2_checkpoint.py`

---

## Qué se hizo

Se refactorizó `src/brain.py` para soportar múltiples proveedores LLM seleccionables
mediante la variable de entorno `LLM_PROVIDER`. Antes, el módulo estaba acoplado
exclusivamente a Anthropic/Claude.

---

## Cambios por archivo

### `src/brain.py`

- **Eliminado:** import top-level de `anthropic`. El import ahora es lazy dentro de
  `_llamar_anthropic()`.
- **Eliminado:** el bloque de llamada al LLM de `analizar()` — se extrajo a funciones
  separadas.
- **Agregado:** `_TOOL_DECISION_OPENAI` — schema del tool en formato OpenAI/Groq,
  construido reutilizando `_TOOL_DECISION["input_schema"]`.
- **Agregado:** `_llamar_anthropic(user_message)` — implementación Anthropic (lógica
  migrada desde `analizar()`).
- **Agregado:** `_llamar_gemini(user_message)` — implementación Gemini via
  `google-generativeai`. Construye el schema `protos.Tool` dentro de la función.
  Convierte los valores `MapComposite` y `RepeatedScalar` de protobuf a tipos Python
  nativos antes de devolverlos.
- **Agregado:** `_llamar_groq(user_message)` — implementación Groq via SDK `groq`
  (API compatible con OpenAI). Parsea `tool_calls[0].function.arguments` como JSON.
- **Agregado:** `_llamar_proveedor(user_message)` — despachador que lee `LLM_PROVIDER`
  del entorno y llama a la función específica.
- **Modificado:** `analizar()` — reemplaza el bloque de llamada directa a Anthropic
  por `raw_input = _llamar_proveedor(user_message)`.

**Sin cambios:** `_validar_contexto`, `_validar_timeframe`, `_validar_y_corregir_salida`,
`_fallback_con_razon`, `_clamp`, `_FALLBACK`, `_SYSTEM_PROMPT`, `_TOOL_DECISION`,
la firma de `analizar()`.

### `requirements.txt`

Agregadas dos dependencias:
- `google-generativeai>=0.8.0`
- `groq>=0.9.0`

### `.env.example`

Agregadas cuatro variables nuevas:
- `LLM_PROVIDER` — selector de proveedor (default `anthropic`)
- `LLM_MODEL` — override del modelo; vacío usa el default por proveedor
- `GEMINI_API_KEY` — requerido solo si `LLM_PROVIDER=gemini`
- `GROQ_API_KEY` — requerido solo si `LLM_PROVIDER=groq`

### `scripts/fase2_checkpoint.py`

Agrega al inicio del output:
```
Proveedor: anthropic | Modelo: (default)
```

---

## Defaults de modelo por proveedor

| Proveedor  | Default                    |
|------------|----------------------------|
| anthropic  | `claude-sonnet-4-6`        |
| gemini     | `gemini-1.5-flash`         |
| groq       | `llama-3.3-70b-versatile`  |

Todos pueden sobreriderse con `LLM_MODEL=<modelo>` en el entorno.

---

## Decisiones de diseño

**Imports lazy:** los SDKs de `google-generativeai` y `groq` se importan dentro del
cuerpo de la función correspondiente, no en el top-level del módulo. Esto garantiza que
el módulo cargue sin errores en un entorno donde solo está instalado `anthropic`.

**Temperatura uniforme:** los tres proveedores usan `temperature=0.1` (o equivalente),
consistente con la restricción de temperatura baja del proyecto.

**Conversión Gemini:** la respuesta de Gemini retorna tipos protobuf (`MapComposite`,
`RepeatedScalar`). Se convierte explícitamente a `dict` y `list` antes de pasar a
`_validar_y_corregir_salida`, que espera tipos Python nativos.

**Schema reutilizado (Groq):** `_TOOL_DECISION_OPENAI` referencia directamente
`_TOOL_DECISION["input_schema"]`, sin duplicar el JSON Schema.

---

## Guardrails preservados

- `brain.py` no importa `ccxt`, `pandas`, ni `pandas_ta` (verificado).
- Ante cualquier error de SDK (import, API, parseo) → `None` → fallback seguro.
- El contrato público de `analizar()` no cambió.
