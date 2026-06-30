---
agente: analista
fecha: 2026-06-16
tarea: Revisión de documentación previa a implementación de brain.py — Fase 2
estado: completado
archivos_modificados:
  - docs/contrato_cerebro.md
  - docs/system_prompt.md
---

## Resumen

Revisión completa de los 5 documentos relevantes para la Fase 2 (`system_prompt.md`,
`contrato_cerebro.md`, `CLAUDE.md`, `src/types.py`, `.env.example`) más el código de
Fase 1 (`context_builder.py`) para entender el formato real de salida. Se encontraron
**4 problemas** — 3 resueltos en esta sesión, 1 pendiente de decisión del usuario.

---

## Problemas encontrados y correcciones aplicadas

### P1 — Formato de serialización del ContextoMercado no especificado (CRÍTICO — resuelto)

- **Doc:** `docs/system_prompt.md` (ausencia completa de especificación)
- **Problema:** el documento especifica la tool definition y los parámetros de la llamada
  al LLM, pero no dice **cómo formatear el `ContextoMercado` como mensaje de usuario**.
  `brain.py` necesita convertir el dict de Python en texto legible para Claude. Sin esta
  especificación, el desarrollador tiene que inventar el formato, lo cual es un hueco de
  spec bloqueante.
  
  Preguntas sin respuesta que afectan la implementación directamente:
  - ¿JSON serializado plano? ¿YAML? ¿Texto con secciones por timeframe?
  - ¿Se incluyen todos los campos o se filtra alguno?
  - ¿El mensaje de usuario tiene un prefijo/encuadre ("Analiza el siguiente contexto:")?
  
- **Corrección:** se agregó una sección "Formato del mensaje de usuario" al final del
  bloque "Formato de la llamada al LLM" en `system_prompt.md`. Se especifica: JSON
  serializado con `json.dumps(..., indent=2, ensure_ascii=False)`, precedido por el
  prefijo "Evalúa la siguiente señal de trading:" y sin omitir campos. Esta decisión
  es coherente con el principio de "el LLM solo opera sobre datos provistos" y evita
  ambigüedad sobre qué ve el modelo.

---

### P2 — Comportamiento ante `riesgo_disponible_pct = 0.0` incompleto (CRÍTICO — resuelto)

- **Doc:** `docs/contrato_cerebro.md`, tabla de casos borde
- **Problema:** el caso borde documenta que con `riesgo_disponible_pct = 0.0` el
  `multiplicador_riesgo` debe ser `0.0`. Pero no especifica si esto lo **fuerza el código**
  de `brain.py` *antes* de llamar al LLM, o *después* de recibir su respuesta, o si es
  solo una expectativa del modelo.
  
  Sin esta especificación, el desarrollador puede implementarlo de tres formas distintas,
  con comportamientos observables diferentes en el log (¿el LLM se llama igualmente o no?).
  
- **Corrección:** se actualizó la tabla de casos borde en `contrato_cerebro.md` con una
  columna "Quién lo fuerza" para los dos casos que necesitan override de código:
  
  | Situación | Comportamiento esperado | Quién lo fuerza |
  |---|---|---|
  | `riesgo_disponible_pct = 0.0` | El cerebro puede analizar, pero `multiplicador_riesgo` debe ser `0.0`. | Código en `brain.py` — clampear el valor post-validación antes de devolver `DecisionCerebro`. El LLM se llama igualmente para registrar el régimen. |
  | `senal_base = "NONE"` | `evaluacion_senal` siempre `"neutral"`, `multiplicador_riesgo = 0.0`. | El system prompt lo instruye; si el LLM devuelve otro valor, el código lo clampea como `SCHEMA_INVALIDO` parcial — pero **no** activa el fallback completo. Loguear la anomalía. |

---

### P3 — Qué hacer ante validación de salida fallida es ambiguo (MENOR — resuelto)

- **Doc:** `docs/contrato_cerebro.md`, sección "Validaciones de salida"
- **Problema:** el doc dice "ante cualquier falla de validación de salida → devolver
  respuesta default". Pero no distingue entre:
  
  a) Campo fuera de rango clampeable (e.g. `multiplicador_riesgo = 1.3` → clampear a `1.0`)
  b) Campo con tipo incorrecto o enum inválido (no clampeable — fallback)
  
  El doc actual trata todos los casos igual (fallback). Sin embargo, el contrato ya admite
  clampeo explícito para `multiplicador_riesgo > 1.0` (sección "Semántica de los campos").
  Esta inconsistencia puede confundir al desarrollador.
  
