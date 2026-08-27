"""SIGUIENTE sin foto como camino normal, y foto opcional para recalibrar.
Ademas: limite de Gmail por opcion."""
import os, sys, dataclasses, json
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")
import config as cm, messages
import core.scheduler as sched, modules.gmail as G
from database import Database
from core.router import Router
from modules.vigia import VigiaModule
from modules.gmail import GmailModule, CONTADOR_KEY
from modules.panel import PanelModule

BASE = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
RELOJ = {"t": BASE}
def ahora(): return RELOJ["t"]
sched.now_local = ahora; G.now_local = ahora

YO = "999"
TMP = Path(os.environ["TEMP"]) / "sig.db"; TMP.unlink(missing_ok=True)
F = Path(os.environ["TEMP"]) / "sig_fotos"; F.mkdir(exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP, evidence_dir=F)
db = Database(cfg.db_path, cfg.schema_path); db.migrate()

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

class Vis:
    enabled = True
    def __init__(s): s.r = []; s.prompts = []; s.imagenes = []
    def planificar(s, path, prompt, context=None):
        s.prompts.append(prompt); s.imagenes.append(path)
        d = s.r.pop(0) if s.r else {"decision": "TECHNICAL_ERROR"}
        # Contrato nuevo: la estrategia ES la lista de bloques y el primero
        # es el de ahora. Los fixtures viejos traen "bloque" aparte.
        if isinstance(d, dict) and d.get("bloque"):
            d = dict(d)
            resto = [x for x in (d.get("estrategia") or []) if x != d["bloque"]]
            d["estrategia"] = [d["bloque"]] + resto
        return d
    def evaluar_texto(s, prompt):
        s.prompts.append(prompt); return {"ok": True, "texto": "ya usaste las dos", "error": ""}

class Puente:
    enabled = True
    def __init__(s): s.llamadas = []
    def count_unread(s): s.llamadas.append("count"); return 3
    def list_unread(s, limit=10):
        s.llamadas.append("list")
        return [{"id": "m1", "from": "e@x.cl", "subject": "s", "date": "d"}]
    def get_content(s, mid, max_chars=60000):
        s.llamadas.append("content")
        return {"from": "e@x.cl", "subject": "s", "date": "d", "body": "b", "truncated": False}

class TG:
    def __init__(s): s.directos = []
    def send_message(s, chat, text, buttons=None, parse_mode=None):
        s.directos.append((text, buttons)); return {"ok": True}
    def answer_callback(s, *a, **k): pass
    def download_photo(s, fid, dest):
        p = Path(dest) / f"{fid}.jpg"; p.write_bytes(b"x"); return p

class Nada:
    enabled = False
    def __getattr__(s, n): return lambda *a, **k: False

vis = Vis(); tg = TG(); puente = Puente()
vigia = VigiaModule(cfg, db, tg, vis, Nada())
gmail = GmailModule(cfg, db, puente, tg, vis)
panel = PanelModule(cfg, db)
mods = {"vigia": vigia, "panel": panel, "gmail": gmail}
for k in ("timer", "system", "pomodoro", "guardian", "calendar", "lite", "intervalos"):
    mods[k] = Nada()
r = Router(cfg, db, tg, mods); panel.attach(r)

def out():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL"); return f
def btns(f): return [b[1] for g in json.loads(f["buttons"]) for b in g] if f and f["buttons"] else []
def msg(t, m): return {"message": {"message_id": m, "chat": {"id": YO}, "from": {"id": YO}, "text": t}}
def cb(d, m=7): return {"callback_query": {"id": "c", "data": d, "from": {"id": YO},
                                           "message": {"message_id": m, "chat": {"id": YO}}}}
def foto(m, f): return {"message": {"message_id": m, "chat": {"id": YO}, "from": {"id": YO},
                                    "photo": [{"file_id": f}]}}
def ses(): return db.one("SELECT * FROM vigia_session WHERE id=1")
def directos():
    d = list(tg.directos); tg.directos.clear(); return d
