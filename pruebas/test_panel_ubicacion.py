"""El panel siempre vive en el ultimo mensaje de la conversacion.

Antes habia dos clases de boton visualmente iguales: los de navegacion editaban
el menu en su sitio y los de accion largaban un mensaje nuevo abajo, dejando el
menu arriba con los botones vivos. La respuesta aparecia en un lado y el panel
seguia en otro.

Regla unica: se conservan tres mensajes normales y un solo panel al final.
"""

import os, sys, dataclasses
from pathlib import Path
from datetime import timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import messages
import core.runtime as R
from database import Database
from core.runtime import Runtime
from modules.panel import (PANEL_MESSAGE_KEY, PANEL_MENU_KEY, PANEL_OUTBOX_KEY,
                           PANEL_SNAPSHOT_KEY)

YO = "999"

# ZoneInfo("America/Santiago") no existe en Windows: no viene la base IANA.
ZONA = timezone(timedelta(hours=-4))
for _mod in list(sys.modules.values()):
    if getattr(_mod, "__name__", "") != "zoneinfo" and hasattr(_mod, "ZoneInfo"):
        _mod.ZoneInfo = lambda nombre=None: ZONA

R.read_events = lambda *a, **k: []

TMP = Path(os.environ["TEMP"]) / "panel_ubic" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP,
                          lite_secret_path=TMP.parent / "lite_secret.key")

FALLAS = 0


def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c:
        FALLAS += 1


class TG:
    """Telegram doble: reparte message_id como los reparte el de verdad."""

    def __init__(self):
        self.enviados = []
        self.editados = []
        self.borrados = []
        self.callados = []      # los que llegaron sin notificar
        self.n = 1000

    def send_message(self, chat_id, text, buttons=None, parse_mode=None,
                     disable_notification=False):
        self.n += 1
        self.enviados.append((self.n, text, buttons))
        if disable_notification:
            self.callados.append(self.n)
        return {"ok": True, "result": {"message_id": self.n}}

    def edit_message(self, chat_id, message_id, text, buttons=None, parse_mode=None):
        self.editados.append((message_id, text, buttons))
        return {"ok": True}

    def send_photo(self, *a, **k):
        return {"ok": True}

    def delete_message(self, chat_id, message_id):
        self.borrados.append(message_id)
        return {"ok": True}

    def delete_messages(self, chat_id, message_ids):
        self.borrados.extend(message_ids)
        return {"ok": True}

    def answer_callback(self, *a, **k):
        pass

    def get_updates(self, *a, **k):
        return []


class Inter:
    """Doble de Intervalos: contesta como contesta el real, con un mensaje."""

    def handle(self, command, source_id=None, raw_text=""):
        with db.transaction():
            db.enqueue(YO, "RESPUESTA DE INTERVALOS")
        return True

    def handle_command(self, *a, **k):
        return False

    def tick(self, *a, **k):
        pass

    # Desde `ff1f2cb` el router lo llama en cada mensaje.
    def abandon_contexto(self, *a, **k):
        pass


db = None
rt = None
tg = None


def montar():
    global db, rt, tg
    if db:
        db.close()
    TMP.unlink(missing_ok=True)
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    rt = Runtime(cfg, db)
    tg = TG()
    rt.telegram = tg
    rt.router.telegram = tg
    rt.modules["intervalos"] = Inter()


def msg(texto, mid=1):
    return {"message": {"message_id": mid, "chat": {"id": YO},
                        "from": {"id": YO}, "text": texto}}


def cb(data, mid):
    return {"callback_query": {"id": "c", "data": data, "from": {"id": YO},
                               "message": {"message_id": mid,
                                           "chat": {"id": YO}}}}


def ciclo(update):
    rt.router.process(update)
    rt.flush_outbox()


# =========================================================================
print("=== 1. el panel sabe en que mensaje quedo ===")
montar()
ciclo(msg("/panel"))
ok(len(tg.enviados) == 1, "se mando el panel")
ok(db.get_state(PANEL_MESSAGE_KEY) == tg.enviados[0][0],
   "y quedo anotado su message_id real")
ok(db.get_state(PANEL_OUTBOX_KEY) is None, "la fila que se seguia ya se solto")
ok(db.get_state(PANEL_MENU_KEY) == "panel:home", "arranca en el home")

print("\n=== 2. navegar sigue editando en el sitio ===")
panel_id = db.get_state(PANEL_MESSAGE_KEY)
ciclo(cb("panel:intervalos", panel_id))
ok(len(tg.enviados) == 1, "no aparecio ningun mensaje nuevo")
ok(tg.editados and tg.editados[-1][0] == panel_id, "se edito el mismo mensaje")
ok(db.get_state(PANEL_MENU_KEY) == "panel:intervalos", "y recuerda donde estas")

print("\n=== 3. una accion deja la respuesta y el panel, en ese orden ===")
ciclo(cb("/marca", panel_id))
enviados = [t for _, t, _ in tg.enviados]
ok("RESPUESTA DE INTERVALOS" in enviados, "el modulo contesto")
ok(enviados[-1] == messages.PANEL_TITULO,
   "y el panel quedo DESPUES, al final de todo")
