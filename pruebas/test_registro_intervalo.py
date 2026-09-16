"""Registro diario del intervalo configurado. Auto-registro, nunca racha."""

import os, sys, dataclasses
from pathlib import Path
from datetime import datetime, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import core.scheduler as sched
import modules.system as S
import modules.intervalos as I
from database import Database
from modules.system import SystemModule

# ------------------------------------------------------------- reloj falso
BASE = datetime.now().astimezone().replace(hour=1, minute=0, second=0, microsecond=0)
RELOJ = {"t": BASE}
def ahora(): return RELOJ["t"]
def avanzar(**kw): RELOJ["t"] = RELOJ["t"] + timedelta(**kw)
sched.now_local = ahora
S.now_local = ahora

TMP = Path(os.environ["TEMP"]) / "registro_int" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
LOG = TMP.parent / S.REGISTRO_ARCHIVO
cfg = dataclasses.replace(cm.load(), owner_chat_id="999", db_path=TMP)

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

class Nada:
    enabled = False
    def __getattr__(s, n): return lambda *a, **k: False

db = None
def limpiar():
    global db
    if db: db.close()
    TMP.unlink(missing_ok=True)
    LOG.unlink(missing_ok=True)
    RELOJ["t"] = BASE
    db = Database(cfg.db_path, cfg.schema_path); db.migrate()
    return SystemModule(cfg, db, Nada(), Nada())

def todas_las_lineas():
    return LOG.read_text(encoding="utf-8").splitlines() if LOG.exists() else []


def lineas():
    """Solo las lineas del registro del intervalo.

    Desde `ff1f2cb` el archivo tambien anota los contextos voluntarios del
    marcaje, asi que un dia ya no es una linea. Esta suite cuida el registro
    del intervalo; el resto del archivo se revisa igual en la prueba de las
    palabras prohibidas, que mira el texto completo.
    """
    return [l for l in todas_las_lineas() if "intervalo =" in l]

def dia_completo(sis, valor=None):
    """Las cuatro muestras de un dia, una por franja de seis horas."""
    if valor is not None:
        I.ESPERA_MINUTOS = valor
    for franja in range(4):
        RELOJ["t"] = RELOJ["t"].replace(hour=franja * 6 + 1)
        sis.tick()

ORIGINAL = I.ESPERA_MINUTOS

print("=== 1. toma cuatro muestras al dia, no mas ===")
sis = limpiar()
dia_completo(sis, 60)
ok(len(db.get_state(S.REGISTRO_MUESTRAS_KEY)) == 4, "cuatro muestras")
for _ in range(6):
    sis.tick()
ok(len(db.get_state(S.REGISTRO_MUESTRAS_KEY)) == 4, "y no suma mas por tickear seguido")
ok(not lineas(), "todavia no escribe: el dia no termino")

print("\n=== 1b. arrancar a media tarde NO rellena las franjas pasadas ===")
sis_t = limpiar()
RELOJ["t"] = BASE.replace(hour=14)          # franja 2, media tarde
for _ in range(5):
    sis_t.tick()
m = db.get_state(S.REGISTRO_MUESTRAS_KEY)
ok(len(m) == 1, f"una sola muestra, no tres de golpe ({m})")
ok(m[0][0] == 2, "y queda anotada en su franja real")
RELOJ["t"] = BASE.replace(hour=20)          # franja 3
sis_t.tick()
ok(len(db.get_state(S.REGISTRO_MUESTRAS_KEY)) == 2, "la franja siguiente si suma")

sis = limpiar()
dia_completo(sis, 60)

print("\n=== 2. al cambiar de dia, cierra el anterior ===")
avanzar(days=1); sis.tick()
ls = lineas()
ok(len(ls) == 1, f"una linea ({len(ls)})")
ok("= intervalo = 60 min" in ls[0], f"con el valor configurado: {ls[0]}")
ok(BASE.strftime("%d/%m/%Y") in ls[0], "y la fecha del dia que cerro")

