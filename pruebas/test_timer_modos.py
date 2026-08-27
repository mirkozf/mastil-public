"""Tres modalidades sobre un solo motor de timer. Reloj falso: ningun sleep."""

import os, sys, dataclasses, json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

RAIZ = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import messages
import core.scheduler as sched
import modules.timer as T
from database import Database
from modules.timer import TimerModule, COUNTDOWN, FIXED, REPEATING

# ------------------------------------------------------------- reloj falso
BASE = datetime.now().astimezone().replace(hour=20, minute=0, second=0, microsecond=0)
RELOJ = {"t": BASE}
def ahora(): return RELOJ["t"]
def avanzar(**kw): RELOJ["t"] = RELOJ["t"] + timedelta(**kw)
_RELOJ_REAL = sched.now_local          # para probar la zona de verdad
sched.now_local = ahora
T.now_local = ahora

TMP = Path(os.environ["TEMP"]) / "timer_modos.db"
cfg = dataclasses.replace(cm.load(), owner_chat_id="999", db_path=TMP)

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

db = None
def limpiar():
    global db
    if db: db.close()
    TMP.unlink(missing_ok=True)
    RELOJ["t"] = BASE
    db = Database(cfg.db_path, cfg.schema_path); db.migrate()
    return TimerModule(cfg, db)

def filas():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL")
    return f

def out():
    return " ".join((x["text"] or "") for x in filas())

def botones():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    salida = []
    for x in f:
        if x["buttons"]:
            salida += [b[1] for b in json.loads(x["buttons"])]
    return salida

def fila():
    return db.one("SELECT * FROM timer WHERE id = 1")

def cmd(t, texto):
    return t.handle_command(texto.split()[0], texto)


print("=== 1-3. countdown: se crea y queda activo ===")
t = limpiar()
cmd(t, "/timer 30 ir a comer")
txt = out()
f = fila()
ok(f["active"] == 1 and f["modo"] == COUNTDOWN, "queda activo en modo cuenta atras")
ok("Cuenta atr" in txt, f"lo dice en el mensaje")
ok(sched.from_iso(f["ends_at"]) == BASE + timedelta(minutes=30), "termina en 30 min exactos")
ok(f["reason"] == "ir a comer", "conserva la razon")

print("\n=== 4-5. countdown llega a cero y suena ===")
avanzar(minutes=29); t.tick()
ok(not out(), "a los 29 no suena")
avanzar(minutes=1); t.tick()
ok("Timer terminado" in out(), "a los 30 suena")
ok(fila()["status"] == "ringing", "queda sonando, como siempre")
cmd(t, "/apagar")
ok(fila()["active"] == 0, "y /apagar lo deja sin timer activo")

print("\n=== 6-7. avisar a: se crea con la hora ===")
t = limpiar()
cmd(t, "/timer_a 21:40")
txt = out()
f = fila()
ok(f["active"] == 1 and f["modo"] == FIXED, "queda activo en modo avisar a")
objetivo = BASE.replace(hour=21, minute=40, second=0)
ok(sched.from_iso(f["ends_at"]) == objetivo, "apunta a las 21:40 de hoy")
ok("21:40" in txt, "lo confirma con la hora")

print("\n=== 8. avisar a dispara UNA sola vez y termina ===")
avanzar(hours=1, minutes=39); t.tick()
ok(not out(), "un minuto antes no dispara")
avanzar(minutes=1); t.tick()
txt = out()
ok("21:40" in txt, "a la hora avisa")
ok(fila()["active"] == 0, "y queda SIN timer activo")
t.tick(); t.tick()
ok(not out(), "no vuelve a avisar nunca")

print("\n=== 9. avisar a NO se convierte en Calendar ===")
t = limpiar()
cmd(t, "/timer_a 07:30 reunion con el equipo en la oficina")
f = fila()
ok(f["active"] == 1, "acepta la hora")
ok(f["reason"] == "", "y descarta todo lo demas: no guarda titulo")
ok(f["duration_minutes"] == 0 and f["interval_minutes"] == 0, "sin duracion ni recurrencia")
ok(db.one("SELECT COUNT(*) c FROM calendar_command_requests")["c"] == 0,
   "no toca Calendar")

print("\n=== la hora que ya paso es la de manana ===")
t = limpiar()
cmd(t, "/timer_a 19:00")           # el reloj esta en 20:00
ok(sched.from_iso(fila()["ends_at"]) == BASE.replace(hour=19, minute=0) + timedelta(days=1),
   "19:00 con reloj en 20:00 queda para manana")
cmd(t, "/timer_a 99:99"); cmd(t, "/timer_conservar")
ok(messages.TIMER_HORA_INVALIDA in out(), "una hora imposible se rechaza")

