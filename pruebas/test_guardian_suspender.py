"""Suspension exclusiva de Guardian.

Apaga solo Guardian. Los eventos NO se borran, no se resuelven y no cambian de
hora: dejan de ser intervenidos, nada mas. Todo lo demas sigue tickeando.

Determinista: sin sleeps, sin red, base temporal que se borra sola.
"""

import os, sys, dataclasses
from pathlib import Path
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import messages
import core.runtime as R
from database import Database
from core.runtime import Runtime, GUARDIAN_SUSPENDED_KEY, SUSPENDED_KEY

YO = "999"

# `ZoneInfo("America/Santiago")` no existe en Windows: Python no trae la base
# IANA. Se reemplaza por un offset fijo en todos los modulos ya cargados, que
# ademas saca el horario de verano del medio y deja la suite determinista.
ZONA = timezone(timedelta(hours=-4))
for _mod in list(sys.modules.values()):
    if getattr(_mod, "__name__", "") != "zoneinfo" and hasattr(_mod, "ZoneInfo"):
        _mod.ZoneInfo = lambda nombre=None: ZONA

# El ICS no se descarga: el tick tiene que poder correr sin red y sin ruido.
EVENTOS = [{"titulo": "falso"}]
R.read_events = lambda *a, **k: list(EVENTOS)

TMP = Path(os.environ["TEMP"]) / "g_suspender" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
cfg = dataclasses.replace(
    cm.load(), owner_chat_id=YO, db_path=TMP,
    lite_secret_path=TMP.parent / "lite_secret.key",
)

FALLAS = 0


def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c:
        FALLAS += 1


class Espia:
    """Doble de modulo: cuenta cuantas veces le pidieron tick."""

    def __init__(self):
        self.ticks = 0
        self.eventos = None

    def tick(self, events=None):
        self.ticks += 1
        self.eventos = events


db = None
rt = None
espias = {}
SISTEMA = None


def montar():
    """Runtime real, con los modulos del tick reemplazados por espias."""
    global db, rt, espias, SISTEMA
    if db:
        db.close()
    TMP.unlink(missing_ok=True)
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    rt = Runtime(cfg, db)
    # El SystemModule real se conserva aparte: es el que atiende los comandos,
    # y su `attach` le dejo el Guardian REAL, que es quien sabe cortar una
    # rafaga. Los del tick son espias, para poder contarlos.
    SISTEMA = rt.modules["system"]
    espias = {}
    for nombre in ("vigia", "guardian", "pomodoro", "timer", "lite", "intervalos", "system"):
        espias[nombre] = Espia()
        rt.modules[nombre] = espias[nombre]


def sis():
    return SISTEMA


def salida(pendientes=False):
    sql = "SELECT * FROM outbox"
    if pendientes:
        sql += " WHERE sent_at IS NULL"
    return db.query(sql + " ORDER BY id")


def textos():
    return [f["text"] or "" for f in salida()]


def vaciar():
    with db.transaction():
        db.execute("DELETE FROM outbox")


def evento(event_id="ev1", phase="insiste"):
    """Una fila de Guardian, como la deja una intervencion en curso."""
    with db.transaction():
        marca = datetime.now().astimezone().isoformat()
        db.execute(
            "INSERT INTO guardian_events"
            "(event_id, title, start_at, phase, is_active, created_at) "
            "VALUES (?,?,?,?,1,?)",
            (event_id, "**algo", marca, phase, marca),
        )


def rafaga_programada(event_id="ev1"):
    """Los mensajes de una rafaga que todavia no salieron."""
    futuro = (datetime.now().astimezone() + timedelta(seconds=30)).isoformat()
    ahora = datetime.now(timezone.utc).isoformat()
    with db.transaction():
        for texto in messages.GUARDIAN_INSISTE[:3]:
            db.execute(
                "INSERT INTO outbox"
                "(chat_id, kind, text, flow_key, send_after, created_at) "
                "VALUES (?,'text',?,?,?,?)",
                (YO, texto, f"guardian:{event_id}", futuro, ahora),
            )


