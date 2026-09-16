"""Limpieza por evento: Guardian conserva cola; Vigia no deja rastro."""

import dataclasses
import os
import sys
from datetime import datetime
from pathlib import Path

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import messages
import integrations.calendar as calendar_integration
from core.runtime import Runtime
from database import Database
from modules.panel import PANEL_MESSAGE_KEY

calendar_integration.ZoneInfo = lambda nombre=None: datetime.now().astimezone().tzinfo

YO = "999"
TMP = Path(os.environ["TEMP"]) / "limpieza_flujos" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
cfg = dataclasses.replace(
    cm.load(), owner_chat_id=YO, db_path=TMP,
    lite_secret_path=TMP.parent / "lite_secret.key",
    timezone="UTC",
)

FALLAS = 0


def ok(condicion, texto):
    global FALLAS
    print(f"  {'ok  ' if condicion else 'MAL '} {texto}")
    if not condicion:
        FALLAS += 1


class Telegram:
    def __init__(self):
        self.n = 2000
        self.sent = []
        self.edited = []
        self.deleted = []

    def send_message(self, chat_id, text, buttons=None, parse_mode=None,
                     disable_notification=False):
        self.n += 1
        self.sent.append((self.n, text, buttons, parse_mode))
        return {"ok": True, "result": {"message_id": self.n}}

    def send_photo(self, chat_id, path, caption="", parse_mode=None):
        self.n += 1
        self.sent.append((self.n, caption, None, parse_mode))
        return {"ok": True, "result": {"message_id": self.n}}

    def edit_message(self, chat_id, message_id, text, buttons=None,
                     parse_mode=None):
        self.edited.append((int(message_id), text, buttons, parse_mode))
        return {"ok": True}

    def delete_message(self, chat_id, message_id):
        self.deleted.append(int(message_id))
        return {"ok": True}

    def delete_messages(self, chat_id, message_ids):
        self.deleted.extend(int(mid) for mid in message_ids)
        return {"ok": True}


def montar():
    TMP.unlink(missing_ok=True)
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    runtime = Runtime(cfg, db)
    telegram = Telegram()
    runtime.telegram = telegram
    runtime.router.telegram = telegram
    runtime.modules["vigia"].telegram = telegram
    return db, runtime, telegram


print("=== 1. Guardian limpia sólo el evento activo ===")
db, rt, tg = montar()
guardian = rt.modules["guardian"]
ahora = datetime.now().astimezone().replace(microsecond=0)
evento_a = {"id": "evento-A", "title": "** bañarme", "start": ahora}
evento_b = {"id": "evento-B", "title": "** preparar comida", "start": ahora}

guardian.tick([evento_a])
rt.flush_outbox()
guardian.tick([evento_a, evento_b])
rt.flush_outbox()

anchor_id = db.get_state("guardian_queue_message_id")
flow_a = "guardian:evento-A"
ok(anchor_id is not None, "la siguiente tarea tiene tarjeta persistente")

# Encola una ráfaga y deja que salga sólo lo que ya está vencido. Los demás
# mensajes conservan send_after y representan el caso real de pulsar LISTO
# mientras la ráfaga todavía está llegando.
guardian._insistir(guardian._active())
rt.flush_outbox()
ok(db.one("SELECT 1 FROM outbox WHERE flow_key=? AND sent_at IS NULL", (flow_a,))
   is not None, "quedaron avisos de la ráfaga todavía por enviar")

guardian.handle_command("/listo", "/listo")
rt.flush_outbox()

ok(db.one("SELECT 1 FROM outbox WHERE flow_key=? AND sent_at IS NULL", (flow_a,))
   is None, "el cierre cancela todos los avisos futuros de A")
vivos_a = db.query(
    "SELECT message_id FROM telegram_messages "
    "WHERE flow_key=? AND deleted_at IS NULL", (flow_a,)
)
ok(not vivos_a, "el cierre borra todos los avisos ya enviados de A")

anchor = db.one(
    "SELECT deleted_at FROM telegram_messages WHERE chat_id=? AND message_id=?",
    (YO, anchor_id),
)
ok(anchor and anchor["deleted_at"] is None,
   "la tarjeta de la tarea pendiente no cae con A")
ok(any("Cerrado:" in texto and "bañarme" in texto
       for _, texto, _, _ in tg.sent),
   "queda el mensaje de cierre con el nombre de A")

guardian.tick([])
rt.flush_outbox()
nuevo_id = db.get_state("guardian_queue_message_id")
ok(any(mid == nuevo_id and "preparar comida" in texto
       for mid, texto, _, _ in tg.sent),
   "la decision de B llega como tarjeta nueva, que suena")
viejo = db.one(
    "SELECT deleted_at FROM telegram_messages WHERE chat_id=? AND message_id=?",
    (YO, anchor_id),
)
ok(viejo and viejo["deleted_at"] is not None, "y la tarjeta anterior se retira")
ok(db.get_state(PANEL_MESSAGE_KEY) is not None,
   "el panel único permanece al final")
db.close()


print("\n=== 2. Vigia cierra sin dejar rastro de la sesión ===")
db, rt, tg = montar()
vigia = rt.modules["vigia"]
vigia.handle_command("/vigia", "/vigia ordenar el escritorio")
rt.flush_outbox()
session = vigia._session()
flow_vigia = f"vigia:{session.event_id}"

vigia._directo("Analizando el avance.", messages.VIGIA_BOTONES_ESPERA)
with db.transaction():
    vigia._say("Este mensaje todavía no salió.", messages.VIGIA_BOTONES_ESPERA)

ok(db.one("SELECT 1 FROM outbox WHERE flow_key=? AND sent_at IS NULL",
          (flow_vigia,)) is not None,
   "Vigia tiene también un mensaje pendiente de la sesión")

vigia.handle_command("/vigia_cerrar", "/vigia_cerrar")
rt.flush_outbox()

ok(db.one("SELECT 1 FROM outbox WHERE flow_key=? AND sent_at IS NULL",
          (flow_vigia,)) is None,
   "al cerrar cancela todo lo que Vigia aún no había enviado")
ok(not db.query(
    "SELECT message_id FROM telegram_messages "
    "WHERE flow_key=? AND deleted_at IS NULL", (flow_vigia,)
), "al cerrar elimina todo lo que Vigia ya había mostrado")
ok(not any(texto in (messages.VIGIA_CERRADO, messages.VIGIA_CANCELADO)
           for _, texto, _, _ in tg.sent),
   "Vigia no agrega un mensaje histórico de cierre")
ok(not vigia._session(), "la sesión queda realmente cerrada")
ok(db.get_state(PANEL_MESSAGE_KEY) is not None,
   "sólo el panel general puede permanecer")

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