print("\n=== 10-13. repetitivo: crea y reprograma ===")
t = limpiar()
cmd(t, "/timer_cada 50")
f = fila()
ok(f["active"] == 1 and f["modo"] == REPEATING, "queda activo en modo repetitivo")
ok(f["interval_minutes"] == 50, "guarda el periodo")
primero = BASE + timedelta(minutes=50)
ok(sched.from_iso(f["ends_at"]) == primero, "primer aviso a los 50 min")
avanzar(minutes=50); t.tick()
ok("50 minutos" in out(), "avisa")
ok(sched.from_iso(fila()["ends_at"]) == primero + timedelta(minutes=50),
   "y ya dejo programado el siguiente")
ok(fila()["active"] == 1, "sigue activo")

print("\n=== 14. repite varias veces sin encadenar timers ===")
avisos = 0
for _ in range(3):
    avanzar(minutes=50); t.tick()
    if "50 minutos" in out(): avisos += 1
ok(avisos == 3, f"aviso las tres veces ({avisos})")
ok(db.one("SELECT COUNT(*) c FROM timer")["c"] == 1, "y sigue habiendo UNA sola fila")

print("\n=== 14b. el repetitivo VENCE solo y ofrece relanzarlo ===")
t = limpiar()
cmd(t, "/timer_cada 30 60")        # cada 30 min, por 1 hora
ok(fila()["duration_minutes"] == 60, "guarda el tope elegido")
out()
avanzar(minutes=30); t.tick()
fs = filas()
ok(any("30 minutos" in (x["text"] or "") for x in fs), "primer aviso")
ok([b[1] for x in fs if x["buttons"] for b in json.loads(x["buttons"])] == ["/timer_cancelar"],
   "y trae UN solo boton: detener")
avanzar(minutes=30); t.tick()
fs = filas()
txt = " ".join((x["text"] or "") for x in fs)
ok("Dej" in txt and "de avisar" in txt, "al cumplirse la hora, avisa que termina")
ok(fila()["active"] == 0, "y queda sin timer activo")
datos = [b[1] for x in fs if x["buttons"] for b in json.loads(x["buttons"])]
ok("/timer_cada 30 60" in datos, f"con OTRA VEZ igual configurado ({datos})")
for _ in range(3):
    avanzar(minutes=30); t.tick()
ok(not out(), "y no vuelve a avisar nunca")

print("\n=== 14c. el tope corta a la hora pedida, no en el siguiente multiplo ===")
t = limpiar()
cmd(t, "/timer_cada 45 60"); out()   # 45 no divide a 60
avanzar(minutes=45); t.tick(); out()
avanzar(minutes=15); t.tick()        # minuto 60 exacto
ok("de avisar" in out(), "termina en el minuto 60, sin esperar al 90")

print("\n=== 14d. no existe el repetitivo eterno ===")
t = limpiar()
cmd(t, "/timer_cada 10 99999"); out()
ok(fila()["duration_minutes"] == T.TOPE_MAXIMO,
   f"un tope absurdo se recorta a la jornada ({fila()['duration_minutes']})")

print("\n=== 15. detener el repetitivo corta el ciclo entero ===")
cmd(t, "/timer_cancelar"); out()
ok(fila()["active"] == 0, "queda sin timer activo")
for _ in range(3):
    avanzar(minutes=50); t.tick()
ok(not out(), "y no vuelve a avisar")

print("\n=== 16. detener cualquier modo limpia el estado ===")
for texto in ("/timer 20", "/timer_a 23:00", "/timer_cada 15"):
    t = limpiar()
    cmd(t, texto); out()
    cmd(t, "/timer_cancelar"); out()
    f = fila()
    ok(f["active"] == 0 and f["interval_minutes"] == 0 and not f["ends_at"],
       f"{texto.split()[0]} -> estado limpio")

print("\n=== 17-19. un solo timer activo: REEMPLAZAR / CONSERVAR ===")
t = limpiar()
cmd(t, "/timer 30"); out()
antes = fila()["ends_at"]
cmd(t, "/timer_cada 50")
txt = out()
ok(messages.TIMER_YA_HAY in txt, "avisa que ya hay uno")
ok(fila()["modo"] == COUNTDOWN and fila()["ends_at"] == antes,
   "y NO toca el que estaba mientras no respondas")
cmd(t, "/timer_conservar")
ok(messages.TIMER_CONSERVADO in out(), "CONSERVAR lo dice")
ok(fila()["modo"] == COUNTDOWN and fila()["ends_at"] == antes,
   "y deja intacto el anterior")
cmd(t, "/timer_cada 50"); out()
cmd(t, "/timer_reemplazar"); out()
f = fila()
ok(f["modo"] == REPEATING and f["interval_minutes"] == 50, "REEMPLAZAR crea el nuevo")
ok(json.loads(f["milestones"] or "[]") == [], "y no deja restos del anterior")
ok(f["duration_minutes"] == T.TOPE_POR_DEFECTO,
   f"sin tope explicito usa el de por defecto ({f['duration_minutes']})")
