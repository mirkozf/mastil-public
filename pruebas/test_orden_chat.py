"""Retencion del chat: tres mensajes recientes y un panel."""

import dataclasses
import os
import sys
from datetime import timedelta, timezone
from pathlib import Path

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
from core.message_policy import MessagePolicy
from database import Database

YO = "999"
ASISTIDA = "222"
TMP = Path(os.environ["TEMP"]) / "orden_chat" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
TMP.unlink(missing_ok=True)
cfg = dataclasses.replace(cm.load(), db_path=TMP)
db = Database(cfg.db_path, cfg.schema_path)
db.migrate()

FALLAS = 0


def ok(condicion, texto):
    global FALLAS
    print(f"  {'ok  ' if condicion else 'MAL '} {texto}")
    if not condicion:
        FALLAS += 1


class Telegram:
    def __init__(self):
        self.lotes = []
        self.paneles = []
        self.editados = []

    def set_message_observer(self, observer):
        self.observer = observer

    def delete_messages(self, chat_id, ids):
        self.lotes.append((str(chat_id), list(ids)))

    def delete_message(self, chat_id, message_id):
        self.paneles.append((str(chat_id), int(message_id)))

    def edit_message(self, chat_id, message_id, text, buttons=None):
        self.editados.append((str(chat_id), int(message_id), text))


class Panel:
    def __init__(self):
        self.recreados = []

    def recreate_current(self, chat_id):
        self.recreados.append(str(chat_id))


tg = Telegram()
panel = Panel()
policy = MessagePolicy(db, tg, YO)
policy.bind(tg)

print("=== 1. conserva tres y borra el resto ===")
policy.record(YO, 100, direction="outgoing", kind="text", is_panel=True)
with db.transaction():
    db.set_state("panel_message_id", 100)
for message_id in range(101, 106):
    policy.record_incoming(YO, message_id)

creado = policy.reconcile(panel)
ok(tg.lotes == [(YO, [102, 101])], "borro solo los dos mas antiguos")
ok(tg.paneles == [(YO, 100)], "borro el panel que quedo arriba")
ok(panel.recreados == [YO] and creado, "pidio un unico panel nuevo")

visibles = db.query(
    "SELECT message_id FROM telegram_messages "
    "WHERE chat_id=? AND is_panel=0 AND deleted_at IS NULL "
    "ORDER BY message_id", (YO,))
ok([r["message_id"] for r in visibles] == [103, 104, 105],
   "la base deja exactamente los tres recientes")

print("\n=== 2. si el panel ya esta abajo no lo duplica ===")
policy.record(YO, 200, direction="outgoing", kind="text", is_panel=True)
with db.transaction():
    db.set_state("panel_message_id", 200)
policy.record_incoming(YO, 106)
creado = policy.reconcile(panel)
ok(not creado, "no recreo un panel que ya estaba al final")
ok(tg.paneles == [(YO, 100)], "no borro el panel vigente")

print("\n=== 3. la usuaria asistida queda completamente fuera ===")
antes = db.one("SELECT COUNT(*) AS n FROM telegram_messages")["n"]
policy.record_incoming(ASISTIDA, 999)
despues = db.one("SELECT COUNT(*) AS n FROM telegram_messages")["n"]
ok(antes == despues, "no registro ni administra mensajes Lite")

print("\n=== 4. un corte de red nunca duplica el panel ===")


class TelegramCaido(Telegram):
    def delete_message(self, chat_id, message_id):
        raise RuntimeError("sin red")

    def edit_message(self, chat_id, message_id, text, buttons=None):
        raise RuntimeError("sin red")


caido = TelegramCaido()
policy2 = MessagePolicy(db, caido, YO)
policy2.bind(caido)
policy2.record(YO, 300, direction="outgoing", kind="text", is_panel=True)
with db.transaction():
    db.set_state("panel_message_id", 300)
policy2.record_incoming(YO, 301)
panel2 = Panel()
creado = policy2.reconcile(panel2)
ok(not creado and not panel2.recreados,
   "si no pudo retirar el viejo, no creo otro")
ok(db.get_state("panel_message_id") == 300,
   "conservo el rastro para reintentar despues")

print("\n=== 5. una pantalla protegida no se borra ===")
policy3 = MessagePolicy(db, tg, YO)
policy3.bind(tg)
policy3.record(
    YO, 400, direction="outgoing", kind="text", is_panel=False,
    protected=True,
)
for message_id in range(401, 406):
    policy3.record_incoming(YO, message_id)
policy3.reconcile(panel)
protegida = db.one(
    "SELECT deleted_at FROM telegram_messages WHERE chat_id=? AND message_id=400",
    (YO,),
)
ok(protegida is not None and protegida["deleted_at"] is None,
   "conservo la pantalla protegida aunque hubiera mas de tres mensajes")
policy3.set_protected(YO, 400, False)
policy3.reconcile(panel)
protegida = db.one(
    "SELECT deleted_at FROM telegram_messages WHERE chat_id=? AND message_id=400",
    (YO,),
)
ok(protegida is not None and protegida["deleted_at"] is not None,
   "al desprotegerla vuelve a la limpieza normal")

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
