#!/usr/bin/env python3
"""Respaldo consistente de mastil.db.

    python3 scripts/backup_database.py
    python3 scripts/backup_database.py --dest /ruta --keep 14

Usa la API `backup` de SQLite, que toma una copia coherente aunque Mástil esté
corriendo y escribiendo. Copiar el archivo a mano mientras hay un WAL abierto
puede dejar un respaldo corrupto justo cuando más se necesita.

El respaldo incluye los recordatorios cifrados de la usuaria asistida. La llave vive aparte, en
data/lite_secret.key: sin ella el respaldo es ilegible. Respaldar las dos cosas
juntas anula el cifrado; respaldar sólo la base pierde el contenido. Elegí a
conciencia dónde guarda cada una.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as config_module           # noqa: E402


def main() -> int:
    cfg = config_module.load()

    parser = argparse.ArgumentParser(description="Respalda la base de Mástil")
    parser.add_argument("--dest", default=str(cfg.root / "data" / "backups"))
    parser.add_argument("--keep", type=int, default=14,
                        help="cuántos respaldos conservar (0 = todos)")
    args = parser.parse_args()

    if not cfg.db_path.exists():
        print(f"No existe la base {cfg.db_path}")
        return 1

    destino = Path(args.dest)
    destino.mkdir(parents=True, exist_ok=True)

    marca = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    salida = destino / f"mastil-{marca}.db"

    origen = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True)
    copia = sqlite3.connect(str(salida))
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()

    salida.chmod(0o600)

    verificacion = sqlite3.connect(str(salida))
    estado = verificacion.execute("PRAGMA integrity_check").fetchone()[0]
    total = verificacion.execute("SELECT COUNT(*) FROM lite_reminders").fetchone()[0]
    verificacion.close()

    print(f"respaldo      : {salida}")
    print(f"bytes         : {salida.stat().st_size}")
    print(f"integridad    : {estado}")
    print(f"recordatorios : {total}")

    if estado != "ok":
        print("\n¡El respaldo NO pasó la verificación de integridad!")
        return 1

    if args.keep > 0:
        respaldos = sorted(destino.glob("mastil-*.db"))
        for viejo in respaldos[:-args.keep]:
            viejo.unlink()
            print(f"borrado       : {viejo.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
