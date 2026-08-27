#!/usr/bin/env python3
"""Punto de entrada de Mástil.

    python3 main.py            # corre el ciclo
    python3 main.py --once     # una sola vuelta, para probar sin quedarse
    python3 main.py --check    # valida configuración y base, no toca Telegram
"""

from __future__ import annotations

import argparse
import sys

import config as config_module
import core.scheduler as scheduler
from database import open_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mástil")
    parser.add_argument("--once", action="store_true",
                        help="una sola iteración del ciclo")
    parser.add_argument("--check", action="store_true",
                        help="valida config y esquema sin conectarse a Telegram")
    args = parser.parse_args(argv)

    cfg = config_module.load()
    # Antes que nada: en qué zona piensa este proceso. Sin esto, el mismo
    # código agenda horas distintas en cada máquina.
    scheduler.set_timezone(cfg.timezone)
    db = open_database(cfg)

    if args.check:
        print(f"zona horaria    : {cfg.timezone} -> "
              f"{scheduler.now_local():%Y-%m-%d %H:%M %Z}")
        print(f"base            : {cfg.db_path}")
        print(f"evidencia       : {cfg.evidence_dir}")
        print(f"usuarias Lite   : {len(cfg.lite_users)}")
        print(f"Calendar escribe: {'sí' if cfg.calendar_bridge_enabled else 'no (inerte)'}")
        print(f"Gmail           : {'sí' if cfg.gmail_enabled else 'no'}")
        print(f"Vision          : {'sí' if cfg.vision_enabled else 'no'}")
        tablas = [
            row["name"] for row in db.query(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        print(f"tablas          : {len(tablas)} -> {', '.join(tablas)}")
        db.close()
        return 0

    config_module.require(cfg)

    # El import es tardío a propósito: --check debe funcionar aunque falte
    # cualquier credencial.
    from core.runtime import Runtime

    runtime = Runtime(cfg, db)
    try:
        if args.once:
            runtime.boot()
            runtime.run_once()
        else:
            runtime.run_forever()
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
