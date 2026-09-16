"""Cuenta regresiva: minutos, o minutos:segundos.

`7` sigue siendo siete minutos. `7:10` son siete minutos y diez segundos. La
diferencia la marca los dos puntos, y nada mas.

El fin exacto vive en `ends_at`; `duration_minutes` es el techo con el que se
validan los avisos, y por eso redondea hacia arriba.
"""

import os, sys, dataclasses
from pathlib import Path
from datetime import datetime, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import messages
import core.scheduler as sched
import modules.timer as T
from database import Database
from modules.timer import TimerModule, _segundos_de
from modules.panel import PanelModule

YO = "999"

# ------------------------------------------------------------- reloj falso
BASE = datetime.now().astimezone().replace(hour=10, minute=0, second=0,
                                           microsecond=0)
RELOJ = {"t": BASE}
sched.now_local = lambda: RELOJ["t"]
T.now_local = lambda: RELOJ["t"]

TMP = Path(os.environ["TEMP"]) / "timer_segundos" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP)

FALLAS = 0


def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c:
        FALLAS += 1


db = None
timer = None


def montar():
    global db, timer
    if db:
        db.close()
    TMP.unlink(missing_ok=True)
    RELOJ["t"] = BASE
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    return TimerModule(cfg, db)


def fila():
    return db.one("SELECT * FROM timer WHERE id = 1")


def dura_segundos():
    """Lo que de verdad va a durar: del arranque al fin."""
    f = fila()
    return int((sched.from_iso(f["ends_at"])
                - sched.from_iso(f["started_at"])).total_seconds())


def ultimo():
    filas = db.query("SELECT text FROM outbox ORDER BY id")
    return (filas[-1]["text"] or "") if filas else ""


def arrancar(texto):
    global timer
    timer = montar()
    timer.start(f"/timer {texto}")


# =========================================================================
print("=== 1. la lectura del valor ===")
ok(_segundos_de("4:20") == 260, "4:20 son 260 segundos")
ok(_segundos_de("3:20") == 200, "3:20 son 200")
ok(_segundos_de("7:10") == 430, "7:10 son 430")
ok(_segundos_de("0:30") == 30, "0:30 son 30")
ok(_segundos_de("4:5") == 245, "4:5 se entiende como 4 y 5 segundos")
ok(_segundos_de("4") is None, "un numero suelto NO son segundos: son minutos")
ok(_segundos_de("4:60") is None, "60 segundos no existen")
ok(_segundos_de("hola") is None, "y lo que no es hora, no se inventa")

print("\n=== 2. un numero suelto sigue siendo minutos ===")
for minutos in (1, 4, 5, 7, 30):
    arrancar(str(minutos))
    ok(dura_segundos() == minutos * 60, f"{minutos} -> {minutos} minutos")

print("\n=== 3. con dos puntos, minutos y segundos ===")
for texto, segundos in (("4:20", 260), ("3:20", 200), ("7:10", 430),
                        ("0:30", 30), ("1:05", 65)):
    arrancar(texto)
    ok(dura_segundos() == segundos, f"{texto} -> {segundos} segundos exactos")

print("\n=== 4. lo dice como lo escribiste ===")
arrancar("4:20")
ok("4:20 minutos" in ultimo(), f"4:20 se anuncia como 4:20 ({ultimo()[:40]}...)")
arrancar("7")
ok("7 minutos" in ultimo(), "7 se anuncia como 7 minutos")
arrancar("4:00")
ok("4 minutos" in ultimo(), "4:00 es redondo y se dice en minutos")
ok(dura_segundos() == 240, "y dura los 240 segundos")

print("\n=== 5. el techo redondea hacia arriba ===")
#
# `duration_minutes` es con lo que se validan los avisos: si 4:20 quedara en 4,
# un aviso a los 4 minutos seria imposible aunque el timer siga corriendo.
arrancar("4:20")
ok(int(fila()["duration_minutes"]) == 5, "4:20 deja el techo en 5")
ok(dura_segundos() == 260, "pero la duracion real sigue siendo 4:20")
arrancar("4")
ok(int(fila()["duration_minutes"]) == 4, "y un valor redondo no se toca")

