"""429 de Gemini: cuota, no saturacion. No reintentar a ciegas."""
import os, sys, dataclasses, json
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")
import config as cm, messages
import core.scheduler as sched, modules.vigia as V
from database import Database
from core.router import Router
from modules.vigia import VigiaModule, CUOTA_KEY, _espera_de_cuota
from modules.panel import PanelModule

BASE = datetime.now().astimezone().replace(microsecond=0)
RELOJ = {"t": BASE}
def ahora(): return RELOJ["t"]
def avanzar(seg): RELOJ["t"] = RELOJ["t"] + timedelta(seconds=seg)
sched.now_local = ahora; V.now_local = ahora

YO = "999"
TMP = Path(os.environ["TEMP"]) / "cuota.db"; TMP.unlink(missing_ok=True)
F = Path(os.environ["TEMP"]) / "cuota_fotos"; F.mkdir(exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP, evidence_dir=F)
db = Database(cfg.db_path, cfg.schema_path); db.migrate()
FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

CUERPO_429 = ('Gemini HTTP 429: {"error": {"code": 429, "message": "You exceeded your '
              'current quota... * Quota exceeded for metric: '
              'generate_content_free_tier_requests, limit: 20, model: gemini-2.5-flash'
              '\nPlease retry in 38.899020129s.", "status": "RESOURCE_EXHAUSTED"}}')

class Vis:
    enabled = True
    def __init__(s): s.r = []; s.llamadas = 0
    def planificar(s, path, prompt, context=None):
        s.llamadas += 1
        d = s.r.pop(0) if s.r else {"decision": "TECHNICAL_ERROR", "reason": "x"}
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
        s.directos.append(text); return {"ok": True}
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
def txt(): return " ".join(x["text"] or "" for x in out())
def msg(t, m): return {"message": {"message_id": m, "chat": {"id": YO}, "from": {"id": YO}, "text": t}}
def cb(d, m=7): return {"callback_query": {"id": "c", "data": d, "from": {"id": YO},
                                           "message": {"message_id": m, "chat": {"id": YO}}}}
def foto(m, f): return {"message": {"message_id": m, "chat": {"id": YO}, "from": {"id": YO},
                                    "photo": [{"file_id": f}]}}
E = ["basura", "ropa"]
def plan(b): return {"estado": "EN_RUTA", "estrategia": E, "bloque": b, "nota": "", "estimacion": ""}

print("=== parseo del 429 ===")
ok(_espera_de_cuota(CUERPO_429) == 39, f"lee los segundos que pide la API ({_espera_de_cuota(CUERPO_429)})")
ok(_espera_de_cuota("Gemini HTTP 503: saturado") is None, "un 503 no es cuota")
ok(_espera_de_cuota("Gemini error: The read operation timed out") is None, "un timeout tampoco")

print("\n=== el 429 se explica como cuota, no como saturacion ===")
r.process(msg("/vigia ordenar", 1)); out(); tg.directos.clear()
vis.r.append({"decision": "TECHNICAL_ERROR", "reason": CUERPO_429})
r.process(foto(2, "a"))
t = txt()
ok("cuota diaria" in t, "lo llama cuota DIARIA")
ok("20 consultas por día" in t, "con el limite que reporta la API")
ok("saturado" not in t, "NO lo llama saturacion")
ok("se reinicia mañana" in t, "y dice cuando vuelve, no unos segundos")

print("\n=== reintentar dentro de la ventana NO llama a Gemini ===")
llamadas = vis.llamadas
tg.directos.clear()
r.process(cb("/vigia_reintentar"))
ok(vis.llamadas == llamadas, "no gasto una consulta")
t = txt()
ok("cuota diaria" in t, "y lo explica igual")
ok(not any(messages.VIGIA_PENSANDO in d for d in tg.directos),
   "ni promete un analisis que no va a pasar")
for _ in range(5): r.process(cb("/vigia_reintentar")); out()
ok(vis.llamadas == llamadas, "cinco reintentos mas siguen sin gastar nada")

print("\n=== pasada la ventana, vuelve a funcionar ===")
avanzar(40)
vis.r.append(plan("Saca la basura."))
r.process(cb("/vigia_reintentar"))
ok(vis.llamadas == llamadas + 1, "ahora si llama")
ok("Saca la basura" in txt(), "y entrega el bloque")

print("\n=== 503 y timeout siguen diciendo lo suyo ===")
vis.r.append({"decision": "TECHNICAL_ERROR", "reason": "Gemini HTTP 503: high demand"})
r.process(foto(20, "s")); t = txt()
ok("saturado" in t, "el 503 si es saturacion")
ok("límite de consultas" not in t, "y no se confunde con cuota")
vis.r.append({"decision": "TECHNICAL_ERROR", "reason": "Gemini error: The read operation timed out"})
r.process(foto(21, "t")); t = txt()
ok("tardó demasiado" in t, "el timeout se nombra como tal")

print("\n=== la cuota sobrevive el reinicio del proceso ===")
vis.r.append({"decision": "TECHNICAL_ERROR", "reason": CUERPO_429})
r.process(foto(22, "u")); out()
v2 = VigiaModule(cfg, db, tg, vis, Nada())
ok(v2._cuota_restante() > 0, "otro proceso ve la ventana igual")
llamadas = vis.llamadas
v2.handle_photo(foto(23, "v")["message"]); out()
ok(vis.llamadas == llamadas, "y tampoco gasta consultas")

db.close(); TMP.unlink(missing_ok=True)
for x in F.glob("*"): x.unlink(missing_ok=True)
print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