ok(enviados.index("RESPUESTA DE INTERVALOS") < len(enviados) - 1,
   "la respuesta salio antes que el panel")

print("\n=== 4. la pantalla vieja se borra ===")
ok(panel_id in tg.borrados, "se borro la pantalla vieja")
ok(not [e for e in tg.editados if e[1] == messages.PANEL_APAGADO],
   "no deja una copia apagada cuando Telegram permite borrarla")

print("\n=== 5. el panel vuelve al menu PRINCIPAL, no a donde estabas ===")
#
# Arrastrar la pantalla anterior al pie del chat hacia reaparecer cosas que ya
# no venian al caso: un pedido cumplido, un menu del que ya te habias ido.
# Volver siempre al home cuesta un toque de mas y a cambio no sorprende nunca.
ok(tg.enviados[-1][1] == messages.PANEL_TITULO, "reaparece en el home")
ok(tg.enviados[-1][2] == messages.PANEL_BOTONES, "con la botonera principal")
ok(db.get_state(PANEL_MENU_KEY) == "panel:home", "y lo deja anotado asi")

print("\n=== 6. y el panel nuevo tambien sabe donde quedo ===")
ok(db.get_state(PANEL_MESSAGE_KEY) == tg.enviados[-1][0],
   "anoto el message_id del panel nuevo")

print("\n=== 7. dos acciones seguidas: la regla se sostiene ===")
nuevo_id = db.get_state(PANEL_MESSAGE_KEY)
ciclo(cb("/marca", nuevo_id))
ok(tg.enviados[-1][1] == messages.PANEL_TITULO,
   "el panel sigue quedando al final")
ok(nuevo_id in tg.borrados, "y la segunda pantalla vieja tambien se borro")
ok(db.get_state(PANEL_MESSAGE_KEY) == tg.enviados[-1][0], "sin perderle el rastro")

print("\n=== 7b. el Timer tampoco se arrastra ===")
#
# `panel:timer` es el unico que no esta en MENUS: se arma solo segun haya o no
# un timer corriendo, y por eso tenia un tratamiento aparte para no reaparecer
# con un estado viejo. Volviendo siempre al home ese caso especial sobra.
montar()
ciclo(msg("/panel"))
pid = db.get_state(PANEL_MESSAGE_KEY)
ciclo(cb("panel:timer", pid))
ok(db.get_state(PANEL_MENU_KEY) == "panel:timer", "entrar al Timer queda anotado")
pid = db.get_state(PANEL_MESSAGE_KEY)
ciclo(cb("/tm", pid))
ok(tg.enviados[-1][1] == messages.PANEL_TITULO,
   "pero tras una accion vuelve al home, como todos")
ok(db.get_state(PANEL_MENU_KEY) == "panel:home", "y ya no dice estar en el Timer")
ok(bool(tg.enviados[-1][2]), "y el panel que reaparece trae botones")

print("\n=== 8. cualquier respuesta nueva devuelve el panel al final ===")
montar()
ciclo(msg("/panel"))
antes_env = len(tg.enviados)
# Un mensaje cualquiera de Guardian con su boton: otro message_id.
ciclo(cb("/marca", 7777))
enviados = [t for _, t, _ in tg.enviados]
ok(enviados[-2] == "RESPUESTA DE INTERVALOS", "primero aparece la respuesta")
ok(enviados[-1] == messages.PANEL_TITULO, "y despues el panel")
ok(len(tg.enviados) == antes_env + 2, "sale una respuesta y un solo panel")

print("\n=== 8c. el panel llega callado, la respuesta no ===")
#
# Cada aviso traia DOS notificaciones: la del aviso y la del panel que se
# recrea abajo para quedar al final. El panel no da noticias, solo botones: que
# suene el telefono porque el tablero cambio de lugar no tiene sentido.
montar()
ciclo(msg("/panel"))
ciclo(cb("/marca", 7777))
respuesta, panel = tg.enviados[-2], tg.enviados[-1]
ok(respuesta[1] == "RESPUESTA DE INTERVALOS", "la respuesta va primero")
ok(respuesta[0] not in tg.callados, "y SI notifica: es la noticia")
ok(panel[1] == messages.PANEL_TITULO, "el panel va despues")
ok(panel[0] in tg.callados, "y llega sin sonido")
ok(len(tg.callados) == 2, f"solo callan los paneles ({tg.callados})")

print("\n=== 8b. apagar la alarma del timer devuelve el panel ===")
#
# El aviso del timer trae su propio boton APAGAR, asi que el callback NO viene
# del panel. Una alarma puede sonar diez veces: para cuando la cortas, el panel
# quedo diez mensajes atras y no se encuentra mas. Apagarla es volver al punto
# de partida, asi que el panel vuelve con ella.
montar()
ciclo(msg("/panel"))
pid = db.get_state(PANEL_MESSAGE_KEY)
ciclo(cb("panel:intervalos", pid))
pid = db.get_state(PANEL_MESSAGE_KEY)
ciclo(cb("/apagar", 5555))          # 5555 = el aviso del Timer, ajeno al panel
ok(bool(tg.enviados[-1][2]), "tras apagar reaparece un panel con botones")
ok(db.get_state(PANEL_MESSAGE_KEY) == tg.enviados[-1][0], "y queda rastreado")
ok(pid in tg.borrados,
   "el panel viejo se borro, aunque el boton fuera de otro mensaje")
