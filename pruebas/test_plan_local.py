"""El plan entero viene en la primera foto. Avanzar NO llama al modelo."""
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
from modules.vigia import VigiaModule, CUOTA_KEY
from modules.panel import PanelModule

BASE = datetime.now().astimezone().replace(microsecond=0)
RELOJ = {"t": BASE}
def ahora(): return RELOJ["t"]
def avanzar(**kw): RELOJ["t"] = RELOJ["t"] + timedelta(**kw)
sched.now_local = ahora; V.now_local = ahora

YO = "999"
TMP = Path(os.environ["TEMP"]) / "planloc.db"; TMP.unlink(missing_ok=True)
F = Path(os.environ["TEMP"]) / "planloc_fotos"; F.mkdir(exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP, evidence_dir=F)
db = Database(cfg.db_path, cfg.schema_path); db.migrate()

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

class Vis:
    enabled = True
    def __init__(s): s.r = []; s.prompts = []; s.llamadas = 0
    def planificar(s, path, prompt, context=None):
        s.llamadas += 1; s.prompts.append(prompt)
        return s.r.pop(0) if s.r else {"decision": "TECHNICAL_ERROR", "reason": "x"}
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
def btns(f): return [b[1] for g in json.loads(f["buttons"]) for b in g] if f and f["buttons"] else []
def msg(t, m): return {"message": {"message_id": m, "chat": {"id": YO}, "from": {"id": YO}, "text": t}}
def cb(d, m=7): return {"callback_query": {"id": "c", "data": d, "from": {"id": YO},
                                           "message": {"message_id": m, "chat": {"id": YO}}}}
def foto(m, f): return {"message": {"message_id": m, "chat": {"id": YO}, "from": {"id": YO},
                                    "photo": [{"file_id": f}]}}
def ses(): return db.one("SELECT * FROM vigia_session WHERE id=1")

PLAN4 = ["Recoge toda la basura visible. No toques todavia la ropa.",
         "Junta toda la ropa en un punto. No ordenes todavia el escritorio.",
         "Despeja el escritorio: deja solo lo de uso diario.",
         "Barre el piso."]
def resp(plan, estado="EN_RUTA", **kw):
    d = {"estado": estado, "estrategia": plan, "nota": "", "estimacion": "2-3 h"}
    d.update(kw); return d


print("=== la primera foto trae el PLAN COMPLETO ===")
r.process(msg("/vigia ordenar la pieza", 1)); out()
vis.r.append(resp(PLAN4))
r.process(foto(2, "a"))
ok(vis.llamadas == 1, "una sola llamada")
plan = json.loads(ses()["estrategia"])
ok(plan == PLAN4, f"guarda los 4 bloques ({len(plan)})")
t = txt()
ok("Recoge toda la basura" in t, "muestra el primero")
ok("(1 de 4)" in t, f"y en que punto del plan estas")
ok("Junta toda la ropa" not in t, "sin mostrar los otros tres")
ok("2-3 h" in t, "con la estimacion")

print("\n=== avanzar NO llama al modelo ===")
for n, esperado in [(2, "Junta toda la ropa"), (3, "Despeja el escritorio"), (4, "Barre el piso")]:
    r.process(cb("/vigia_siguiente"))
    t = txt()
    ok(esperado in t, f"bloque {n}: {esperado[:22]}")
    ok(f"({n} de 4)" in t, f"  numerado ({n} de 4)")
ok(vis.llamadas == 1, f"CERO consultas extra en 3 avances (total {vis.llamadas})")
ok(not any(messages.VIGIA_PENSANDO in d for d in tg.directos),
   "ni promete pensar: es instantaneo")

print("\n=== al acabarse el plan ofrece cerrar, sin exigir foto ===")
r.process(cb("/vigia_siguiente"))
f = out()[-1]
ok(messages.VIGIA_PLAN_TERMINADO in (f["text"] or ""), "avisa que se acabo el plan")
ok(vis.llamadas == 1, "sin llamar al modelo")
ok(ses()["active"] == 1, "y NO cierra solo")
ok("/vigia_cerrar" in btns(f), "pero CERRAR queda a mano: la foto final no es requisito")

print("\n=== la foto de cierre lleva a COMPLETADO; cerrar es un paso aparte ===")
vis.r.append(resp([], estado="COMPLETADO"))
r.process(foto(3, "b"))
f = out()[-1]
ok("OBJETIVO COMPLETADO" in (f["text"] or ""), "avisa el cierre")
ok(ses()["active"] == 1 and ses()["stage"] == "cerrando", "espera el registro opcional")
ok(btns(f) == ["/vigia_registrar", "/vigia_cerrar", "panel:home"],
   f"REGISTRAR / CERRAR / PANEL ({btns(f)})")
r.process(cb("/vigia_cerrar")); out()
ok(ses()["active"] == 0, "cerrar sin foto final cierra la sesion")
ok(db.one("SELECT COUNT(*) c FROM vigia_completed_events")["c"] >= 1,
   "y queda anotada como cumplida")
ok(vis.llamadas == 2, f"la tarea entera costo 2 consultas ({vis.llamadas})")

print("\n=== consumo: 4 bloques y cierre = 2 consultas ===")
ok(vis.llamadas == 2, "confirmado")