def texto_directo(): return " ".join(t for t, _ in directos())
def btn_directo():
    d = [x for x in tg.directos if x[1]]
    return [b[1] for g in d[-1][1] for b in g] if d else []

E = ["basura", "ropa", "superficies"]
def plan(bloque, estado="EN_RUTA", **kw):
    d = {"estado": estado, "estrategia": E, "bloque": bloque, "nota": "", "estimacion": ""}
    d.update(kw); return d


print("=== SIGUIENTE ya NO llama al modelo ===")
r.process(msg("/vigia ordenar la pieza", 1)); out()
vis.r.append(plan("Saca la basura. No toques la ropa."))
r.process(foto(2, "a")); f = out()[-1]
ok(btns(f) == ["/vigia_siguiente", "/vigia_bloque_ok", "/vigia_trabado", "panel:home"],
   f"SIGUIENTE primero ({btns(f)})")
llamadas = len(vis.prompts)
r.process(cb("/vigia_siguiente")); out()
r.process(cb("/vigia_siguiente")); out()
ok(len(vis.prompts) == llamadas, "dos avances, cero consultas")
directos()

print("\n=== RECALIBRAR pide la foto, directo y en el acto ===")
r.process(cb("/vigia_bloque_ok"))
ok(any("foto del estado actual" in t for t, _ in tg.directos),
   "sale directo, no por la outbox")
ok(not out(), "y nada quedo encolado")
directos()

# ======================================================================
print("\n=== GMAIL: cada opcion tiene su propio par ===")
def usos(cmd):
    e = db.get_state(CONTADOR_KEY) or {}
    if e.get("fecha") != ahora().strftime("%Y-%m-%d"): return 0
    return int((e.get("usos", {}).get(cmd) or {}).get("n", 0))

r.process(msg("/gmail_hay", 20)); out()
r.process(msg("/gmail_hay", 21)); out()
ok(usos("/gmail_hay") == 2, "hay: 2/2")
ok(usos("/gmail_remitentes") == 0, "remitentes sigue en 0/2")

llamadas = len(puente.llamadas)
r.process(msg("/gmail_hay", 22)); f = out()[-1]
ok("¿hay correos?" in (f["text"] or ""), f"hay agotado, y dice cual ({f['text'][:60]})")
ok(len(puente.llamadas) == llamadas, "no consulto")

r.process(msg("/gmail_remitentes", 23))
ok(any("Remitentes" in (x["text"] or "") for x in out()), "remitentes SI funciona")
ok(usos("/gmail_remitentes") == 1, "y cuenta aparte (1/2)")
r.process(msg("/gmail_remitentes", 24)); out()
ok(usos("/gmail_remitentes") == 2, "2/2")

print("\n=== y el contenido queda accesible ===")
llamadas = len(puente.llamadas)
r.process(msg("/gmail_contenido 1 natural", 25))
ok(any("Correo 1" in (x["text"] or "") for x in out()), "el contenido se abre")
ok(len(puente.llamadas) == llamadas + 1, "y consulta de verdad")
ok(usos("/gmail_hay") == 2 and usos("/gmail_remitentes") == 2, "sin gastar revisiones")

print("\n=== la friccion nombra la consulta correcta ===")
r.process(msg("/gmail_remitentes", 26)); out()
r.process(cb("/gmail_igual")); out()
r.process(cb("panel:gm:motivo")); out()
r.process(msg("quiero ver si respondio", 27)); out()
ok("CONSULTA QUE QUIERE HACER: remitentes" in vis.prompts[-1],
   "Gemini sabe cual consulta se agoto")

print("\n=== dia nuevo, los dos contadores vuelven a 0 ===")
RELOJ["t"] = BASE + timedelta(days=1)
ok(usos("/gmail_hay") == 0 and usos("/gmail_remitentes") == 0, "ambos en 0")

db.close(); TMP.unlink(missing_ok=True)
for x in F.glob("*"): x.unlink(missing_ok=True)
print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
