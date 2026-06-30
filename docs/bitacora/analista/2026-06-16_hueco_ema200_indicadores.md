---
agente: analista
fecha: 2026-06-16
tarea: Documentar hueco de EMA(200) — parámetros de descarga distintos para timeframe 1D
estado: completado
archivos_modificados:
  - docs/indicadores.md
  - docs/bitacora/estado_proyecto.md
---

## Resumen

Se documentó el hueco de spec identificado por el desarrollador durante la Fase 1: el timeframe `1d` descarga 250 velas (en lugar de 200) para garantizar 200 velas válidas post-warmup, necesarias para que EMA(200) devuelva valores no-NaN. La sección "Parámetros de descarga" de `docs/indicadores.md` fue reestructurada para reflejar esto. El hueco fue eliminado de `estado_proyecto.md`.

---

## Problemas encontrados y correcciones aplicadas

### P1 — Tabla de parámetros de descarga no diferenciaba timeframes (hueco de spec)

- **Doc:** `docs/indicadores.md`, sección "Parámetros de descarga"
- **Problema:** la tabla original listaba un único conjunto de parámetros para todos los timeframes (200 velas descargadas / 150 válidas). Sin embargo, EMA(200) calculada en el timeframe `1d` requiere al menos 200 velas válidas — con 150, `pandas_ta.ema(close, length=200)` devuelve `NaN` en todas las filas. El desarrollador resolvió esto en código usando `VELAS_DESCARGAR_1D = 250`, pero la spec no lo reflejaba.
- **Corrección:** la sección fue reestructurada en dos partes:
  - "Parámetros generales" (1H y 4H): 200 descargadas / 150 válidas — sin cambios
  - "Excepción: timeframe 1D": 250 descargadas / 200 válidas, con nota explicativa sobre la constante `VELAS_DESCARGAR_1D` en `context_builder.py`

### P2 — Entrada "pendiente doc" en estado_proyecto.md

- **Doc:** `docs/bitacora/estado_proyecto.md`
- **Problema:** la tabla de decisiones técnicas marcaba "pendiente doc en indicadores.md" para la decisión de velas 1D. La sección de huecos de spec también listaba este ítem como acción requerida.
- **Corrección:** la referencia en la tabla de decisiones apunta ahora a `docs/indicadores.md`. La sección "Huecos de spec pendientes de documentar" fue vaciada con la nota "_(ninguno pendiente)_". La nota entre paréntesis en la lista de archivos de documentación también fue eliminada.

---

## Decisiones tomadas durante esta sesión

| Decisión | Resolución |
|---|---|
| ¿Cuántas velas válidas necesita EMA(200)? | 200 exactas — la primera vela calculable por EMA(n) requiere n puntos. |
| ¿Los timeframes 1H y 4H cambian sus parámetros? | No. Siguen con 200 descargadas / 150 válidas. Solo 1D es distinto. |
| ¿El checklist al final de `indicadores.md` requiere cambios? | No. Los ítems del checklist son genéricos para cualquier cambio de parámetros y siguen siendo válidos. |

---

## Items pendientes

_(ninguno)_

---

## Veredicto

El hueco de spec está cerrado. `docs/indicadores.md` ahora refleja fielmente el comportamiento implementado en `context_builder.py`. No quedan huecos de spec pendientes. El proyecto puede avanzar a Fase 2 sin ambigüedades sobre los parámetros de descarga.
