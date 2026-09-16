"""La cola por el router real: callbacks cola:, formulario del panel, comandos."""
import os, sys, dataclasses
from pathlib import Path
from datetime import datetime, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")
import config as cm, messages
import core.scheduler as sched, modules.guardian as G
from database import Database
from core.router import Router
from modules.guardian import GuardianModule
from modules.panel import PanelModule
from modules.intervalos import IntervalosModule

BASE = datetime.now().astimezone().replace(microsecond=0)
RELOJ = {"t": BASE}
def ahora(): return RELOJ["t"]
sched.now_local = ahora; G.now_local = ahora

TMP = Path(os.environ["TEMP"]) / "cola_router.db"; TMP.unlink(missing_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id="999", db_path=TMP)
db = Database(cfg.db_path, cfg.schema_path); db.migrate()

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

def out():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL")
    return [x["text"] or "" for x in f]

class TG:
    def __init__(self): self.answered = []
    def answer_callback(self, cid, text="", show_alert=False): self.answered.append(cid)
    def send_message(self, *a, **k): return {"ok": True}

class Nada:
    def handle_command(self, *a, **k): return False
    def stop(self, *a, **k): pass
    def restore_calendar(self, *a, **k): pass
    def matches(self, *a, **k): return False
    def handle_message(self, *a, **k): return False
    def handle_text(self, *a, **k): return False
    def handle_photo(self, *a, **k): return False

guardian = GuardianModule(cfg, db)
panel = PanelModule(cfg, db)
mods = {"panel": panel, "guardian": guardian, "intervalos": IntervalosModule(cfg, db),
        "timer": Nada(), "system": Nada(), "pomodoro": Nada(),
        "gmail": Nada(), "calendar": Nada(), "lite": Nada(), "vigia": Nada()}
tg = TG()
r = Router(cfg, db, tg, mods); panel.attach(r)

def ev(eid, t, m=0): return {"id": eid, "title": f"** {t}", "start": RELOJ["t"] + timedelta(minutes=m)}
def msg(t, mid=1): return {"message": {"message_id": mid, "chat": {"id": "999"}, "from": {"id": "999"}, "text": t}}
def cbq(data, mid=7): return {"callback_query": {"id": "c1", "data": data, "from": {"id": "999"},
                                                 "message": {"message_id": mid, "chat": {"id": "999"}}}}
def rid(eid): return db.one("SELECT rowid r FROM guardian_events WHERE event_id=?", (eid,))["r"]
def fase(eid):
    x = db.one("SELECT phase FROM guardian_events WHERE event_id=?", (eid,)); return x["phase"] if x else None

print("=== router despacha los callbacks cola: ===")
guardian.tick([ev("A", "uno")]); guardian.tick([ev("B", "dos")]); out()
guardian.handle_command("/listo", "/listo"); guardian.tick([]); out()
ok(fase("B") == "decision", "hay una decision pendiente")

r.process(cbq(f"cola:despues:{rid('B')}"))
ok(tg.answered == ["c1"], "responde el callback (sin spinner)")
ok(any("final de la cola" in x for x in out()), "DESPUES pasa por el router")
ok(fase("B") == "queued", "B vuelve a la cola")
RELOJ["t"] = RELOJ["t"] + timedelta(minutes=16)
guardian.tick([]); out()
ok(fase("B") == "decision", "y a los ~15 min se vuelve a presentar")

print("\n=== usuario ajeno no puede tocar la cola ===")
r.process({"callback_query": {"id": "c2", "data": f"cola:descartar:{rid('B')}",
                              "from": {"id": "555"}, "message": {"message_id": 7, "chat": {"id": "555"}}}})
ok(fase("B") == "decision", "un ajeno no descarta nada")
ok(not out(), "y no genera mensajes")

print("\n=== el panel ya no tiene formulario de reagendar ===")
from modules.panel import PIDEN_TEXTO
ok(not any(k.startswith("panel:cola") for k in PIDEN_TEXTO),
   f"sin flujos panel:cola en el panel: {[k for k in PIDEN_TEXTO if 'cola' in k]}")
r.process(cbq("panel:cola:manana")); t = out()
ok(not any("Hora" in x or "hora" in x for x in t), "ese callback ya no pide nada")
ok(fase("B") == "decision", "y no cambia el evento pendiente")

print("\n=== DESCARTAR por el router ===")
r.process(cbq(f"cola:descartar:{rid('B')}"))
ok(fase("B") == "discarded", "DESCARTAR cierra por el router")
ok(any("descartado" in x for x in out()), "y lo avisa")

db.close(); TMP.unlink(missing_ok=True)
print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
