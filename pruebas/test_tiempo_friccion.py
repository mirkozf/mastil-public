"""/tiempo: consulta directa desde la última marca."""
import dataclasses
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(
    MASTIL_TELEGRAM_BOT_TOKEN="0:t",
    MASTIL_OWNER_CHAT_ID="999",
    MASTIL_ICAL_URL="https://x.invalid/a.ics",
    MASTIL_TIMEZONE="UTC",
)

import config as cm
import messages
import modules.intervalos as I
from core.router import Router
from database import Database
from modules.intervalos import (
    ESPERA_MINUTOS,
    HORAS_CIERRE,
    MAX_FILAS,
    MOMENTOS_AVISO,
    IntervalosModule,
    formato_duracion,
)

I.ZoneInfo = lambda _: timezone.utc

YO = "999"
TMP = Path(os.environ["TEMP"]) / "tiempo_directo.db"
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP)
FALLAS = 0


def ok(condicion, texto):
    global FALLAS
    print(f"  {'ok  ' if condicion else 'MAL '} {texto}")
    if not condicion:
        FALLAS += 1


class TG:
    def answer_callback(self, *args, **kwargs):
        pass

    def send_message(self, *args, **kwargs):
        return {"ok": True}


class Nada:
    enabled = False

    def __getattr__(self, _name):
        return lambda *args, **kwargs: False


db = None


def montar():
    global db, inter, router
    if db:
        db.close()
    TMP.unlink(missing_ok=True)
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    inter = IntervalosModule(cfg, db)
    modules = {"intervalos": inter}
    for nombre in ("panel", "vigia", "timer", "system", "pomodoro",
                   "gmail", "guardian", "calendar", "lite"):
        modules[nombre] = Nada()
    router = Router(cfg, db, TG(), modules)


def salida():
    filas = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL")
    return filas


def ultimo():
    filas = salida()
    return filas[-1] if filas else None


def es_tiempo(fila):
    return bool(fila) and "marca" in (fila["text"] or "").lower()


def tiene_friccion(fila):
    if not fila or not fila["buttons"]:
        return False
    botones = json.dumps(json.loads(fila["buttons"]))
    return "/tiempo_mostrar" in botones or "/tiempo_dejarlo" in botones


def marcar(numero):
    inter.handle("/marca", f"marca-{numero}")
    salida()


def tiempo():
    inter.handle("/tiempo", None)
    return ultimo()


print("=== primera consulta ===")
montar()
marcar(1)
fila = tiempo()
ok(es_tiempo(fila), "muestra el tiempo")
ok(not tiene_friccion(fila), "sin decisiones intermedias")

print("\n=== consultas repetidas ===")
for numero in range(1, 21):
    fila = tiempo()
    ok(es_tiempo(fila), f"consulta {numero}: tiempo directo")
    ok(not tiene_friccion(fila), f"consulta {numero}: sin friccion")

print("\n=== marca nueva y reinicio del modulo ===")
marcar(2)
ok(es_tiempo(tiempo()), "la marca nueva responde directo")
inter_reiniciado = IntervalosModule(cfg, db)
inter_reiniciado.handle("/tiempo", None)
ok(es_tiempo(ultimo()), "sigue directo tras reiniciar el modulo")

print("\n=== sin marcas ===")
montar()
fila = tiempo()
ok(messages.INTERVALOS_SIN_MARCAS in (fila["text"] or ""), "explica que faltan marcas")

print("\n=== router ===")
montar()
marcar(1)
router.process({
    "message": {"message_id": 1, "chat": {"id": YO}, "from": {"id": YO},
                "text": "/tiempo"}
})
ok(es_tiempo(ultimo()), "el router entrega el tiempo")
router.process({
    "message": {"message_id": 2, "chat": {"id": YO}, "from": {"id": YO},
                "text": "/tiempo"}
})
ok(es_tiempo(ultimo()), "el router repite el tiempo directo")

print("\n=== el resto del modulo ===")
ok(MOMENTOS_AVISO == (0, 150, 180, 420), f"avisos intactos {MOMENTOS_AVISO}")
ok(HORAS_CIERRE == 4 and MAX_FILAS == 10, "constantes intactas")
ok(isinstance(ESPERA_MINUTOS, int) and ESPERA_MINUTOS > 0,
   f"ESPERA_MINUTOS sigue en {ESPERA_MINUTOS} min")
ok(formato_duracion(3661) == "1h 01m 01s" and formato_duracion(0) == "00m 00s",
   "el calculo no cambia")

montar()
db.execute(
    "INSERT INTO interval_marks(user_id, marked_at_utc, local_day, request_id) "
    "VALUES (?,?,?,?)",
    (YO, (datetime.now(timezone.utc) - timedelta(minutes=ESPERA_MINUTOS + 5)).isoformat(),
     "2026-08-19", "viejo"),
)
inter.tick()
ok(any(messages.INTERVALOS_AVISO in (fila["text"] or "") for fila in salida()),
   "el aviso del intervalo sigue saliendo")
ok(es_tiempo(tiempo()), "y /tiempo sigue directo")

db.close()
TMP.unlink(missing_ok=True)
print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
