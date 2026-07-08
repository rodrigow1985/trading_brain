"""
Estado persistente del scanner — anti-duplicados de alertas.

Regla (spec estrategias v2): si una situación ya se alertó para un ticker,
no volver a alertarla hasta que la condición se resetee (deje de cumplirse
al menos una vez).

Tabla scanner_situaciones en la misma base SQLite del proyecto (DB_PATH):
    par            TEXT  — ticker
    situacion      TEXT  — id de la estrategia (ej. SIT1_TOQUE_EMA20)
    activa         INTEGER — 1 si la condición se cumplió en el último escaneo
    ultima_alerta  TEXT  — ISO 8601 de la última alerta enviada
    actualizado    TEXT  — ISO 8601 del último escaneo que tocó la fila
"""

import logging
import sqlite3
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scanner_situaciones (
    par           TEXT NOT NULL,
    situacion     TEXT NOT NULL,
    activa        INTEGER NOT NULL DEFAULT 0,
    ultima_alerta TEXT,
    actualizado   TEXT NOT NULL,
    PRIMARY KEY (par, situacion)
);
"""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


# Nota: `with sqlite3.connect(...)` solo maneja la transacción, NO cierra la
# conexión — se cierra explícitamente para no dejar el archivo bloqueado.

def init(db_path: str) -> None:
    """Crea la tabla si no existe (idempotente)."""
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(_SCHEMA)
    finally:
        conn.close()


def estaba_activa(db_path: str, par: str, situacion: str) -> bool:
    """True si la situación ya estaba activa (alertada y sin resetear)."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT activa FROM scanner_situaciones WHERE par = ? AND situacion = ?",
            (par, situacion),
        ).fetchone()
    finally:
        conn.close()
    return bool(row and row[0])


def actualizar(db_path: str, par: str, situacion: str, activa: bool, alerto: bool = False) -> None:
    """
    Registra el estado de la situación tras un escaneo.

    activa=False resetea la condición → la próxima vez que se cumpla vuelve
    a alertar. alerto=True actualiza además el timestamp de última alerta.
    """
    ahora = _ahora()
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            if alerto:
                conn.execute(
                    """
                    INSERT INTO scanner_situaciones (par, situacion, activa, ultima_alerta, actualizado)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(par, situacion) DO UPDATE SET
                        activa = excluded.activa,
                        ultima_alerta = excluded.ultima_alerta,
                        actualizado = excluded.actualizado
                    """,
                    (par, situacion, int(activa), ahora, ahora),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO scanner_situaciones (par, situacion, activa, actualizado)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(par, situacion) DO UPDATE SET
                        activa = excluded.activa,
                        actualizado = excluded.actualizado
                    """,
                    (par, situacion, int(activa), ahora),
                )
    finally:
        conn.close()
