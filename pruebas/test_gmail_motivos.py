"""Los motivos escritos quedan guardados y Gemini ve los anteriores.

El contador dice CUANTAS veces se reviso. Esto dice CON QUE se justifico, que
es lo unico capaz de mostrar cuando la friccion se volvio tramite: una formula
repetida treinta veces pasaba treinta veces, porque cada evaluacion se hacia a
ciegas de las anteriores.

Lo que se prueba: que se guarden, que no crezcan sin techo, y sobre todo que el
motivo de hoy se compare con los de antes y NO consigo mismo.
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
import modules.gmail as G
from database import Database
from core.router import Router
from modules.gmail import GmailModule, MOTIVOS_KEY, MOTIVOS_MAX

# Esta suite prueba la FRICCION COMPLETA, que puede no ser el modo por defecto
# (ver FRICCION_COMPLETA en modules/gmail.py). Se declara aca para que siga
# cubierta pase lo que pase con el interruptor.
G.FRICCION_COMPLETA = True
from modules.panel import PanelModule

# ---- reloj falso -------------------------------------------------------
BASE = datetime.now().astimezone().replace(hour=10, minute=0, second=0,
                                           microsecond=0)
RELOJ = {"t": BASE}


def ahora():
    return RELOJ["t"]


def avanzar(**kw):
    RELOJ["t"] = RELOJ["t"] + timedelta(**kw)


sched.now_local = ahora
G.now_local = ahora

YO = "999"
TMP = Path(os.environ["TEMP"]) / "gmail_motivos" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP)

FALLAS = 0


def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c:
        FALLAS += 1


class Puente:
    enabled = True

    def __init__(self):
        self.llamadas = []

    def count_unread(self):
        self.llamadas.append("count")
        return 3

    def list_unread(self, limit=10):
        self.llamadas.append("list")
        return [{"id": "m1", "from": "x@x.cl", "subject": "s", "date": "d"}]


class VisionFalsa:
    """Gemini falso: guarda el prompt que recibio."""

    def __init__(self, ok_=True):
        self.prompts = []
        self.ok_ = ok_

    def evaluar_texto(self, prompt):
        self.prompts.append(prompt)
        if not self.ok_:
            return {"ok": False, "texto": "", "error": "caido"}
        return {"ok": True, "texto": "Yo lo dejaría para mañana.", "error": ""}


class TG:
    def answer_callback(self, cid, text="", show_alert=False):
        pass

    def send_message(self, chat_id, text, buttons=None, parse_mode=None):
        return {"ok": True}


class Nada:
    def abandon_contexto(self, *a, **k): pass
    def handle_command(self, *a, **k): return False
    def stop(self, *a, **k): pass
    def restore_calendar(self, *a, **k): pass
    def matches(self, *a, **k): return False
    def handle_message(self, *a, **k): return False
    def handle_text(self, *a, **k): return False
    def handle_photo(self, *a, **k): return False
    def handle(self, *a, **k): return True


db = None


def montar(vision=None):
    global db
    if db:
        db.close()
    TMP.unlink(missing_ok=True)
    RELOJ["t"] = BASE
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    puente, vis, tg = Puente(), vision or VisionFalsa(), TG()
    gmail = GmailModule(cfg, db, puente, tg, vis)
    panel = PanelModule(cfg, db)
    mods = {"gmail": gmail, "panel": panel, "timer": Nada(),
            "system": Nada(), "pomodoro": Nada(), "guardian": Nada(),
            "calendar": Nada(), "lite": Nada(), "vigia": Nada(),
            "intervalos": Nada()}
    r = Router(cfg, db, tg, mods)
    panel.attach(r)
    # La friccion solo aparece con las revisiones del dia agotadas, asi que se
    # gastan de entrada. Se limpia el rastro para que cada seccion pueda contar
    # las aperturas del buzon desde cero.
    for _ in range(messages.GMAIL_LIMITE_DIARIO):
        r.process(msg("/gmail_hay"))
        r.process(cbq("/gmail_igual"))     # con cupo, revisar se confirma
    puente.llamadas.clear()
    vaciar()
    return r, gmail, puente, vis


def vaciar():
    with db.transaction():
        db.execute("DELETE FROM outbox")


def msg(t, mid=1):
    return {"message": {"message_id": mid, "chat": {"id": YO},
                        "from": {"id": YO}, "text": t}}


def cbq(data, mid=7):
    return {"callback_query": {"id": "c", "data": data, "from": {"id": YO},
                               "message": {"message_id": mid,
                                           "chat": {"id": YO}}}}


def guardados():
    return db.get_state(MOTIVOS_KEY) or []


def escribir_motivo(r, texto, mid=2):
    """El camino completo: agotar, REVISAR IGUAL, abrir el formulario, escribir."""
    r.process(msg("/gmail_hay", mid))
    r.process(cbq("/gmail_igual", mid))
    r.process(cbq("panel:gm:motivo", mid))
    vaciar()
    r.process(msg(texto, mid))


def seccion_historial(prompt):
    """Solo el bloque de motivos anteriores.

    El motivo de hoy tambien aparece mas arriba, en MOTIVO DECLARADO, asi que
    buscarlo en el prompt entero no distinguiria una cosa de la otra.
    """
    inicio = prompt.index("MOTIVOS QUE YA HABÍA ESCRITO ANTES")
    return prompt[inicio:prompt.index("CONTEXTO OPERATIVO", inicio)]


# =========================================================================
print("=== 1. el texto del historial, sin sistema alrededor ===")
ok("ninguno registrado" in messages.gmail_historial_motivos([]),
   "sin motivos lo dice, no manda un bloque vacio")
ok("ninguno registrado" in messages.gmail_historial_motivos(None),
   "y aguanta que le pasen nada")

muestra = [
    {"cuando": "2026-09-01T08:30:00", "comando": "/gmail_hay", "motivo": "el primero"},
    {"cuando": "2026-09-02T09:45:00", "comando": "/gmail_hay", "motivo": "el segundo"},
]
texto = messages.gmail_historial_motivos(muestra)
ok('"el primero"' in texto and '"el segundo"' in texto, "van los dos, entre comillas")
ok(texto.index("el segundo") < texto.index("el primero"),
   "del mas reciente al mas antiguo")
ok("2026-09-02 09:45" in texto, "con fecha y hora legibles, sin la T")
ok("(en blanco)" in messages.gmail_historial_motivos([{"motivo": "   "}]),
   "un motivo vacio no deja una linea muda")

print("\n=== 2. escribir un motivo lo guarda ===")
r, gmail, puente, vis = montar()
escribir_motivo(r, "necesito el numero de la cuenta")
ok(len(guardados()) == 1, f"quedo guardado ({len(guardados())})")
entrada = guardados()[0]
ok(entrada["motivo"] == "necesito el numero de la cuenta", "con el texto exacto")
ok(entrada["comando"] == "/gmail_hay", "y con la consulta que lo pidio")
ok(entrada.get("cuando"), "y con su hora")

print("\n=== 3. el motivo de hoy NO se compara consigo mismo ===")
#
# Es el punto delicado del orden: si se guardara antes de evaluar, el modelo
# veria el motivo de hoy repetido en su propio historial y creeria que se
# repite cuando es la primera vez que lo escribe.
ok(len(vis.prompts) == 1, "Gemini recibio una consulta")
bloque = seccion_historial(vis.prompts[0])
ok("ninguno registrado" in bloque,
   "la primera vez el historial va vacio, no con el motivo recien escrito")
ok("necesito el numero de la cuenta" not in bloque,
   "el motivo de hoy no se cuela entre los anteriores")
ok('"necesito el numero de la cuenta"' in vis.prompts[0],
   "pero si sigue estando como MOTIVO DECLARADO")

print("\n=== 4. el segundo motivo SI ve al primero ===")
escribir_motivo(r, "quiero ver si contesto", mid=3)
ok(len(vis.prompts) == 2, "segunda consulta a Gemini")
bloque = seccion_historial(vis.prompts[1])
ok("necesito el numero de la cuenta" in bloque, "ahora si aparece el anterior")
ok("quiero ver si contesto" not in bloque, "y el de hoy sigue sin colarse")
ok(len(guardados()) == 2, "y quedaron los dos guardados")

print("\n=== 5. el prompt trae la instruccion de comparar ===")
p = vis.prompts[1]
ok("MOTIVOS QUE YA HABÍA ESCRITO ANTES" in p, "la seccion tiene titulo propio")
ok("Compara el motivo de hoy con los anteriores" in p, "y le pide compararlos")
ok("reproche" in p, "aclarandole que no es un reproche")
ok("No moralices" in p and "No diagnostiques" in p,
   "las prohibiciones de siempre siguen enteras")
ok(cfg.telegram_bot_token not in p, "y sin credenciales, como siempre")

print("\n=== 6. se guarda aunque despues desista ===")
#
# Lo que interesa es que se dijo a si mismo, no si llego a abrir el buzon.
r, gmail, puente, vis = montar()
escribir_motivo(r, "solo una miradita")
r.process(cbq("/gmail_dejarlo"))
ok(len(guardados()) == 1, "el motivo quedo igual")
ok(not puente.llamadas, "aunque el buzon no se abrio")

print("\n=== 7. reintentar no duplica el motivo ===")
r, gmail, puente, vis = montar(VisionFalsa(ok_=False))
escribir_motivo(r, "se cayo gemini")
ok(len(guardados()) == 1, "se guardo una vez")
r.process(cbq("/gmail_reintentar"))
ok(len(vis.prompts) == 2, "el reintento vuelve a consultar")
ok(len(guardados()) == 1, f"pero NO lo anota de nuevo ({len(guardados())})")

print("\n=== 8. un motivo en blanco no ensucia el historial ===")
r, gmail, puente, vis = montar()
r.process(msg("/gmail_hay"))
r.process(cbq("/gmail_igual"))
r.process(cbq("panel:gm:motivo"))
r.process(msg("    ", 2))
ok(not guardados(), "no guarda una linea vacia")

print("\n=== 9. el techo de los 30 ===")
r, gmail, puente, vis = montar()
viejos = [{"cuando": f"2026-08-{d:02d}T10:00:00", "comando": "/gmail_hay",
           "motivo": f"motivo viejo {d}"} for d in range(1, MOTIVOS_MAX + 1)]
with db.transaction():
    db.set_state(MOTIVOS_KEY, viejos)
ok(len(guardados()) == MOTIVOS_MAX, f"parto con {MOTIVOS_MAX} guardados")

escribir_motivo(r, "el mas nuevo de todos")
ahora_hay = guardados()
ok(len(ahora_hay) == MOTIVOS_MAX,
   f"sigue en {MOTIVOS_MAX}, no crece sin techo ({len(ahora_hay)})")
ok(ahora_hay[-1]["motivo"] == "el mas nuevo de todos", "el nuevo entra al final")
ok(all(e["motivo"] != "motivo viejo 1" for e in ahora_hay),
   "y el mas antiguo se cae")
ok(any(e["motivo"] == "motivo viejo 2" for e in ahora_hay),
   "pero el resto se conserva entero")

print("\n=== 10. un motivo larguisimo se recorta ===")
r, gmail, puente, vis = montar()
escribir_motivo(r, "a" * 500)
ok(len(guardados()[0]["motivo"]) == 300,
   f"queda en 300 ({len(guardados()[0]['motivo'])})")

print("\n=== 11. no toca el contador ni la auditoria ===")
#
# Son registros distintos: uno cuenta, el otro guarda texto. Y `Database.audit`
# dice explicitamente que nunca lleva contenido privado.
filas = db.query("SELECT detail FROM audit_events WHERE module = 'gmail'")
ok(all("aaa" not in (f["detail"] or "") for f in filas),
   "el motivo NO se filtro a la auditoria")

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
