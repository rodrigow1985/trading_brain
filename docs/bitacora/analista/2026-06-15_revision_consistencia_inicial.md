---
agente: analista
fecha: 2026-06-15
tarea: Revisión de consistencia inicial — todos los documentos antes de Fase 1
estado: completado
archivos_modificados:
  - docs/contrato_cerebro.md
  - docs/system_prompt.md
  - docs/log_schema.md
  - docs/paper_trader.md
  - docs/arquitectura.md
  - .env.example
  - CLAUDE.md
  - .claude/agents/desarrollador.md
---

## Resumen

Revisión completa de consistencia entre los 7 documentos del proyecto más `.env.example` y los agentes, previa al inicio de la Fase 1. Se encontraron **10 problemas** — todos resueltos. Los docs quedaron listos para que el desarrollador implemente `context_builder.py`.

---

## Problemas encontrados y correcciones aplicadas

### P1 — `SIGNAL_CLOSE` mezclaba dos semánticas distintas (crítico)
- **Doc:** `docs/paper_trader.md`
- **Problema:** la tabla decía que `SIGNAL_CLOSE` se activa "después de N velas sin movimiento", pero también "cuando la señal deja de estar activa". Son dos condiciones distintas.
- **Corrección:** se separaron en dos `exit_reason`: `SIGNAL_CLOSE` (señal vuelve a `NONE`) y `TIMEOUT` (N velas transcurridas). Orden de evaluación definido: `TIMEOUT` antes que `SIGNAL_CLOSE`. También actualizado en `log_schema.md`.

### P2 — Notas obsoletas "agregar a .env.example" en dos documentos (menor)
- **Docs:** `docs/log_schema.md` y `docs/paper_trader.md`
- **Problema:** ambos pedían agregar variables que ya estaban en `.env.example`.
- **Corrección:** en `log_schema.md` se reemplazó la nota por una tabla de valores de `fallback_reason`. En `paper_trader.md` se convirtió en tabla de referencia.

### P3 — `fallback_reason` sin valores definidos (crítico)
- **Doc:** `docs/log_schema.md`
- **Problema:** la columna existía pero sin valores posibles documentados. El desarrollador habría tenido que inventarlos.
- **Corrección:** se definieron 5 valores: `"CONTEXTO_INVALIDO"`, `"API_ERROR"`, `"JSON_MALFORMADO"`, `"SCHEMA_INVALIDO"`, `"TOOL_NO_LLAMADO"`.

### P4 — Validación de `racional` incompleta (menor)
- **Doc:** `docs/contrato_cerebro.md`
- **Problema:** la tabla de validaciones decía solo "no vacío" pero el schema especificaba máx 280 caracteres.
- **Corrección:** tabla actualizada a `"no vacío, máx 280 caracteres"`.

### P5 — `multiplicador_riesgo = 0.0` para `NONE` no estaba en el system prompt (crítico)
- **Docs:** `docs/contrato_cerebro.md` vs `docs/system_prompt.md`
- **Problema:** el contrato lo establece pero el prompt solo instruía `evaluacion_senal = "neutral"`, sin mencionar el multiplicador.
- **Corrección:** prompt actualizado para decir "siempre devolver `evaluacion_senal = 'neutral'` y `multiplicador_riesgo = 0.0`" cuando `senal_base = NONE`.

### P6 — Schema de tool use no enforcea rangos numéricos (menor)
- **Doc:** `docs/system_prompt.md`
- **Problema:** el `input_schema` del tool no incluye `minimum`/`maximum` — un desarrollador podría asumir que la validación ya está cubierta.
- **Corrección:** nota explícita agregada: los rangos numéricos, longitudes de array y longitud de `racional` deben validarse en código después de recibir la respuesta.

### P7 — Mapeo `CCXT_MARKET_TYPE` ("future") → `mercado_tipo` ("futuro") no documentado (menor)
- **Docs:** `CLAUDE.md` / `.env.example` vs `docs/contrato_cerebro.md`
- **Problema:** la variable de entorno usa nomenclatura ccxt ("future") pero el contrato usa español ("futuro"). El mapeo no estaba documentado.
- **Corrección:** comentario inline agregado en el schema de entrada de `contrato_cerebro.md`.

### P8 — Modelo hardcodeado sin variable de entorno (menor)
- **Docs:** `docs/system_prompt.md` y `.env.example`
- **Problema:** `MODEL = "claude-sonnet-4-6"` hardcodeado, sin forma de cambiarlo sin tocar el código.
- **Corrección:** agregada `ANTHROPIC_MODEL=claude-sonnet-4-6` a `.env.example` y `CLAUDE.md`. `system_prompt.md` actualizado a `os.environ["ANTHROPIC_MODEL"]`. Agente desarrollador actualizado con la nueva variable.

### P9 — Cash mínimo hardcodeado en lugar de derivado (menor)
- **Doc:** `docs/paper_trader.md`
- **Problema:** la regla decía "500 USDT (5% del balance inicial)" mezclando valor absoluto con porcentaje. Si `PAPER_INITIAL_BALANCE` cambia, el 5% ya no sería 500.
- **Corrección:** la regla ahora especifica `PAPER_INITIAL_BALANCE * 0.05`, no un valor fijo.

### P10 — Diagrama omitía flujo de cierre por desaparición de señal (menor)
- **Doc:** `docs/arquitectura.md`
- **Problema:** el diagrama mostraba `SIG → NO → LOG` sin contemplar el caso de posición abierta con señal que vuelve a `NONE`.
- **Corrección:** nota al pie agregada documentando la simplificación y apuntando a `paper_trader.md`.

---

## Decisiones tomadas durante esta sesión

| Decisión | Resolución |
|---|---|
| ¿`SIGNAL_CLOSE` y `TIMEOUT` son lo mismo o distintos? | Distintos. `SIGNAL_CLOSE` = señal vuelve a `NONE`. `TIMEOUT` = N velas sin cierre. |
| ¿El modelo del LLM debe ser configurable? | Sí, via `ANTHROPIC_MODEL` en `.env`. Default: `claude-sonnet-4-6`. |
| ¿El cash mínimo es un valor fijo o un porcentaje? | Porcentaje: `PAPER_INITIAL_BALANCE * 0.05`. |
| ¿Qué valores puede tomar `fallback_reason`? | 5 valores definidos: `CONTEXTO_INVALIDO`, `API_ERROR`, `JSON_MALFORMADO`, `SCHEMA_INVALIDO`, `TOOL_NO_LLAMADO`. |

---

## Items pendientes (no bloqueantes para Fase 1)

- La simplificación del diagrama de arquitectura (cierre por `SIGNAL_CLOSE`/`TIMEOUT`) podría refinarse cuando el paper trader esté implementado.
- `CCXT_TESTNET` y `CCXT_MARKET_TYPE` no aparecen en docs de `docs/` — están en `CLAUDE.md` y `.env.example`, suficiente por ahora.

---

## Veredicto

**Los docs están listos para Fase 1.** El desarrollador puede implementar `context_builder.py` sin necesidad de tomar ninguna decisión de diseño no documentada.
