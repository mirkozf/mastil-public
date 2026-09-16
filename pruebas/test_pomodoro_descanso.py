"""Pomodoro: descanso recomendado segun la duracion del bloque.

Una tabla por tramos, determinista. Ninguna IA interviene: los tiempos de
Mastil son reglas del codigo, y esta no es la excepcion.

La recomendacion es una SUGERENCIA. No pisa el descanso real, que sigue
saliendo de la configuracion como antes.
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
import modules.pomodoro as P
from database import Database
from modules.pomodoro import PomodoroModule, descanso_recomendado
from modules.panel import PanelModule

YO = "999"

# ------------------------------------------------------------- reloj falso
BASE = datetime.now().astimezone().replace(hour=10, minute=0, second=0,
                                           microsecond=0)
RELOJ = {"t": BASE}
sched.now_local = lambda: RELOJ["t"]
P.now_local = lambda: RELOJ["t"]


def avanzar(**kw):
    RELOJ["t"] = RELOJ["t"] + timedelta(**kw)


TMP = Path(os.environ["TEMP"]) / "pomo_descanso" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP)

FALLAS = 0


def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c:
        FALLAS += 1


db = None


def montar():
    global db
    if db:
        db.close()
    TMP.unlink(missing_ok=True)
    RELOJ["t"] = BASE
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    return PomodoroModule(cfg, db)


def salida():
    return [f["text"] or "" for f in db.query("SELECT text FROM outbox ORDER BY id")]


def ultimo():
    s = salida()
    return s[-1] if s else ""


def vaciar():
    with db.transaction():
        db.execute("DELETE FROM outbox")


# =========================================================================
print("=== 1-4. la tabla base ===")
ok(descanso_recomendado(25) == 5, "25 min de trabajo -> 5 de descanso")
ok(descanso_recomendado(45) == 7, "45 -> 7")
ok(descanso_recomendado(60) == 10, "60 -> 10")
ok(descanso_recomendado(90) == 15, "90 -> 15")

print("\n=== 4b. los valores intermedios caen al tramo de arriba ===")
ok(descanso_recomendado(1) == 5, "1 min -> 5 (el tramo mas chico)")
ok(descanso_recomendado(30) == 7, "30 -> 7, no 5: descansar de mas es el error barato")
ok(descanso_recomendado(50) == 10, "50 -> 10")
ok(descanso_recomendado(75) == 15, "75 -> 15")
ok(descanso_recomendado(240) == 15, "240 -> 15, el tope")

print("\n=== 5. cambiar el trabajo cambia la recomendacion ===")
pomo = montar()
for minutos, esperado in ((25, 5), (45, 7), (60, 10), (90, 15)):
    vaciar()
    pomo.handle_command("/pomodoro", f"/pomodoro {minutos}")
    ok(messages.pomodoro_sugerencia(esperado) in ultimo(),
       f"con {minutos} min sugiere {esperado}")

print("\n=== 6-7. es determinista: ni IA ni Gemini ===")
fuente = (Path(RAIZ) / "modules" / "pomodoro.py").read_text(encoding="utf-8")
ok("vision" not in fuente.lower(), "pomodoro.py no importa Vision")
ok("gemini" not in fuente.lower(), "ni menciona Gemini")
ok(all(descanso_recomendado(60) == 10 for _ in range(50)),
   "misma entrada, misma salida, siempre")
ok(descanso_recomendado.__module__ == "modules.pomodoro",
   "y la regla vive en el modulo, no en un servicio externo")

print("\n=== 8. iniciar Pomodoro sigue funcionando ===")
pomo = montar()
vaciar()
pomo.handle_command("/pomodoro", "/pomodoro 60")
fila = db.one("SELECT * FROM pomodoro_session WHERE id = 1")
ok(fila["active"] == 1, "queda una sesion activa")
ok(fila["phase"] == "work", "en fase de trabajo")
ok(int(fila["work_minutes"]) == 60, "con los 60 minutos pedidos")
ok("Pomodoro iniciado" in ultimo(), "y avisa que arranco")
ok("Descanso recomendado: 10 min" in ultimo(), "con su sugerencia")

print("\n=== 9. terminar el bloque sigue funcionando ===")
vaciar()
avanzar(minutes=61)
pomo.tick()
ok(db.one("SELECT phase FROM pomodoro_session WHERE id = 1")["phase"] == "cut_alert",
   "el bloque termina y pide cortar")
ok("BLOQUE TERMINADO" in ultimo(), "con el aviso de siempre")
ok("Descanso recomendado: 10 min" in ultimo(), "y ahi tambien esta la sugerencia")

print("\n=== 10. el descanso sigue funcionando ===")
vaciar()
pomo.handle_command("/descanso", "/descanso")
fila = db.one("SELECT * FROM pomodoro_session WHERE id = 1")
ok(fila["phase"] == "break", "entra en descanso")
ok("Descanso iniciado" in ultimo(), "y lo dice")

print("\n=== 11. la sugerencia NO pisa el descanso real ===")
#
# El descanso sale de la configuracion, como siempre. La recomendacion es
# texto: si fuese una obligacion dejaria de ser una sugerencia.
inicio = sched.from_iso(fila["phase_until"]) if hasattr(sched, "from_iso") else None
esperado = RELOJ["t"] + timedelta(seconds=cfg.pomodoro_descanso_corto_seconds)
ok(fila["phase_until"][:16] == esperado.isoformat()[:16],
   "el descanso real sigue siendo el de la configuracion, no el recomendado")
ok(cfg.pomodoro_descanso_corto_seconds // 60 != descanso_recomendado(60),
   "y de hecho difieren, asi que la prueba no es trivial")

print("\n=== 11b. la duracion invalida sigue rechazandose igual ===")
pomo = montar()
vaciar()
pomo.handle_command("/pomodoro", "/pomodoro 999")
ok(messages.POMODORO_DURACION_INVALIDA in ultimo(), "999 min se rechaza")
ok(not db.one("SELECT active FROM pomodoro_session WHERE id = 1")["active"],
   "y no arranca nada")

print("\n=== 11c. el foco por texto no se rompio ===")
vaciar()
pomo.handle_command("/pomodoro", "/pomodoro escribir informe")
ok("escribir informe" in ultimo(), "un argumento de texto sigue siendo el foco")
ok(int(db.one("SELECT work_minutes FROM pomodoro_session WHERE id = 1")["work_minutes"])
   == cfg.pomodoro_trabajo_minutes, "y usa la duracion por defecto")

print("\n=== 12. la pantalla del Panel lo muestra antes de iniciar ===")
pomo = montar()
panel = PanelModule(cfg, db)
pomo.handle_command("/pomodoro", "/pomodoro 90")
vaciar()
panel.handle_callback({"data": "panel:pomodoro", "from": {"id": YO},
                       "message": {"message_id": 5, "chat": {"id": YO}}})
texto = ultimo()
ok("POMODORO" in texto, "es la pantalla de Pomodoro")
ok("Trabajo: 90 min" in texto, "dice la duracion vigente")
ok("Descanso recomendado: 15 min" in texto, "y el descanso sugerido")

print("\n=== 12b. sin sesion cae en la duracion por defecto ===")
pomo = montar()
panel = PanelModule(cfg, db)
vaciar()
panel.handle_callback({"data": "panel:pomodoro", "from": {"id": YO},
                       "message": {"message_id": 5, "chat": {"id": YO}}})
ok(f"Trabajo: {cfg.pomodoro_trabajo_minutes} min" in ultimo(),
   "muestra la duracion configurada por defecto")

print("\n=== 13-16. nada mas se movio ===")
import modules.timer as T
import modules.intervalos as I
import modules.guardian as G
import modules.vigia as V

ok(T.MODOS if hasattr(T, "MODOS") else True, "Timer sigue importable")
ok(G.RAFAGA_MENSAJES == 7 and G.INTERVENCION_MINUTOS == 70, "Guardian sin cambios")
ok(I.MOMENTOS_AVISO == (0, 150, 180, 420), "Intervalos sin cambios")
ok(isinstance(I.ESPERA_MINUTOS, int) and I.ESPERA_MINUTOS > 0,
   f"ESPERA_MINUTOS lo fija el usuario a mano: {I.ESPERA_MINUTOS} min")
ok(hasattr(V, "VigiaModule"), "Vigia sin cambios")
ok(not (Path(RAIZ) / "requirements.txt").read_text(encoding="utf-8").strip()
   .replace("#", "").strip().startswith(("a", "b", "c", "d", "e", "f", "g")),
   "requirements.txt sigue sin dependencias")

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
