#!/usr/bin/env python3
"""Migra el legacy a mastil.db.

    python3 scripts/migrate_legacy.py --legacy-root /opt/guardian-telegram
    python3 scripts/migrate_legacy.py --legacy-root /opt/guardian-telegram --dry-run

Lo que trae:

    mastil_lite_v0.db        -> lite_reminders, lite_settings  (copia literal)
    mastil_lite_secret.key   -> data/lite_secret.key
    state.json               -> guardian_events, pomodoro_session, timer, offset
    vigia_runtime_state.json -> vigia_completed_events
    calendar_privacy_*.json  -> calendar_privacy_ledger
    gmail_bridge_state.json  -> gmail_session

Los recordatorios de la usuaria asistida se copian **fila por fila y sin recifrar**: las
columnas son las mismas y la llave es la misma, así que el texto cifrado sigue
siendo legible. Si esa llave no se copia, los recordatorios se pierden.

Es idempotente: correrlo dos veces no duplica nada.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as config_module           # noqa: E402
from database import open_database        # noqa: E402


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  ! no pude leer {path.name}: {exc}")
        return None


def migrate(legacy_root: Path, db, cfg, dry_run: bool = False) -> dict:
    informe: dict[str, int | str] = {}
    ahora = datetime.now().astimezone().isoformat()

    # ---------------------------------------------------------- llave Lite
    origen_llave = legacy_root / "mastil_lite_secret.key"
    if origen_llave.exists():
        if dry_run:
            informe["llave_lite"] = "se copiaría"
        else:
            cfg.lite_secret_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origen_llave, cfg.lite_secret_path)
            cfg.lite_secret_path.chmod(0o600)
            informe["llave_lite"] = "copiada"
    else:
        informe["llave_lite"] = "AUSENTE (los recordatorios quedarán ilegibles)"

    # ------------------------------------------------------ recordatorios
    origen_db = legacy_root / "mastil_lite_v0.db"
    if origen_db.exists():
        vieja = sqlite3.connect(str(origen_db))
        vieja.row_factory = sqlite3.Row
        filas = vieja.execute("SELECT * FROM lite_reminders ORDER BY id").fetchall()
        ajustes = vieja.execute("SELECT * FROM lite_settings").fetchall()
        vieja.close()

        if not dry_run:
            with db.transaction():
                for fila in filas:
                    db.execute(
                        """
                        INSERT OR REPLACE INTO lite_reminders
                            (id, user_chat_id, user_name, remind_at_utc, display_date,
                             display_time, activity_enc, status, alert_code,
                             first_alert_utc, last_alert_utc, created_at_utc,
                             confirmed_at_utc, timeout_at_utc)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        tuple(fila[k] for k in fila.keys()),
                    )
                for fila in ajustes:
                    db.execute(
                        """
                        INSERT OR REPLACE INTO lite_settings
                            (user_chat_id, paused, updated_at_utc)
                        VALUES (?,?,?)
                        """,
                        (fila["user_chat_id"], fila["paused"], fila["updated_at_utc"]),
                    )
        informe["recordatorios"] = len(filas)
    else:
        informe["recordatorios"] = 0

    # ------------------------------------------------------------- state
    estado = _load_json(legacy_root / "state.json") or {}

    if not dry_run and estado:
        with db.transaction():
            db.set_state("telegram_offset", int(estado.get("offset", 0) or 0))
            db.set_state("suspended", bool(estado.get("suspended", False)))

            activo = estado.get("current_event_id")
            for event_id, evento in (estado.get("events") or {}).items():
                db.execute(
                    """
                    INSERT OR REPLACE INTO guardian_events
                        (event_id, title, start_at, phase, last_sent, truce_until,
                         check_until, restart_until, rescue_started_at,
                         minutos_en_rescate, is_active, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event_id, evento.get("title", ""), evento.get("start", ahora),
                        evento.get("phase", "done"), evento.get("last_sent"),
                        evento.get("truce_until"), evento.get("check_until"),
                        evento.get("restart_until"), evento.get("rescue_started_at"),
                        int(evento.get("minutos_en_rescate", 0) or 0),
                        1 if event_id == activo and evento.get("phase") != "done" else 0,
                        ahora, ahora,
                    ),
                )

            pomo = estado.get("pomodoro") or {}
            db.execute(
                """
                UPDATE pomodoro_session SET
                    active=?, phase=?, focus=?, cycle=?, next_cycle=?, phase_until=?,
                    return_until=?, rescue_started_at=?, last_sent=?,
                    minutos_en_rescate=?, updated_at=?
                WHERE id = 1
                """,
                (
                    1 if pomo.get("active") else 0, pomo.get("phase"), pomo.get("focus"),
                    int(pomo.get("cycle", 1) or 1), int(pomo.get("next_cycle", 1) or 1),
                    pomo.get("phase_until"), pomo.get("return_until"),
                    pomo.get("rescue_started_at"), pomo.get("last_sent"),
                    int(pomo.get("minutos_en_rescate", 0) or 0), ahora,
                ),
            )

            timer = estado.get("timer") or {}
            db.execute(
                """
                UPDATE timer SET
                    active=?, status=?, duration_minutes=?, reason=?, started_at=?,
                    ends_at=?, paused_at=?, milestones=?, fired_milestones=?,
                    ringing_started_at=?, last_alarm_sent=?, updated_at=?
                WHERE id = 1
                """,
                (
                    1 if timer.get("active") else 0, timer.get("status", "idle"),
                    int(timer.get("duration_minutes", 0) or 0), timer.get("reason", "") or "",
                    timer.get("started_at"), timer.get("ends_at"), timer.get("paused_at"),
                    json.dumps(timer.get("milestones") or []),
                    json.dumps(timer.get("fired_milestones") or []),
                    timer.get("ringing_started_at"), timer.get("last_alarm_sent"), ahora,
                ),
            )

    informe["eventos_guardian"] = len(estado.get("events") or {})
    informe["offset"] = int(estado.get("offset", 0) or 0)

    # -------------------------------------------------------------- vigía
    vigia = _load_json(legacy_root / "vigia_runtime_state.json") or {}
    completados = vigia.get("completed_event_ids") or []
    if not dry_run and completados:
        with db.transaction():
            for event_id in completados:
                db.execute(
                    "INSERT OR REPLACE INTO vigia_completed_events(event_id, completed_at) VALUES (?,?)",
                    (event_id, ahora),
                )
    informe["vigia_completados"] = len(completados)

    # ------------------------------------------------------------- ledger
    ledger = _load_json(legacy_root / "calendar_privacy_ledger.json") or {}
    entradas = (ledger.get("entries") or {}) if isinstance(ledger, dict) else {}
    if not dry_run and entradas:
        with db.transaction():
            for event_id, entrada in entradas.items():
                db.execute(
                    """
                    INSERT OR REPLACE INTO calendar_privacy_ledger
                        (event_id, day, title, description, obfuscated_at, reason, applied)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        event_id, entrada.get("day", ""), entrada.get("title", ""),
                        entrada.get("description", ""),
                        entrada.get("obfuscated_at", ahora), entrada.get("reason", ""),
                        1 if entrada.get("applied") else 0,
                    ),
                )
    informe["ledger_calendar"] = len(entradas)

    # -------------------------------------------------------------- gmail
    gmail = _load_json(legacy_root / "gmail_bridge_state.json") or {}
    items = gmail.get("items") or []
    if not dry_run and items:
        with db.transaction():
            db.execute("DELETE FROM gmail_session")
            for item in items:
                db.execute(
                    """
                    INSERT OR REPLACE INTO gmail_session
                        (n, message_id, sender, subject, date, created_at)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (int(item.get("n", 0)), item.get("id", ""), item.get("from"),
                     item.get("subject"), item.get("date"), ahora),
                )
    informe["gmail_items"] = len(items)

    return informe


def main() -> int:
    parser = argparse.ArgumentParser(description="Migra el legacy de Mástil a SQLite")
    parser.add_argument("--legacy-root", default="/opt/guardian-telegram")
    parser.add_argument("--dry-run", action="store_true",
                        help="informa qué se migraría, sin escribir nada")
    args = parser.parse_args()

    legacy_root = Path(args.legacy_root)
    if not legacy_root.exists():
        print(f"No existe {legacy_root}")
        return 1

    cfg = config_module.load()
    db = open_database(cfg)

    print(f"Legacy : {legacy_root}")
    print(f"Destino: {cfg.db_path}")
    if args.dry_run:
        print("MODO SIMULACIÓN: no se escribe nada.\n")

    informe = migrate(legacy_root, db, cfg, args.dry_run)

    print()
    for clave, valor in informe.items():
        print(f"  {clave:22s} {valor}")

    if not args.dry_run:
        total = db.one("SELECT COUNT(*) AS c FROM lite_reminders")["c"]
        print(f"\n  recordatorios en destino: {total}")

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
