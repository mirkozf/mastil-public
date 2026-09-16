"""Guardian conserva una sola tarjeta de cola fuera de los tres recientes."""

import dataclasses
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import core.runtime as R
import messages
from database import Database
from core.runtime import Runtime
from modules.panel import PANEL_MESSAGE_KEY

YO = "999"
TMP = Path(os.environ["TEMP"]) / "cola_ancla_chat" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
TMP.unlink(missing_ok=True)

ZONA = timezone(timedelta(hours=-4))
for modulo in list(sys.modules.values()):
    if getattr(modulo, "__name__", "") != "zoneinfo" and hasattr(modulo, "ZoneInfo"):
        modulo.ZoneInfo = lambda nombre=None: ZONA

R.read_events = lambda *a, **k: []
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP,
                          lite_secret_path=TMP.parent / "lite_secret.key")

FALLAS = 0


def ok(condicion, texto):
    global FALLAS
    print(f"  {'ok  ' if condicion else 'MAL '} {texto}")
    if not condicion:
        FALLAS += 1


class Telegram:
    def __init__(self):
        self.n = 1000
        self.sent = []
        self.edited = []
        self.deleted = []

    def send_message(self, chat_id, text, buttons=None, parse_mode=None,
                     disable_notification=False):
        self.n += 1
        self.sent.append((self.n, text, buttons, parse_mode))
        return {"ok": True, "result": {"message_id": self.n}}

    def send_photo(self, *args, **kwargs):
        self.n += 1
        return {"ok": True, "result": {"message_id": self.n}}

    def edit_message(self, chat_id, message_id, text, buttons=None, parse_mode=None):
        self.edited.append((int(message_id), text, buttons, parse_mode))
        return {"ok": True}

    def delete_message(self, chat_id, message_id):
        self.deleted.append(int(message_id))
        return {"ok": True}

    def delete_messages(self, chat_id, message_ids):
        self.deleted.extend(int(x) for x in message_ids)
        return {"ok": True}

    def answer_callback(self, *args, **kwargs):
        pass

    def get_updates(self, *args, **kwargs):
        return []


db = Database(cfg.db_path, cfg.schema_path)
db.migrate()
rt = Runtime(cfg, db)
tg = Telegram()
rt.telegram = tg
rt.router.telegram = tg
guardian = rt.modules["guardian"]

now = datetime.now().astimezone().replace(microsecond=0)
evento_a = {"id": "A", "title": "** ordenar cocina", "start": now}
evento_b = {"id": "B", "title": "** lavar loza", "start": now}

print("=== 1. una cola crea una sola tarjeta protegida ===")
guardian.tick([evento_a])
rt.flush_outbox()
guardian.tick([evento_a, evento_b])
rt.flush_outbox()

anchor_id = db.get_state("guardian_queue_message_id")
panel_id = db.get_state(PANEL_MESSAGE_KEY)
anchor = db.one(
    "SELECT protected, deleted_at FROM telegram_messages WHERE chat_id=? AND message_id=?",
    (YO, anchor_id),
)
ok(anchor_id is not None, "Guardian conoce el id real de su tarjeta")
ok(anchor and anchor["protected"] == 1 and anchor["deleted_at"] is None,
   "la tarjeta queda protegida")
ok(panel_id > anchor_id, "el panel vuelve a quedar debajo de la tarjeta")
ok(any("SIGUIENTE PENDIENTE" in text and "lavar loza" in text
       for _, text, _, _ in tg.sent), "la tarjeta nombra la siguiente tarea")

print("\n=== 2. conserva la tarjeta mas tres normales y el panel ===")
for numero in range(4):
    with db.transaction():
        db.enqueue(YO, f"AVISO {numero}")
    rt.flush_outbox()

normales = db.query(
    """
    SELECT message_id FROM telegram_messages
    WHERE chat_id=? AND is_panel=0 AND protected=0 AND deleted_at IS NULL
    ORDER BY message_id
    """,
    (YO,),
)
anchor = db.one(
    "SELECT protected, deleted_at FROM telegram_messages WHERE chat_id=? AND message_id=?",
    (YO, anchor_id),
)
ok(len(normales) == 3, "quedan exactamente tres mensajes normales")
ok(anchor and anchor["protected"] == 1 and anchor["deleted_at"] is None,
   "la tarjeta de cola no se pierde")
ok(db.get_state(PANEL_MESSAGE_KEY) > normales[-1]["message_id"],
   "el panel queda al final")