print("\n=== 3. cuenta los dias en el mismo valor ===")
for _ in range(3):
    dia_completo(sis, 60); avanzar(days=1); sis.tick()
ls = lineas()
ok(len(ls) == 4, f"cuatro dias registrados ({len(ls)})")
ok("(día 4 en este valor)" in ls[-1], f"y el cuarto lo dice: {ls[-1]}")

print("\n=== 4. NUNCA lo llama racha ===")
texto = " ".join(todas_las_lineas()).lower()
ok("racha" not in texto, "la palabra 'racha' no aparece")
ok("perdiste" not in texto and "rompiste" not in texto, "ni nada que suene a fracaso")
ok("día" in texto and "en este valor" in texto, "es un hecho: 'día N en este valor'")

print("\n=== 5. un cambio se dice, NO se promedia ===")
# El dia cambia a mitad: dos muestras en 60 y dos en 45.
I.ESPERA_MINUTOS = 60
for franja in (0, 1):
    RELOJ["t"] = RELOJ["t"].replace(hour=franja * 6 + 1); sis.tick()
I.ESPERA_MINUTOS = 45
for franja in (2, 3):
    RELOJ["t"] = RELOJ["t"].replace(hour=franja * 6 + 1); sis.tick()
avanzar(days=1); sis.tick()
ultima = lineas()[-1]
ok("45 min" in ultima, "queda el valor con que termino el dia")
ok("cambió durante el día" in ultima, f"y avisa que cambio: {ultima}")
ok("60 min" in ultima, "diciendo cual era antes")
ok("(día" not in ultima, "sin contar dias: ese dia no tuvo un valor unico")

print("\n=== 6. tras el cambio, la cuenta arranca de nuevo ===")
dia_completo(sis, 45); avanzar(days=1); sis.tick()
ok("(día 1 en este valor)" in lineas()[-1], f"dia 1 en 45: {lineas()[-1]}")
dia_completo(sis, 45); avanzar(days=1); sis.tick()
ok("(día 2 en este valor)" in lineas()[-1], "dia 2 en 45")

print("\n=== 7. no manda nada por Telegram ===")
pendientes = db.query("SELECT * FROM outbox WHERE sent_at IS NULL")
ok(not pendientes, f"la outbox sigue vacia ({len(pendientes)} filas)")

print("\n=== 8. el archivo vive junto a la base, con permisos propios ===")
ok(LOG.parent == TMP.parent, "en la misma carpeta que la base (data/)")
ok(LOG.name == "intervalo_diario.log", f"se llama {LOG.name}")
if os.name != "nt":
    ok(oct(LOG.stat().st_mode)[-3:] == "600", "y queda en 600")
else:
    ok(True, "(los permisos 600 se verifican en Linux, no en Windows)")

print("\n=== 9. registra la CONFIGURACION, no la conducta ===")
sis2 = limpiar()
I.ESPERA_MINUTOS = 76
ok(sis2._intervalo_configurado() == 76, "lee la constante tal cual")
db.execute("INSERT INTO interval_marks(user_id, marked_at_utc, local_day, request_id) "
           "VALUES ('999', ?, '2026-01-01', 'x1')", (sched.iso(ahora()),))
ok(sis2._intervalo_configurado() == 76, "y no la afecta ninguna marca real")

print("\n=== 10. sobrevive al reinicio del proceso ===")
sis3 = limpiar()
dia_completo(sis3, 60)
sis4 = SystemModule(cfg, db, Nada(), Nada())   # instancia nueva, misma base
avanzar(days=1); sis4.tick()
ok(len(lineas()) == 1, "el dia se cierra igual tras reiniciar")
ok("60 min" in lineas()[0], "sin perder las muestras que ya habia")

I.ESPERA_MINUTOS = ORIGINAL
db.close()
TMP.unlink(missing_ok=True)
LOG.unlink(missing_ok=True)
print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
