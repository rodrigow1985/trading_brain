"""
Harness de validación pasiva — Fase 3.

Corre el cerebro en vivo sobre contexto real pero SIN ejecutar trades.
Solo observa, loguea en SQLite y muestra un resumen por consola.

Uso:
    python scripts/validate_brain.py              # 5 iteraciones (default)
    python scripts/validate_brain.py --iterations 2

Restricciones:
- CERO ejecución de trades.
- Si construir_contexto falla → loguear error y continuar.
- Si analizar devuelve fallback → registrar y continuar.
"""

import argparse
import logging
import os
import time

from dotenv import load_dotenv

load_dotenv()

# Configurar logging antes de importar módulos del proyecto
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

# Imports del proyecto (después de load_dotenv para que lean el entorno)
from src.brain import analizar  # noqa: E402
from src.context_builder import construir_contexto  # noqa: E402
from src.logger import init_db, log_brain_call  # noqa: E402

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_PAR = "BTC/USDT"
_MERCADO_TIPO = "spot"
_POSICION_ACTUAL = "NONE"
_RIESGO_DISPONIBLE_PCT = 1.0
_TIMEFRAME_LOG = "1h"        # timeframe que se loguea como "evaluado"
_SLEEP_ENTRE_ITER = 5        # segundos entre iteraciones


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Harness de validación pasiva — corre el cerebro sin ejecutar trades."
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Número de iteraciones (default: 5)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    n_iter: int = args.iterations

    db_path = os.environ.get("DB_PATH", "trading_brain.db")
    model = (
        os.environ.get("LLM_MODEL")
        or os.environ.get("ANTHROPIC_MODEL")
        or "claude-sonnet-4-6"
    )

    logger.info("=== Validación pasiva iniciada ===")
    logger.info("Iteraciones: %d | DB: %s | Modelo: %s", n_iter, db_path, model)

    # Inicializar DB
    init_db(db_path)

    filas_insertadas = 0

    for i in range(1, n_iter + 1):
        logger.info("--- Iteración %d/%d ---", i, n_iter)

        # 1. Construir contexto (puede fallar por red o exchange)
        try:
            contexto = construir_contexto(
                par=_PAR,
                mercado_tipo=_MERCADO_TIPO,
                posicion_actual=_POSICION_ACTUAL,
                riesgo_disponible_pct=_RIESGO_DISPONIBLE_PCT,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Error construyendo contexto en iteración %d/%d: %s — continuando",
                i, n_iter, exc,
            )
            if i < n_iter:
                time.sleep(_SLEEP_ENTRE_ITER)
            continue

        candle_timestamp: str = contexto.get("timestamp", "")  # type: ignore[assignment]

        # 2. Llamar al cerebro y medir latencia
        t0 = time.monotonic()
        decision = analizar(contexto)
        latency_ms = int((time.monotonic() - t0) * 1000)

        # 3. Loguear en SQLite
        row_id = log_brain_call(
            db_path=db_path,
            par=_PAR,
            timeframe=_TIMEFRAME_LOG,
            candle_timestamp=candle_timestamp,
            context=contexto,
            decision=decision,
            raw_response=None,   # brain.py no expone el raw; se completa en Fase 5
            model=model,
            latency_ms=latency_ms,
        )
        filas_insertadas += 1

        # 4. Imprimir resumen de la iteración
        regimen = decision.get("regimen", "?")
        evaluacion = decision.get("evaluacion_senal", "?")
        multiplicador = decision.get("multiplicador_riesgo", 0.0)
        is_fallback = "FALLBACK_ACTIVADO" in decision.get("alertas", [])

        fallback_tag = " [FALLBACK]" if is_fallback else ""
        print(
            f"[{i}/{n_iter}] {_PAR} {_TIMEFRAME_LOG} | "
            f"régimen={regimen} | "
            f"eval={evaluacion} | "
            f"mult={multiplicador:.2f} | "
            f"latencia={latency_ms}ms | "
            f"id={row_id}"
            f"{fallback_tag}"
        )

        # 5. Esperar entre iteraciones (salvo la última)
        if i < n_iter:
            logger.debug("Esperando %ds antes de la siguiente iteración", _SLEEP_ENTRE_ITER)
            time.sleep(_SLEEP_ENTRE_ITER)

    # Resumen final
    print(f"\nValidación pasiva completada — {filas_insertadas}/{n_iter} filas insertadas en brain_calls.")
    logger.info(
        "=== Validación pasiva finalizada — %d/%d filas insertadas ===",
        filas_insertadas, n_iter,
    )


if __name__ == "__main__":
    main()
