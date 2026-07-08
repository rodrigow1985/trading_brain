"""
Scanner 1D — entrypoint.

Escanea múltiples activos al cierre de la vela diaria (00:00 UTC) y notifica
a Telegram cuando se detecta una condición técnica relevante.

Uso:
    docker compose run --rm brain python scripts/run_scanner.py

    # Escaneo inmediato sin esperar el cierre de vela (útil para pruebas)
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

from src import notifier, scanner_state
from src.scanner import escanear
from src.strategies import get_strategy_set
from src.watchlist import TODOS as PARES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def _tiempo_hasta_cierre_1d() -> float:
    """Calcula segundos hasta el próximo cierre de vela 1D (00:00 UTC)."""
    now = datetime.now(timezone.utc)
    next_close = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(0.0, (next_close - now).total_seconds())


def _dormir_hasta(wait_seconds: float) -> None:
    remaining = wait_seconds
    proxima = datetime.now(timezone.utc) + timedelta(seconds=remaining)
    log.info("Esperando hasta el cierre de vela 1D — %s UTC", proxima.strftime("%Y-%m-%d 00:00"))
    while remaining > 0:
        time.sleep(min(60.0, remaining))
        remaining -= 60.0
        if remaining > 60:
            log.debug("%.0f segundos hasta el cierre de vela 1D", remaining)


def _notificar_resultados(resultados: list[dict]) -> None:
    for r in resultados:
        try:
            if "situaciones" in r:
                # Set v2: un mensaje por ticker con todas las situaciones nuevas
                notifier.notificar_situaciones(
                    par=r["par"],
                    fecha_vela=r["fecha_vela"],
                    situaciones=r["situaciones"],
                    activas_previas=r["activas_previas"],
                    prioritaria=r["prioritaria"],
                    metricas=r["metricas"],
                    analisis=r["analisis"]["analisis"],
                    nivel_atencion=r["analisis"]["nivel_atencion"],
                    alertas=r["analisis"]["alertas"],
                    chart_png=r.get("chart_png"),
                )
            else:
                # Set v1: un mensaje por estrategia
                notifier.notificar_scanner(
                    par=r["par"],
                    senal=r["senal"],
                    estrategia=r["estrategia"],
                    metricas=r["metricas"],
                    analisis=r["analisis"]["analisis"],
                    nivel_atencion=r["analisis"]["nivel_atencion"],
                    alertas=r["analisis"]["alertas"],
                    timeframe=r["timeframe"],
                    chart_png=r.get("chart_png"),
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("Error notificando alerta de %s: %s", r["par"], exc)


def run(escanear_ahora: bool = False) -> None:
    log.info("=== Scanner 1D iniciado — ejecuta al cierre de cada vela diaria (00:00 UTC) ===")
    log.info("Activos: %d — %s", len(PARES), ", ".join(PARES))

    ciclo = 0

    while True:
        ciclo += 1

        if not escanear_ahora or ciclo > 1:
            wait_sec = _tiempo_hasta_cierre_1d()
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

        # Heartbeat: confirma que la corrida terminó, haya o no alertas nuevas
        try:
            if get_strategy_set() == "v2":
                n_nuevas = sum(len(r["situaciones"]) for r in resultados)
                db_path = os.environ.get("DB_PATH", "trading_brain.db")
                n_activas = scanner_state.contar_activas(db_path)
            else:
                n_nuevas = len(resultados)
                n_activas = None
            notifier.notificar_resumen_scanner(
                n_activos=len(PARES), n_nuevas=n_nuevas, n_activas=n_activas,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Error enviando resumen del scanner: %s", exc)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scanner 1D — escanea activos al cierre de cada vela diaria (00:00 UTC).")
    parser.add_argument(
        "--ahora",
        action="store_true",
        help="Ejecutar el primer escaneo inmediatamente sin esperar el cierre de vela",
    )
    args = parser.parse_args()
    run(escanear_ahora=args.ahora)