# =========================================================================
print("=== 1. Guardian arranca activo ===")
montar()
ok(not db.get_state(GUARDIAN_SUSPENDED_KEY, False), "sin estado guardado, esta activo")
rt.tick()
ok(espias["guardian"].ticks == 1, "y su tick corre")

print("\n=== 2. el boton que se ofrece es el que corresponde ===")
vaciar()
sis().handle_command("/estado", "/estado")
fila = salida()[-1]
ok(messages.GUARDIAN_ESTADO_ACTIVO in (fila["text"] or ""), "activo: lo dice")
ok("SUSPENDER GUARDIAN" in (fila["buttons"] or ""), "y ofrece SUSPENDER")
ok("REANUDAR GUARDIAN" not in (fila["buttons"] or ""), "sin ofrecer los dos a la vez")

print("\n=== 3. suspender lo deja suspendido ===")
vaciar()
sis().handle_command("/suspender_guardian", "/suspender_guardian")
ok(db.get_state(GUARDIAN_SUSPENDED_KEY) is True, "el estado queda en suspendido")
ok("Guardian suspendido" in textos()[-1], "lo confirma")
ok("La agenda sigue funcionando" in textos()[-1], "y aclara que la agenda sigue")
ok("REANUDAR GUARDIAN" in (salida()[-1]["buttons"] or ""), "ofrece REANUDAR")

print("\n=== 3b. el aviso describe el sistema, no a la persona ===")
aviso = textos()[-1].lower()
ok(not any(p in aviso for p in ("estres", "estrés", "ansiedad", "descansa",
                                "te hace bien", "tranquilo", "relaja")),
   "sin texto psicologico")

print("\n=== 4 y 5. suspendido no corre su tick: ni rafagas ni baja frecuencia ===")
antes = espias["guardian"].ticks
rt.tick()
rt.tick()
ok(espias["guardian"].ticks == antes, "guardian.tick no se llama mas")

print("\n=== 6, 16, 18, 19. lo demas sigue intacto ===")
ok(espias["vigia"].ticks == 3, "Vigia sigue tickeando")
ok(espias["vigia"].eventos == EVENTOS, "y sigue recibiendo los eventos de Calendar")
ok(espias["intervalos"].ticks == 3, "Intervalos sigue")
ok(espias["timer"].ticks == 3, "Timer sigue")
ok(espias["pomodoro"].ticks == 3 and espias["lite"].ticks == 3, "Pomodoro y Lite siguen")

print("\n=== 7, 8. los eventos no se borran ni se resuelven ===")
evento("ev_previo")
filas = db.query("SELECT * FROM guardian_events")
ok(len(filas) == 1, "el evento esta")
sis().handle_command("/suspender_guardian", "/suspender_guardian")
filas = db.query("SELECT * FROM guardian_events")
ok(len(filas) == 1, "suspender otra vez no lo borra")
ok(filas[0]["phase"] == "insiste", "no le cambia la fase")
ok(filas[0]["is_active"] == 1, "no lo marca resuelto")
inicio = filas[0]["start_at"]
evento("ev_durante")
ok(len(db.query("SELECT * FROM guardian_events")) == 2,
   "un evento que aparece durante la suspension sigue existiendo")
ok(db.query("SELECT * FROM guardian_events")[0]["start_at"] == inicio,
   "y a nadie se le movio la hora")

print("\n=== 9, 10. suspender corta la rafaga pendiente, no la ya enviada ===")
montar()
evento()
rafaga_programada()
ahora = datetime.now(timezone.utc).isoformat()
with db.transaction():
    db.execute("INSERT INTO outbox(chat_id, kind, text, created_at, sent_at) "
               "VALUES (?,'text',?,?,'ya')", (YO, "ESTE YA SALIO", ahora))
    db.execute("INSERT INTO outbox(chat_id, kind, text, send_after, created_at) "
               "VALUES (?,'text',?,?,?)",
               (YO, "aviso de Timer, ajeno a Guardian",
                (datetime.now().astimezone() + timedelta(seconds=30)).isoformat(), ahora))