ok(db.one("SELECT COUNT(*) c FROM timer WHERE active=1")["c"] == 1, "sigue habiendo uno solo")
cmd(t, "/timer_reemplazar")
ok(messages.TIMER_NADA_QUE_REEMPLAZAR in out(), "reemplazar sin nada pendiente avisa")

print("\n=== 20-25. reinicio del proceso ===")
t = limpiar()
cmd(t, "/timer 40"); out()
t2 = TimerModule(cfg, db)          # instancia nueva, misma base
ok(sched.from_iso(fila()["ends_at"]) == BASE + timedelta(minutes=40),
   "countdown recupera su hora objetivo")
avanzar(minutes=40); t2.tick()
ok("Timer terminado" in out(), "y suena cuando corresponde")
ok(db.one("SELECT COUNT(*) c FROM timer")["c"] == 1, "sin duplicar timers")

t = limpiar()
cmd(t, "/timer_a 23:30"); out()
t2 = TimerModule(cfg, db)
ok(sched.from_iso(fila()["ends_at"]) == BASE.replace(hour=23, minute=30),
   "fixed recupera la hora exacta")

t = limpiar()
cmd(t, "/timer_cada 30"); out()
t2 = TimerModule(cfg, db)
ok(sched.from_iso(fila()["ends_at"]) == BASE + timedelta(minutes=30),
   "repeating recupera el proximo aviso")

print("\n=== un apagon largo no dispara una rafaga de atrasados ===")
avanzar(hours=3)                    # se perdieron 6 periodos de 30 min
t2.tick()
disparos = out().count("30 minutos")
ok(disparos == 1, f"avisa UNA vez, no seis ({disparos})")
prox = sched.from_iso(fila()["ends_at"])
ok(prox > ahora(), "y el proximo queda en el futuro")
t2.tick()
ok(not out(), "sin repetir de inmediato")

print("\n=== la zona horaria sale de la config, no de la maquina ===")
# El bug que esto habria cachado: en un servidor en UTC, "avisar a las 21:40"
# agendaba las 21:40 UTC. En el equipo del dueno funcionaba porque ahi la zona
# del sistema ya era la correcta.
sched.now_local = _RELOJ_REAL
try:
    ZoneInfo("America/Santiago"); hay_zonas = True
except Exception:
    hay_zonas = False        # Windows no trae la base IANA

sched.set_timezone("America/Santiago")
if hay_zonas:
    off = sched.now_local().utcoffset()
    ok(off in (timedelta(hours=-4), timedelta(hours=-3)),
       f"con America/Santiago piensa en Chile ({off})")
    guardado_en_utc = datetime(2026, 8, 26, 23, 40, tzinfo=timezone.utc)
    ok(sched.clock(guardado_en_utc) in ("19:40", "20:40"),
       f"una hora guardada en UTC se MUESTRA en Chile ({sched.clock(guardado_en_utc)})")
    sched.set_timezone("Etc/UTC")
    ok(sched.now_local().utcoffset() == timedelta(0),
       "y en UTC si asi se configura: la zona manda, no la maquina")
else:
    ok(sched.now_local() is not None,
       "sin base de zonas cae a la del sistema, sin romperse")
    ok(sched.timezone_actual() is None, "y lo deja explicito")
    ok(True, "(zona IANA no disponible: la asercion fuerte corre en Linux)")
sched.set_timezone(None)
sched.now_local = ahora
ok(sched.timezone_actual() is None, "y se puede volver a la del sistema")

print("\n=== 26-27. nada nuevo y nada roto ===")
req = Path(RAIZ, "requirements.txt").read_text(encoding="utf-8")
ok(all(l.strip().startswith("#") or not l.strip() for l in req.splitlines()),
   "requirements.txt sigue sin dependencias")
import modules.guardian as G, modules.intervalos as I
ok(G.RAFAGA_MENSAJES == 7 and G.INTERVENCION_MINUTOS == 70, "Guardian sin cambios")
ok(I.ESPERA_MINUTOS == 76, "Intervalos sin cambios")
ok(hasattr(T.TimerModule, "pause") and hasattr(T.TimerModule, "resume"),
   "pausa y reanudacion siguen existiendo")

print("\n=== pausar sigue siendo solo de la cuenta atras ===")
t = limpiar()
cmd(t, "/timer 30"); out()
cmd(t, "/timer_pausar")
ok(fila()["status"] == "paused", "countdown si se pausa")
cmd(t, "/timer_cancelar"); out()
cmd(t, "/timer_cada 20"); out()
cmd(t, "/timer_pausar")
ok(messages.TIMER_PAUSA_SOLO_CUENTA in out(), "repetitivo no")
ok(fila()["status"] == "running", "y sigue corriendo")

db.close()
TMP.unlink(missing_ok=True)
print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