print("\n=== 6. los avisos siguen siendo minutos ===")
timer = montar()
timer.start("/timer 10 3 7")
import json
ok(json.loads(fila()["milestones"]) == [3, 7], "los avisos se guardan igual")
ok(dura_segundos() == 600, "y la duracion no cambio")

timer = montar()
timer.start("/timer 5:30 2")
ok(json.loads(fila()["milestones"]) == [2], "tambien con M:SS")
ok(dura_segundos() == 330, "con su duracion exacta")

print("\n=== 7. la razon sigue funcionando ===")
timer = montar()
timer.start("/timer 4:20 sacar la ropa")
ok(fila()["reason"] == "sacar la ropa", "el texto despues del numero es la razon")
ok(dura_segundos() == 260, "y no se comio los segundos")

print("\n=== 8. lo invalido sigue rechazandose ===")
timer = montar()
timer.start("/timer 0:00")
ok(not fila()["active"], "0:00 no arranca nada")
timer = montar()
timer.start("/timer 0")
ok(not fila()["active"], "y 0 tampoco")
timer = montar()
timer.start("/timer 4:60")
ok(not fila()["active"], "4:60 no arranca")
timer = montar()
timer.start("/timer 2000")
ok(not fila()["active"], "ni una duracion fuera de tope")

print("\n=== 9. el timer suena cuando corresponde ===")
arrancar("4:20")
RELOJ["t"] = BASE + timedelta(seconds=259)
timer.tick()
ok(fila()["status"] == "running", "a los 259 segundos todavia corre")
RELOJ["t"] = BASE + timedelta(seconds=261)
timer.tick()
ok(fila()["status"] != "running", "y a los 261 ya vencio")

print("\n=== 9b. al terminar dice de cuanto era ===")
#
# "Timer terminado" a secas no decia cual: con varios en el dia, o uno largo,
# no se sabia que era lo que termino.
ok("Timer de 4:20 minutos terminado" in ultimo(),
   f"nombra la duracion tal como se pidio ({ultimo()[:40]})")
RELOJ["t"] = BASE + timedelta(seconds=261 + cfg.timer_alarma_cada_seconds)
timer.tick()
ok("Timer de 4:20 minutos terminado" in ultimo(), "y la alarma repetida tambien")

arrancar("1")
RELOJ["t"] = BASE + timedelta(seconds=61)
timer.tick()
ok("Timer de 1 minuto terminado" in ultimo(), "un minuto se dice en singular")

arrancar("10")
RELOJ["t"] = BASE + timedelta(minutes=3)
timer.pause()
RELOJ["t"] = BASE + timedelta(minutes=8)          # cinco minutos en pausa
timer.resume()
RELOJ["t"] = BASE + timedelta(minutes=15, seconds=1)
timer.tick()
ok(fila()["status"] == "ringing", "con la pausa descontada termina a los 15")
ok("Timer de 10 minutos terminado" in ultimo(),
   f"y dice los 10 pedidos, no los 15 que pasaron ({ultimo()[:40]})")

print("\n=== 10. el panel manda el valor tal cual ===")
db2 = Database(cfg.db_path, cfg.schema_path)
db2.migrate()
panel = PanelModule(cfg, db2)


class TimerFalso:
    # La pantalla del Timer le pregunta que hay corriendo.
    def resumen_actual(self):
        return ""


class RouterFalso:
    def __init__(self):
        self.comandos = []
        self.modules = {"timer": TimerFalso()}

    def handle_command(self, comando, source_id=None):
        self.comandos.append(comando)
        return True


router = RouterFalso()
panel.attach(router)
panel.handle_callback({"data": "panel:tm:otro", "from": {"id": YO},
                       "message": {"message_id": 7, "chat": {"id": YO}}})
panel.handle_text(YO, YO, "4:20")
ok(router.comandos[-1] == "/timer 4:20", "OTRO entrega el valor sin tocarlo")

print("\n=== 11. y la pantalla lo explica ===")
ok("7:10" in messages.PANEL_TIMER_OTRO, "el texto de OTRO muestra el formato")
db2.close()

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
