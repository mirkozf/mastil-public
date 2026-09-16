"""Gmail en modo simple: una sola pregunta y nada mas.

TEMPORAL, para las temporadas en que hay que revisar el correo de verdad y
seguido. El flujo completo sigue entero: lo unico que cambia es
`FRICCION_COMPLETA` en modules/gmail.py.

Esta suite cubre LAS DOS rutas, para que volver atras sea seguro.
"""

import os, sys, dataclasses
from pathlib import Path

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import messages
import modules.gmail as G
from database import Database
from modules.gmail import GmailModule

# Esta suite cubre LAS DOS rutas, asi que declara el modo que prueba en cada
# tramo en vez de heredarlo. El interruptor puede estar en cualquiera de los
# dos lados sin que estas pruebas se caigan ni dejen de cubrir nada.
ORIGINAL = G.FRICCION_COMPLETA
G.FRICCION_COMPLETA = False

YO = "999"
TMP = Path(os.environ["TEMP"]) / "gmail_simple" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP)

FALLAS = 0


def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c:
        FALLAS += 1


class Puente:
    """Doble del Apps Script: contesta sin red y cuenta las consultas."""

    enabled = True

    def __init__(self):
        self.consultas = 0

    def unread_count(self, *a, **k):
        self.consultas += 1
        return 3

    def senders(self, *a, **k):
        self.consultas += 1
        return ["alguien@x.com"]

    def __getattr__(self, n):
        def _(*a, **k):
            self.consultas += 1
            return []
        return _


class Vision:
    """Si esto se llama en modo simple, el modo simple esta mal."""

    enabled = True

    def __init__(self):
        self.llamadas = 0

    def __getattr__(self, n):
        def _(*a, **k):
            self.llamadas += 1
            return {"decision": "TECHNICAL_ERROR"}
        return _


class TG:
    def send_message(self, *a, **k):
        return {"ok": True}


db = None
gm = None
puente = None
vision = None


def montar():
    global db, gm, puente, vision
    if db:
        db.close()
    TMP.unlink(missing_ok=True)
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    puente, vision = Puente(), Vision()
    gm = GmailModule(cfg, db, puente, TG(), vision)


def salida():
    return [f["text"] or "" for f in db.query("SELECT text FROM outbox ORDER BY id")]


def ultimo():
    s = salida()
    return s[-1] if s else ""


def botones_ultimo():
    f = db.query("SELECT buttons FROM outbox ORDER BY id")
    return (f[-1]["buttons"] or "") if f else ""


def vaciar():
    with db.transaction():
        db.execute("DELETE FROM outbox")


# =========================================================================
print("=== 1. el interruptor esta donde se dijo ===")
ok(hasattr(G, "FRICCION_COMPLETA"), "existe FRICCION_COMPLETA")
ok(isinstance(ORIGINAL, bool),
   f"y es un interruptor de dos lados (hoy: {ORIGINAL})")

print("\n=== 2. revisar pregunta UNA vez y nada mas ===")
montar()
gm.handle_command("/gmail_hay", "/gmail_hay")
ok(messages.GMAIL_CONFIRMA_SIMPLE in ultimo(), "pregunta si esta seguro")
ok("/gmail_igual" in botones_ultimo(), "ofrece confirmar")
ok("/gmail_dejarlo" in botones_ultimo(), "y desistir")
ok(puente.consultas == 0, "todavia no consulto el buzon")
ok(vision.llamadas == 0, "y no llamo al modelo")

print("\n=== 3. confirmar revisa, sin mas preguntas ===")
vaciar()
gm.handle_command("/gmail_igual", "/gmail_igual")
ok(puente.consultas == 1, "consulta el buzon")
ok(vision.llamadas == 0, "sin pasar por el modelo")
ok(messages.GMAIL_PIDE_MOTIVO not in " ".join(salida()), "y sin pedir motivo")

print("\n=== 4. sin tope diario ===")
#
# Es el punto del modo simple: revisar seguido no se bloquea.
montar()
for vuelta in range(6):
    vaciar()
    gm.handle_command("/gmail_hay", "/gmail_hay")
    ok(messages.GMAIL_CONFIRMA_SIMPLE in ultimo(),
       f"revision {vuelta + 1}: sigue preguntando lo mismo")
    gm.handle_command("/gmail_igual", "/gmail_igual")
ok(puente.consultas == 6, "las seis se hicieron")
ok(vision.llamadas == 0, "y el modelo no intervino ninguna vez")

print("\n=== 5. pero el contador SIGUE anotando ===")
#
# Para que volver a la friccion completa encuentre el dia entero, no en cero.
estado = db.get_state(G.CONTADOR_KEY) or {}
anotado = (estado.get("usos", {}).get("/gmail_hay", {}) or {}).get("n")
ok(anotado == 6, f"quedaron anotadas las seis revisiones (n={anotado})")
ok(estado.get("fecha"), "con la fecha del dia")

print("\n=== 6. desistir no revisa nada ===")
montar()
gm.handle_command("/gmail_hay", "/gmail_hay")
vaciar()
gm.handle_command("/gmail_dejarlo", "/gmail_dejarlo")
ok(messages.GMAIL_DEJADO in ultimo(), "lo dice")
ok(puente.consultas == 0, "y no toco el buzon")

print("\n=== 7. abrir un correo concreto no cambio ===")
montar()
gm.handle_command("/gmail_contenido", "/gmail_contenido 1 natural")
ok(messages.GMAIL_CONFIRMA_SIMPLE not in ultimo(),
   "leer un correo puntual no pasa por la confirmacion")

print("\n=== 8. con el puente apagado avisa igual ===")
montar()
puente.enabled = False
gm.handle_command("/gmail_hay", "/gmail_hay")
ok(messages.GMAIL_DESHABILITADO in ultimo(), "lo dice antes que nada")

print("\n=== 9. LA VUELTA ATRAS: con FRICCION_COMPLETA en True ===")
#
# Es lo unico que hay que cambiar para volver al comportamiento de siempre.
G.FRICCION_COMPLETA = True
try:
    montar()
    vaciar()
    gm.handle_command("/gmail_hay", "/gmail_hay")
    ok(messages.GMAIL_CONFIRMA_SIMPLE not in ultimo(),
       "ya no aparece la pregunta simple")
    ok("Te quedan 2 revisiones" in ultimo(), "con cupo pregunta cuantas quedan")
    ok(puente.consultas == 0, "y no revisa sin confirmar")
    gm.handle_command("/gmail_igual", "/gmail_igual")
    ok(puente.consultas == 1, "confirmada, la primera revision entra")
    ok(vision.llamadas == 0, "sin motivo ni modelo")

    # Se agota la segunda revision del dia.
    gm.handle_command("/gmail_hay", "/gmail_hay")
    gm.handle_command("/gmail_igual", "/gmail_igual")
    vaciar()
    gm.handle_command("/gmail_hay", "/gmail_hay")
    ok("Ya usaste tus" in ultimo() and "REVISAR IGUAL" in botones_ultimo(),
       "agotadas, vuelve la friccion de siempre")

    vaciar()
    gm.handle_command("/gmail_igual", "/gmail_igual")
    ok(messages.GMAIL_PIDE_MOTIVO in ultimo(),
       "y vuelve a pedir el motivo escrito")
finally:
    G.FRICCION_COMPLETA = ORIGINAL

ok(G.FRICCION_COMPLETA is ORIGINAL,
   "la suite deja el interruptor como lo encontro")

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