print("\n=== RECALIBRAR reescribe el plan y reinicia el indice ===")
vis.llamadas = 0
r.process(msg("/vigia ordenar cocina", 10)); out()
vis.r.append(resp(PLAN4)); r.process(foto(11, "c")); out()
r.process(cb("/vigia_siguiente")); out()
ok(len(json.loads(ses()["declarados"])) == 1, "un bloque declarado")
NUEVO = ["Saca la loza al lavaplatos.", "Limpia la mesa."]
vis.r.append(resp(NUEVO))
r.process(foto(12, "d"))
t = txt()
ok(json.loads(ses()["estrategia"]) == NUEVO, "el plan se reemplaza por el nuevo")
ok(json.loads(ses()["declarados"]) == [], "los declarados se vacian")
ok("Saca la loza" in t and "(1 de 2)" in t, f"y arranca en 1 de 2")
r.process(cb("/vigia_siguiente")); t = txt()
ok("Limpia la mesa" in t and "(2 de 2)" in t, "avanza en el plan nuevo")

print("\n=== el prompt lleva el plan vigente y lo declarado ===")
p = vis.prompts[-1]
ok("PLAN VIGENTE" in p, "declara el plan vigente")
ok("Recoge toda la basura" in p, "con sus bloques")
ok("BLOQUES DADOS POR HECHOS SIN COMPROBAR" in p, "y lo declarado sin comprobar")
ok("LA FOTO SIEMPRE GANA" in p, "la foto manda")
ok("2 a 6" in p, "le pide el plan completo, no un bloque")
ok("NO HAY FOTO NUEVA" not in p, "sin la rama vieja de 'sin foto'")

print("\n=== REANUDAR sigue funcionando ===")
r.process(cb("/vigia_bloque"))
ok("Limpia la mesa" in txt(), "devuelve el bloque en curso")

print("\n=== cuota: mensaje diario, sin prometer segundos ===")
CUERPO = ('Gemini HTTP 429: {"error":{"code":429,"message":"...* Quota exceeded for '
          'metric: generate_content_free_tier_requests, limit: 20, model: '
          'gemini-2.5-flash\\nPlease retry in 38.8s."}}')
vis.r.append({"decision": "TECHNICAL_ERROR", "reason": CUERPO})
r.process(foto(13, "e"))
t = txt()
ok("cuota diaria" in t, "lo llama cuota diaria")
ok("20 consultas por día" in t, "con el limite que reporta la API")
ok("se reinicia mañana" in t, "y cuando vuelve")
ok("por minuto" not in t, "NO dice por minuto")
ok("39 segundos" not in t and "38 segundos" not in t, "ni promete segundos")
ok(json.loads(ses()["estrategia"]) == NUEVO, "y no pierde el plan")

print("\n=== avanzar sigue funcionando con la cuota agotada ===")
llamadas = vis.llamadas
r.process(cb("/vigia_siguiente")); out()
ok(vis.llamadas == llamadas, "porque no necesita el modelo")

print("\n=== el plan vigente que ve el modelo son SOLO los que quedan ===")
vis.llamadas = 0
db.set_state(CUOTA_KEY, None)   # la seccion anterior la dejo agotada a proposito
r.process(msg("/vigia_cancelar", 20)); out()
r.process(msg("/vigia ordenar la pieza otra vez", 21)); out()
vis.r.append(resp(PLAN4)); r.process(foto(22, "p1")); out()
r.process(cb("/vigia_siguiente")); out()
r.process(cb("/vigia_siguiente")); out()
ok(len(json.loads(ses()["declarados"])) == 2, "dos bloques declarados")
en_curso = ses()["bloque"]
ok(en_curso == PLAN4[2], "y el tercero en curso")

# El modelo MANTIENE el plan, que es lo que la regla 5 le pide. Los fixtures
# viejos siempre devolvian uno nuevo, y por eso este caso no se probaba.
vis.r.append(resp(PLAN4[2:]))
r.process(foto(23, "p2"))
p = vis.prompts[-1]
bloque_vigente = p.split("PLAN VIGENTE")[1].split("BLOQUE QUE ESTABA")[0]
ok(PLAN4[0] not in bloque_vigente, "el primero, ya hecho, NO va como pendiente")
ok(PLAN4[1] not in bloque_vigente, "el segundo tampoco")
ok(PLAN4[2] in bloque_vigente and PLAN4[3] in bloque_vigente,
   "solo viajan el que esta en curso y el que sigue")
declarados_prompt = p.split("SIN COMPROBAR")[1].split("LA PERSONA DICE")[0]
ok(PLAN4[0] in declarados_prompt and PLAN4[1] in declarados_prompt,
   "los hechos viajan aparte, en su propio campo")

print("\n=== y mantener el plan ya no te devuelve al bloque uno ===")
t = txt()
ok(ses()["bloque"] == en_curso, "sigue en el bloque en curso")
ok(PLAN4[0] not in t, "no vuelve a pedir la basura ya botada")
ok(json.loads(ses()["estrategia"]) == PLAN4[2:], "el plan guardado es lo que queda")
ok(json.loads(ses()["declarados"]) == [], "y los declarados se vacian, ya comprobados")

print("\n=== con el plan terminado, el campo lo dice sin mentir ===")
r.process(cb("/vigia_siguiente")); out()
r.process(cb("/vigia_siguiente")); out()
vis.r.append(resp([], estado="COMPLETADO"))
r.process(foto(24, "p3")); out()
p = vis.prompts[-1]
ok("se hicieron todos los del plan" in p, "no quedan pendientes y lo dice asi")

db.close(); TMP.unlink(missing_ok=True)
for x in F.glob("*"): x.unlink(missing_ok=True)
print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