print("\n=== 2b. la tarjeta lista lo que espera y vuelve a sonar cada 15 min ===")
texto = next((t for mid, t, _, _ in tg.sent if mid == anchor_id), "")
ok("- <b>lavar loza</b>" in texto, f"lista la tarea que espera, con guion: {texto!r}")
enviados_antes = len(tg.sent)
with db.transaction():
    # Se adelanta el reloj del aviso agregado en vez de esperar 15 minutos.
    db.set_state("cola_aviso_next", "2000-01-01T00:00:00+00:00")
guardian.tick([evento_a, evento_b])
rt.flush_outbox()
nuevo_id = db.get_state("guardian_queue_message_id")
ok(nuevo_id and nuevo_id != anchor_id, "a los 15 minutos se manda de nuevo, abajo")
ok(anchor_id in tg.deleted, "y la anterior se borra: sigue habiendo una sola")
ok(any(mid == nuevo_id and "- <b>lavar loza</b>" in t
       for mid, t, _, _ in tg.sent[enviados_antes:]), "con la misma lista")
anchor_id = nuevo_id

print("\n=== 3. al cerrar A, la decisión de B llega como tarjeta nueva ===")
#
# Antes la tarjeta se editaba en su sitio y la decision llegaba muda. Es el
# momento en que hay que decidir: tiene que sonar.
guardian.handle_command("/listo", "/listo")
rt.flush_outbox()
guardian.tick([])
rt.flush_outbox()

nuevo_id = db.get_state("guardian_queue_message_id")
tarjeta = next(((t, b) for mid, t, b, _ in tg.sent if mid == nuevo_id), ("", None))
callbacks = [boton[1] for fila in (tarjeta[1] or []) for boton in fila]
ok(nuevo_id and nuevo_id != anchor_id,
   "no edita la tarjeta vieja: la decision se manda de nuevo y suena")
ok(anchor_id in tg.deleted, "la vieja se borra, asi sigue habiendo una sola")
ok(messages.COLA_DECISION_TITULO in tarjeta[0] and "lavar loza" in tarjeta[0],
   "la tarjeta nueva pide decidir B")
ok(callbacks and all(callback.startswith("cola:") for callback in callbacks),
   "conserva las tres acciones de decisión")
anchor_id = nuevo_id

print("\n=== 3b. recordatorios: el de 3 minutos refresca, el de 15 suena ===")
with db.transaction():
    db.execute("UPDATE guardian_events SET decision_next_at = ? "
               "WHERE phase = 'decision'", ("2000-01-01T00:00:00+00:00",))
guardian.tick([])
rt.flush_outbox()
ok(db.get_state("guardian_queue_message_id") == anchor_id,
   "el de los 3 minutos no manda otra tarjeta")
ok(tg.edited and tg.edited[-1][0] == anchor_id, "solo la actualiza en su sitio")

with db.transaction():
    db.execute("UPDATE guardian_events SET decision_step = 2, decision_next_at = ? "
               "WHERE phase = 'decision'", ("2000-01-01T00:00:00+00:00",))
guardian.tick([])
rt.flush_outbox()
nuevo_id = db.get_state("guardian_queue_message_id")
ok(nuevo_id and nuevo_id != anchor_id, "el de los 15 minutos vuelve a mandarla abajo")
ok(anchor_id in tg.deleted, "sin dejar copias")
anchor_id = nuevo_id

print("\n=== 4. HACER AHORA retira la excepción ===")
guardian.handle_cola_callback({
    "id": "c", "data": callbacks[0],
    "message": {"message_id": anchor_id, "chat": {"id": YO}},
})
rt.flush_outbox()
anchor = db.one(
    "SELECT deleted_at FROM telegram_messages WHERE chat_id=? AND message_id=?",
    (YO, anchor_id),
)
ok(anchor_id in tg.deleted, "Telegram recibió el borrado de la tarjeta")
ok(anchor and anchor["deleted_at"] is not None,
   "el ledger deja de tratarla como excepción")

print("\n=== 5. el final de la ráfaga conserva el nombre activo ===")
estado = guardian._active()
marca = db.one("SELECT COALESCE(MAX(id), 0) AS n FROM outbox")["n"]
guardian._insistir(estado)
rafaga = db.query(
    "SELECT text FROM outbox WHERE id > ? ORDER BY id", (marca,)
)
ok(len(rafaga) == 7, "la ráfaga conserva sus siete pasos")
ok("lavar loza" in rafaga[-1]["text"],
   "el último mensaje vuelve a nombrar la tarea")

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