ok(len(salida(pendientes=True)) == 4, "hay 3 de rafaga + 1 de Timer esperando")

sis().handle_command("/suspender_guardian", "/suspender_guardian")
quedan = [f["text"] for f in salida(pendientes=True)]
ok(not any(t in messages.GUARDIAN_INSISTE for t in quedan),
   "los mensajes de rafaga que no salieron se cancelan")
ok("aviso de Timer, ajeno a Guardian" in quedan, "el de Timer NO se toca")
ok(any(f["text"] == "ESTE YA SALIO" for f in salida()),
   "y el que ya salio queda como estaba")

print("\n=== 11, 12. reanudar no dispara una avalancha ===")
vaciar()
sis().handle_command("/reanudar_guardian", "/reanudar_guardian")
ok(db.get_state(GUARDIAN_SUSPENDED_KEY) is False, "vuelve a estar activo")
ok(len(salida()) == 1, "manda UN mensaje, no una tanda atrasada")
ok("Guardian reanudado" in textos()[-1], "y es el aviso de reanudado")
ok("SUSPENDER GUARDIAN" in (salida()[-1]["buttons"] or ""), "que ya ofrece suspender")

print("\n=== 13. despues de reanudar vuelve a funcionar ===")
antes = espias["guardian"].ticks
rt.tick()
ok(espias["guardian"].ticks == antes + 1, "su tick corre de nuevo")

print("\n=== 14, 15. la suspension sobrevive a un reinicio ===")
sis().handle_command("/suspender_guardian", "/suspender_guardian")
db.close()
db2 = Database(cfg.db_path, cfg.schema_path)
db2.migrate()
ok(db2.get_state(GUARDIAN_SUSPENDED_KEY) is True, "reinicio suspendido: sigue suspendido")
with db2.transaction():
    db2.set_state(GUARDIAN_SUSPENDED_KEY, False)
db2.close()
db3 = Database(cfg.db_path, cfg.schema_path)
db3.migrate()
ok(db3.get_state(GUARDIAN_SUSPENDED_KEY) is False, "reinicio activo: sigue activo")
db3.close()

print("\n=== 17. la Cola de Guardian queda como estaba ===")
montar()
evento("en_cola", phase="queued")
sis().handle_command("/suspender_guardian", "/suspender_guardian")
fila = db.query("SELECT * FROM guardian_events WHERE event_id='en_cola'")[0]
ok(fila["phase"] == "queued", "un evento encolado sigue encolado")
ok(len(db.query("SELECT * FROM guardian_events")) == 1, "y no se borro")

print("\n=== 20, 21. un solo estado, sin duplicados ===")
claves = db.query("SELECT key FROM system_state WHERE key LIKE '%suspend%'")
ok([k["key"] for k in claves] == [GUARDIAN_SUSPENDED_KEY],
   "una sola clave nueva en system_state")
ok(GUARDIAN_SUSPENDED_KEY != SUSPENDED_KEY, "y no pisa la suspension global")
vaciar()
sis().handle_command("/suspender_guardian", "/suspender_guardian")
sis().handle_command("/suspender_guardian", "/suspender_guardian")
ok(len(db.query("SELECT key FROM system_state WHERE key LIKE '%suspend%'")) == 1,
   "suspender dos veces no duplica el estado")

print("\n=== 22. no se toca Calendar ===")
ok(espias["vigia"].eventos is None or espias["vigia"].eventos == EVENTOS,
   "los eventos llegan tal cual se leyeron")
ok(not db.query("SELECT * FROM calendar_privacy_ledger"),
   "no se escribio nada en el ledger de Calendar")

print("\n=== 23. la suspension global sigue siendo otra cosa ===")
montar()
sis().handle_command("/suspender_guardian", "/suspender_guardian")
ok(not db.get_state(SUSPENDED_KEY, False), "suspender Guardian NO suspende todo Mastil")
sis().handle_command("/reset_estado", "/reset_estado")
ok(db.get_state(GUARDIAN_SUSPENDED_KEY) is False, "y /reset_estado lo deja activo")

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