ok(tg.enviados[-1][1] == messages.PANEL_TITULO,
   "y vuelve al menu principal, como en cualquier otra accion")

print("\n=== 9. sobrevive a un reinicio ===")
montar()
ciclo(msg("/panel"))
panel_id = db.get_state(PANEL_MESSAGE_KEY)
ciclo(cb("panel:vigia", panel_id))
db.close()
db2 = Database(cfg.db_path, cfg.schema_path)
db2.migrate()
ok(db2.get_state(PANEL_MESSAGE_KEY) == panel_id, "recuerda donde esta el panel")
ok(db2.get_state(PANEL_MENU_KEY) == "panel:vigia", "y en que menu estabas")
db2.close()

print("\n=== 10. mover el panel no rompe un formulario activo ===")
montar()
ciclo(msg("/panel"))
pid = db.get_state(PANEL_MESSAGE_KEY)
ciclo(cb("panel:calendar", pid))
ciclo(cb("panel:cal:hoy", pid))
with db.transaction():
    db.enqueue(YO, "ALERTA EXTERNA")
rt.flush_outbox()
nuevo_pid = db.get_state(PANEL_MESSAGE_KEY)
ok(nuevo_pid != pid, "la alerta movio el formulario al final")
antes = len(tg.editados)
ciclo(msg("ir a comer", mid=88))
ok(len(tg.editados) == antes + 1, "el formulario recibio el texto")
ok(tg.editados[-1][0] == nuevo_pid,
   "y edito el panel nuevo, no el mensaje borrado")

print("\n=== 10b. la respuesta a lo que escribiste no se pierde al bajar ===")
#
# Paso en produccion: tras escribir el numero del correo, el panel mostraba la
# eleccion de formato, pero tu propio mensaje lo empujaba hacia abajo y al
# recrearse volvia al home. La pregunta desaparecia antes de poder elegir.


def escribir(texto, mid):
    """Como el runtime: procesa, anota el mensaje entrante y vacia la cola."""
    rt.router.process(msg(texto, mid))
    rt.message_policy.record_incoming(YO, mid)
    tg.n = max(tg.n, mid)      # Telegram numera en orden: lo que sigue va despues
    rt.flush_outbox()


def pedir_formato():
    montar()
    ciclo(msg("/panel"))
    pid = db.get_state(PANEL_MESSAGE_KEY)
    ciclo(cb("panel:gmail", pid))
    ciclo(cb("panel:gm:contenido", pid))
    escribir("3", 5000)


pedir_formato()
ultimo = tg.enviados[-1]
ok(ultimo[1] == messages.PANEL_GMAIL_FORMATO,
   f"el panel bajo mostrando la eleccion de formato ({(ultimo[1] or '')[:30]})")
destinos = [b[1] for fila in (ultimo[2] or []) for b in fila]
ok("/gmail_contenido 3 natural" in destinos
   and "/gmail_contenido 3 base64" in destinos,
   f"con NATURAL y BASE64 para ese correo ({destinos})")

# Un aviso ajeno mientras eliges: la pregunta sigue en pie.
with db.transaction():
    db.enqueue(YO, "ALERTA EXTERNA")
rt.flush_outbox()
ok(tg.enviados[-1][1] == messages.PANEL_GMAIL_FORMATO,
   "un aviso que llega mientras eliges no la borra")

# Irse a otra cosa la vuelve recuerdo: un comando, y el panel vuelve al home.
escribir("/marca", 6000)
ok(tg.enviados[-1][1] == messages.PANEL_TITULO,
   "mandar otra cosa la da por vieja: el panel vuelve al home")

# Apretar NATURAL la da por contestada: no revive al volver a bajar.
pedir_formato()
panel = rt.modules["panel"]
# El router le entrega el callback de adentro, no el update entero.
ok(panel.reubicar(cb("/gmail_contenido 3 natural",
                     db.get_state(PANEL_MESSAGE_KEY))["callback_query"]),
   "NATURAL cuenta como accion del panel")
panel.recreate_current(YO)
rt.flush_outbox()
ok(tg.enviados[-1][1] == messages.PANEL_TITULO,
   "ya elegido, el panel vuelve al home y la pregunta no revive")

print("\n=== 11. no se crean estados sueltos de mas ===")
montar()
ciclo(msg("/panel"))
claves = sorted(k["key"] for k in
                db.query("SELECT key FROM system_state WHERE key LIKE 'panel%'"))
ok(claves == sorted([PANEL_MESSAGE_KEY, PANEL_MENU_KEY, PANEL_OUTBOX_KEY,
                     PANEL_SNAPSHOT_KEY]),
   "exactamente las cuatro claves del panel")

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
