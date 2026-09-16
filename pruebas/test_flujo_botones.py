"""Los cuatro bugs del flujo SIGUIENTE / RECALIBRAR. Regresion permanente."""
import os, sys, dataclasses, json
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")
import config as cm, messages
from database import Database
from core.router import Router
from modules.vigia import VigiaModule, _leer_fotos
from modules.panel import PanelModule

YO = "999"
TMP = Path(os.environ["TEMP"]) / "flujo.db"; TMP.unlink(missing_ok=True)
F = Path(os.environ["TEMP"]) / "flujo_fotos"; F.mkdir(exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP, evidence_dir=F)
db = Database(cfg.db_path, cfg.schema_path); db.migrate()
FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

class Vis:
    enabled = True
    def __init__(s): s.r = []; s.prompts = []; s.imgs = []
    def planificar(s, path, prompt, context=None):
        s.prompts.append(prompt); s.imgs.append(path)
        d = s.r.pop(0) if s.r else {"decision": "TECHNICAL_ERROR", "reason": "503"}
        # Contrato nuevo: la estrategia ES la lista de bloques y el primero
        # es el de ahora. Los fixtures viejos traen "bloque" aparte.
        if isinstance(d, dict) and d.get("bloque"):
            d = dict(d)
            resto = [x for x in (d.get("estrategia") or []) if x != d["bloque"]]
            d["estrategia"] = [d["bloque"]] + resto
        return d
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

vis = Vis(); tg = TG()
vigia = VigiaModule(cfg, db, tg, vis, Nada()); panel = PanelModule(cfg, db)
mods = {"vigia": vigia, "panel": panel}
for k in ("timer","system","pomodoro","gmail","guardian","calendar","lite","intervalos"):
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
def limpiar_todo(): tg.directos.clear(); out()

E = ["basura", "ropa", "superficies"]
def plan(b, estado="EN_RUTA", **kw):
    d = {"estado": estado, "estrategia": E, "bloque": b, "nota": "", "estimacion": ""}
    d.update(kw); return d

r.process(msg("/vigia ordenar la pieza", 1))
vis.r.append(plan("Saca la basura."))
r.process(foto(2, "a")); limpiar_todo()

print("=== BUG: RECALIBRAR sale directo, no por la outbox ===")
r.process(cb("/vigia_bloque_ok"))
ok(any("foto del estado actual" in t for t, _ in tg.directos), "el pedido sale directo")
ok(not out(), "y NO queda encolado detras de nada")
limpiar_todo()

print("\n=== BUG: avanzar no puede repetir ni devolver el bloque anterior ===")
plan_guardado = json.loads(ses()["estrategia"])
llamadas = len(vis.prompts)
vistos = []
for _ in range(len(plan_guardado) - 1):
    r.process(cb("/vigia_siguiente")); vistos.append(ses()["bloque"])
ok(len(vistos) == len(set(vistos)), f"ningun bloque se repite ({vistos})")
ok(vistos == plan_guardado[1:], "y salen en el orden del plan")
ok(len(vis.prompts) == llamadas, "sin consultar al modelo, asi que no puede equivocarse")
limpiar_todo()

print("\n=== BUG: si falla el analisis con foto, reintenta la MISMA foto ===")
r.process(foto(3, "b"))                     # sin respuestas -> falla
filas = out()
ok(any("No pude analizar" in (x["text"] or "") for x in filas), "avisa el fallo")
f = [x for x in filas if x["buttons"]][-1]
ok(btns(f)[0] == "/vigia_reintentar", f"REINTENTAR reanaliza esa foto ({btns(f)})")
ok(_leer_fotos(ses()["ultima_foto"])[-1].endswith("b.jpg"),
   "que quedo guardada")
limpiar_todo()

db.close(); TMP.unlink(missing_ok=True)
for x in F.glob("*"): x.unlink(missing_ok=True)
print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