- **Corrección:** se actualizó la tabla de validaciones de salida en `contrato_cerebro.md`
  para agregar una columna "Acción ante falla":
  
  | Campo | Restricción | Acción ante falla |
  |---|---|---|
  | `regimen` | enum exacto | Fallback completo — `SCHEMA_INVALIDO` |
  | `confianza_regimen` | `[0.0, 1.0]` | Clampear; loguear anomalía |
  | `evaluacion_senal` | enum exacto | Fallback completo — `SCHEMA_INVALIDO` |
  | `conviccion` | `[0.0, 1.0]` | Clampear; loguear anomalía |
  | `multiplicador_riesgo` | `[0.0, 1.0]` | Clampear; loguear anomalía (ya documentado en "Semántica") |
  | `factores_clave` | longitud `[1, 5]` | Fallback completo — `SCHEMA_INVALIDO` |
  | `racional` | no vacío, máx 280 chars | Si supera 280: truncar a 277 + "..."; loguear. Si vacío: fallback — `SCHEMA_INVALIDO` |
  | `alertas` | puede ser vacío | Sin acción — nunca falla |

---

### P4 — Disco de claves Python vs claves de serialización en Timeframes TypedDict (MENOR — pendiente de decisión del usuario)

- **Doc:** `src/types.py`, clase `Timeframes`
- **Problema:** el `TypedDict` define los campos como `h4`, `d1`, `h1` (identificadores
  Python válidos), pero el contrato y el código de `context_builder.py` usan las claves
  `"4h"`, `"1d"`, `"1h"` en el dict real. El TypedDict no puede usar claves que empiecen
  con dígitos, por lo que el comentario en `types.py` documenta esta discrepancia.
  
  Sin embargo, el tipo de `ContextoMercado.timeframes` está declarado como `dict` (sin
  tipo genérico), lo que anula cualquier chequeo estático de los sub-dicts. El desarrollador
  de `brain.py` necesita saber a qué clave acceder: `contexto["timeframes"]["4h"]` o
  `contexto.timeframes.h4`.
  
- **Estado:** NO bloqueante para brain.py porque el acceso correcto es por clave string
  (`["4h"]`, `["1d"]`, `["1h"]`), tal como lo hace `context_builder.py`. El TypedDict
  `Timeframes` con claves `h4`/`d1`/`h1` no se usa en el código actual — `ContextoMercado`
  declara `timeframes: dict`. Pero es una deuda técnica de tipos que puede confundir.
  
- **PENDIENTE DE DECISIÓN DEL USUARIO:** ¿se elimina `Timeframes` de `types.py` (ya que
  no se usa), o se mantiene como documentación aunque los nombres no coincidan? Esta
  decisión no bloquea Fase 2 pero debe resolverse antes de Fase 3 para que el type checker
  no genere falsos positivos.

---

## Correcciones aplicadas a los documentos

### Cambios en `docs/system_prompt.md`

Se agregó la subsección "Formato del mensaje de usuario" dentro del bloque
"Formato de la llamada al LLM":

```python
# Formato del mensaje de usuario
# El ContextoMercado se serializa como JSON legible precedido de un prefijo fijo.
# Todos los campos se incluyen — no se filtra ninguno.
USER_MESSAGE_TEMPLATE = "Evalúa la siguiente señal de trading:\n\n{contexto_json}"

# Serialización: json.dumps con indent=2 y ensure_ascii=False para preservar
# caracteres especiales (e.g., "BTC/USDT" no necesita escape, pero es buena práctica).
import json
contexto_json = json.dumps(contexto, indent=2, ensure_ascii=False)
user_message = USER_MESSAGE_TEMPLATE.format(contexto_json=contexto_json)
```

### Cambios en `docs/contrato_cerebro.md`

1. Se reemplazó la tabla de "Validaciones de salida" para incluir la columna
   "Acción ante falla" con la distinción entre clampeo y fallback completo.
2. Se actualizó la tabla de "Casos borde" para agregar la columna "Quién lo fuerza"
   en los dos casos que requieren override de código.

---

## Items pendientes

| Item | Prioridad | Bloquea |
|---|---|---|
| Decisión sobre `Timeframes` TypedDict en `types.py` (P4) | Baja | No bloquea Fase 2 ni Fase 3; resolver antes de activar type checking estricto |

---

## Veredicto

**La documentación está lista para implementar `brain.py`.** No hay huecos bloqueantes.

El desarrollador puede implementar `brain.py` con la especificación completa disponible:

1. Tool definition: completa en `system_prompt.md` con todos los campos, tipos y enums.
2. Fallback: todos los campos definidos en `contrato_cerebro.md`, coincide con el schema del tool.
3. Validaciones post-tool: tabla de acciones explícita (clampear vs fallback completo) en `contrato_cerebro.md`.
4. Formato de entrada al LLM: especificado en `system_prompt.md` (JSON con `indent=2` + prefijo fijo).
5. `DecisionCerebro` TypedDict: existe en `src/types.py` con todos los campos correctos.
6. Variables de entorno: `ANTHROPIC_API_KEY` y `ANTHROPIC_MODEL` en `.env.example` y `CLAUDE.md`.
7. Casos borde: tabla completa con columna "Quién lo fuerza" para los overrides de código.

El único punto pendiente (P4 — `Timeframes` TypedDict) no afecta la implementación de `brain.py`.
