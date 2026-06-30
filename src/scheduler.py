"""
Scheduler — Fase 4.

Loop principal del paper trader. Se ejecuta indefinidamente hasta interrupción (Ctrl+C).
Cada vela 1H: construye contexto MTF → calcula señal base → llama al cerebro → paper trader.

Restricciones innegociables:
- CERO trading con dinero real — solo simulación.
- Logging con el módulo estándar logging, no print.
- Type hints en todas las funciones públicas.
- Cualquier excepción en un ciclo → loguear y continuar (nunca romper el loop).
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from src import logger as db_logger
from src.brain import analizar
from src.context_builder import construir_contexto
from src import notifier
from src.paper_trader import EstadoPaperTrader, crear_estado, procesar_vela
from src.strategy import calcular_senal

load_dotenv()

log = logging.getLogger(__name__)


def _tiempo_hasta_proximo_cierre_1h() -> float:
    """
    Calcula los segundos hasta el próximo cierre de vela 1H (HH:00:00 UTC).

    Returns:
        Segundos hasta el próximo cierre (float, siempre > 0).
    """
    now = datetime.now(timezone.utc)
    next_close = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    wait_seconds = (next_close - now).total_seconds()
    return wait_seconds


def _dormir_hasta(wait_seconds: float) -> None:
    """
    Duerme wait_seconds en bloques de 60 s para poder interrumpir con Ctrl+C.
    Loguea cada minuto para dar señal de vida.
    """
    remaining = wait_seconds
    log.info("Esperando %.0f segundos hasta el próximo cierre de vela 1H...", remaining)

    while remaining > 0:
        chunk = min(60.0, remaining)
        time.sleep(chunk)
        remaining -= chunk
        if remaining > 0:
            log.debug("%.0f segundos restantes hasta el cierre de vela", remaining)


def _construir_vela_ohlcv_desde_contexto(contexto: dict) -> dict:
    """
    Extrae los valores OHLCV de la vela 1H desde el contexto MTF.

    Nota: Esta es una aproximación para Fase 4. En Fase 5 se puede mejorar
    descargando la vela OHLCV exacta que acaba de cerrar.

    El contexto 1H tiene precio_actual (= close) y listas de max/min recientes.
    Usamos:
      - open  ≈ close (no disponible en el contexto actual — misma aproximación)
      - high  = max(maximos_recientes)
      - low   = min(minimos_recientes)
      - close = precio_actual
    """
    tf_1h = contexto["timeframes"]["1h"]
    close = float(tf_1h["estructura"]["precio_actual"])
    maximos = tf_1h["estructura"]["maximos_recientes"]
    minimos = tf_1h["estructura"]["minimos_recientes"]

    high = max(float(v) for v in maximos) if maximos else close
    low  = min(float(v) for v in minimos) if minimos else close

    return {
        "open":  close,  # aproximación: usamos close como proxy del open
        "high":  high,
        "low":   low,
        "close": close,
    }


def run(
    par: str = "BTC/USDT",
    mercado_tipo: str = "spot",
) -> None:
    """
    Loop paper end-to-end por vela 1H.

    Pasos por ciclo:
    1. Calcular tiempo hasta el próximo cierre de vela 1H y dormir.
    2. Construir contexto MTF (incluye señal base via strategy.py).
    3. Loguear la señal base calculada.
    4. Llamar al cerebro (analizar) y medir latencia.
    5. Insertar brain_call en SQLite.
    6. Pasar la vela al paper trader.
    7. Log de resumen en consola.
    8. Volver al paso 1.

    Args:
        par:          Ticker a monitorear (e.g. "BTC/USDT").
        mercado_tipo: "spot" | "futuro".
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    db_path = os.environ.get("DB_PATH", "trading_brain.db")
    initial_balance = float(os.environ.get("PAPER_INITIAL_BALANCE", "10000"))
    model = os.environ.get("LLM_MODEL") or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    log.info("=== Iniciando scheduler paper trader ===")
    log.info("Par: %s | Mercado: %s | Balance inicial: %.2f USDT", par, mercado_tipo, initial_balance)
    log.info("DB: %s | Modelo LLM: %s", db_path, model)

    # Inicializar DB y estado del paper trader
    db_logger.init_db(db_path)
    estado: EstadoPaperTrader = crear_estado(initial_balance)

    # Notificar inicio
    try:
        notifier.notificar_inicio(par, initial_balance)
    except Exception as exc:  # noqa: BLE001
        log.warning("Error en notifier.notificar_inicio: %s", exc)

    ciclo = 0

    try:
        while True:
            ciclo += 1
            log.info("--- Ciclo #%d ---", ciclo)

            # 1. Dormir hasta el próximo cierre de vela 1H
            wait_seconds = _tiempo_hasta_proximo_cierre_1h()
            _dormir_hasta(wait_seconds)

            # 2. Construir contexto MTF
            log.info("[%d] Construyendo contexto MTF para %s...", ciclo, par)
            try:
                posicion_actual = estado.posicion_actual
                riesgo_disponible = 1.0 if posicion_actual == "NONE" else 0.0

                contexto = construir_contexto(
                    par=par,
                    mercado_tipo=mercado_tipo,
                    posicion_actual=posicion_actual,
                    riesgo_disponible_pct=riesgo_disponible,
                )
            except Exception as exc:  # noqa: BLE001
                log.error("[%d] Error construyendo contexto: %s — saltando ciclo", ciclo, exc)
                continue

            senal_base = calcular_senal(contexto)
            log.info("[%d] Señal base: %s", ciclo, senal_base)

            # 3. Llamar al cerebro (siempre, para registrar el contexto en brain_calls)
            import time as _time
            t0 = _time.monotonic()
            try:
                decision = analizar(contexto)
            except Exception as exc:  # noqa: BLE001
                log.error("[%d] Error inesperado en analizar(): %s — saltando ciclo", ciclo, exc)
                continue
            latency_ms = int((_time.monotonic() - t0) * 1000)

            log.info(
                "[%d] Cerebro — regimen=%s eval=%s mult=%.2f conviccion=%.2f latency=%dms",
                ciclo,
                decision["regimen"],
                decision["evaluacion_senal"],
                decision["multiplicador_riesgo"],
                decision["conviccion"],
                latency_ms,
            )

            # Notificar señal y decisión del cerebro si había señal LONG o SHORT
            if senal_base in ("LONG", "SHORT"):
                try:
                    rsi_1h = float(contexto["timeframes"]["1h"]["indicadores"]["rsi"])
                    notifier.notificar_senal(
                        par=par,
                        senal=senal_base,
                        precio=float(contexto["timeframes"]["1h"]["estructura"]["precio_actual"]),
                        rsi=rsi_1h,
                        regimen=decision["regimen"],
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("Error en notifier.notificar_senal: %s", exc)

                try:
                    notifier.notificar_decision(
                        par=par,
                        senal=senal_base,
                        evaluacion=decision["evaluacion_senal"],
                        multiplicador=decision["multiplicador_riesgo"],
                        conviccion=decision["conviccion"],
                        racional=decision["racional"],
                        alertas=decision["alertas"],
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("Error en notifier.notificar_decision: %s", exc)

            # Notificar fallback si el cerebro lo activó
            if "FALLBACK_ACTIVADO" in decision["alertas"]:
                try:
                    notifier.notificar_fallback(par=par, razon="FALLBACK_ACTIVADO")
                except Exception as exc:  # noqa: BLE001
                    log.warning("Error en notifier.notificar_fallback: %s", exc)

            # 4. Insertar brain_call en SQLite
            try:
                brain_call_id = db_logger.log_brain_call(
                    db_path=db_path,
                    par=par,
                    timeframe="1h",
                    candle_timestamp=contexto["timestamp"],
                    context=contexto,
                    decision=decision,
                    raw_response=None,  # no disponible desde analizar() en esta fase
                    model=model,
                    latency_ms=latency_ms,
                )
            except Exception as exc:  # noqa: BLE001
                log.error("[%d] Error insertando brain_call: %s — saltando ciclo", ciclo, exc)
                continue

            # 5. Obtener vela OHLCV aproximada desde el contexto
            vela_ohlcv = _construir_vela_ohlcv_desde_contexto(contexto)

            # 6. Procesar vela en el paper trader
            try:
                estado = procesar_vela(
                    estado=estado,
                    contexto=contexto,
                    decision=decision,
                    brain_call_id=brain_call_id,
                    vela_ohlcv=vela_ohlcv,
                    db_path=db_path,
                )
            except Exception as exc:  # noqa: BLE001
                log.error("[%d] Error en procesar_vela(): %s — continuando con estado anterior", ciclo, exc)
                continue

            # 7. Resumen del ciclo
            log.info(
                "[%d] RESUMEN — equity=%.2f USDT | cash=%.2f | posicion=%s | "
                "senal=%s | eval_cerebro=%s | racional: %s",
                ciclo,
                estado.equity,
                estado.cash,
                estado.posicion_actual,
                senal_base,
                decision["evaluacion_senal"],
                decision["racional"],
            )

            # Notificar resumen de la vela (siempre)
            try:
                notifier.notificar_vela(
                    par=par,
                    timestamp=contexto["timestamp"],
                    senal=senal_base,
                    regimen=decision["regimen"],
                    evaluacion=decision["evaluacion_senal"],
                    equity=estado.equity,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Error en notifier.notificar_vela: %s", exc)

    except KeyboardInterrupt:
        log.info("Scheduler interrumpido por el usuario (Ctrl+C). Cerrando.")
        log.info(
            "Estado final — equity=%.2f USDT | posicion=%s | ciclos completados: %d",
            estado.equity, estado.posicion_actual, ciclo,
        )
