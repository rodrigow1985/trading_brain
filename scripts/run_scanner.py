"""
Scanner 4H — entrypoint.

Escanea múltiples activos al cierre de cada vela 4H y notifica a Telegram
cuando el cerebro confirma una señal LONG.

Uso:
    docker compose run --rm brain python scripts/run_scanner.py

    # Escaneo inmediato sin esperar la vela (útil para pruebas)
    docker compose run --rm brain python scripts/run_scanner.py --ahora
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from src import notifier
from src.scanner import escanear
from src.watchlist import TODOS as PARES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def _tiempo_hasta_proximo_cierre_4h() -> float:
    """Calcula segundos hasta el próximo cierre de vela 4H (00, 04, 08, 12, 16, 20 UTC)."""
    now = datetime.now(timezone.utc)
    hora_actual = now.hour
    # Siguiente múltiplo de 4 horas
    proxima_hora = ((hora_actual // 4) + 1) * 4

    if proxima_hora >= 24:
        next_close = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        next_close = now.replace(
            hour=proxima_hora, minute=0, second=0, microsecond=0
        )

    return max(0.0, (next_close - now).total_seconds())


def _dormir_hasta(wait_seconds: float) -> None:
    remaining = wait_seconds
    log.info("Esperando %.0f segundos hasta el próximo cierre de vela 4H...", remaining)
    while remaining > 0:
        time.sleep(min(60.0, remaining))
        remaining -= 60.0
        if remaining > 60:
            log.debug("%.0f segundos restantes hasta el cierre de vela 4H", remaining)


def _notificar_resultados(resultados: list[dict]) -> None:
    for r in resultados:
        par = r["par"]
        metricas = r["metricas_4h"]
        decision = r["decision"]

        try:
            notifier.notificar_scanner_match(
                par=par,
                precio=metricas["precio"],
                ema20=metricas["ema20"],
                dist_ema20_pct=metricas["dist_ema20_pct"],
                rsi_4h=metricas["rsi"],
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Error en notificar_scanner_match para %s: %s", par, exc)

        try:
            notifier.notificar_decision(
                par=par,
                senal="LONG",
                evaluacion=decision["evaluacion_senal"],
                multiplicador=decision["multiplicador_riesgo"],
                conviccion=decision["conviccion"],
                racional=decision["racional"],
                alertas=decision["alertas"],
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Error en notificar_decision para %s: %s", par, exc)


def run(escanear_ahora: bool = False) -> None:
    log.info("=== Scanner 4H iniciado ===")
    log.info("Activos: %d — %s", len(PARES), ", ".join(PARES))

    ciclo = 0

    while True:
        ciclo += 1

        if not escanear_ahora or ciclo > 1:
            wait_sec = _tiempo_hasta_proximo_cierre_4h()
            _dormir_hasta(wait_sec)

        log.info("[Ciclo %d] Iniciando escaneo de %d activos...", ciclo, len(PARES))

        try:
            resultados = escanear(PARES)
        except Exception as exc:  # noqa: BLE001
            log.error("[Ciclo %d] Error en escanear(): %s", ciclo, exc)
            continue

        if resultados:
            log.info("[Ciclo %d] %d señal(es) confirmada(s) — notificando...", ciclo, len(resultados))
            _notificar_resultados(resultados)
        else:
            log.info("[Ciclo %d] Sin señales confirmadas en esta vela.", ciclo)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scanner 4H — escanea activos al cierre de cada vela.")
    parser.add_argument(
        "--ahora",
        action="store_true",
        help="Ejecutar el primer escaneo inmediatamente sin esperar el cierre de vela",
    )
    args = parser.parse_args()
    run(escanear_ahora=args.ahora)
