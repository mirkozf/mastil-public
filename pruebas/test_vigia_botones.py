"""Cada paso del diagrama de Vigia, por boton. Nada obliga a escribir comandos."""
import os, sys, dataclasses, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")
import config as cm, messages
from database import Database
from core.router import Router
from modules.vigia import VigiaModule
from modules.panel import PanelModule

YO = "999"
TMP = Path(os.environ["TEMP"]) / "vig_btn.db"; TMP.unlink(missing_ok=True)
F = Path(os.environ["TEMP"]) / "vig_btn_fotos"; F.mkdir(exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP, evidence_dir=F)
db = Database(cfg.db_path, cfg.schema_path); db.migrate()

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

class Vis:
    enabled = True
    def __init__(s): s.r = []; s.prompts = []
    def planificar(s, p, prompt, context=None):
        s.prompts.append(prompt)
        d = s.r.pop(0) if s.r else {"decision": "TECHNICAL_ERROR"}
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
for k in ("timer", "system", "pomodoro", "gmail", "guardian",
          "calendar", "lite", "intervalos"):
    mods[k] = Nada()
r = Router(cfg, db, tg, mods); panel.attach(r)

def out():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL"); return f
def btns(f): return [b[1] for g in json.loads(f["buttons"]) for b in g] if f and f["buttons"] else []
def etiq(f): return [b[0] for g in json.loads(f["buttons"]) for b in g] if f and f["buttons"] else []
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

PLAN = {"estado": "EN_RUTA", "estrategia": ["basura", "ropa", "superficies"],
        "bloque": "Recoge la basura visible. No toques todavía la ropa.",
        "nota": "", "estimacion": "1-2 h"}

print("=== VIGÍA -> NUEVA TAREA ===")
r.process(cb("panel:vigia")); f = out()[-1]
ok(etiq(f)[0] == "🎯 NUEVA TAREA", f"primer boton ({etiq(f)})")
ok("panel:vig:ctx" in btns(f), "y hay acceso al contexto")
ok("/vigia_bloque" in btns(f), "y a reanudar el bloque")
r.process(cb("panel:vig:objetivo")); f = out()[-1]
ok(messages.PANEL_VIGIA_OBJETIVO in (f["text"] or ""), "pide el objetivo")

print("\n=== CONTEXTO MÍNIMO, campo por campo ===")
r.process(msg("ordenar la cocina", 1))
f = out()[-1]
ok("CONTEXTO" in (f["text"] or "") and "ordenar la cocina" in (f["text"] or ""),
   "tras el objetivo cae directo en el contexto")
ok(btns(f) == ["panel:vig:ctx:alcance", "panel:vig:ctx:prioridad",
               "panel:vig:ctx:elementos", "panel:vig:ctx:restricciones",
               "panel:vig:foto", "panel:home"],
   f"los 4 campos + FOTO + PANEL ({btns(f)})")
for campo, texto in [("alcance", "toda la cocina"),
                     ("prioridad", "superficies despejadas"),
                     ("elementos", "platos, basura, cajas"),
                     ("restricciones", "no tirar nada dudoso")]:
    r.process(cb(f"panel:vig:ctx:{campo}")); out()
    r.process(msg(texto, 2)); f = out()[-1]
    ok(texto[:12] in " ".join(etiq(f)), f"{campo} queda visible en su boton")
ctx = json.loads(ses()["contexto"])
ok(ctx["alcance"] == "toda la cocina" and ctx["restricciones"] == "no tirar nada dudoso",
   "los cuatro campos guardados")

print("\n=== FOTO ===")
r.process(cb("panel:vig:foto")); f = out()[-1]
ok("Manda la foto" in (f["text"] or ""), "dice que mande la foto")
ok(btns(f) == ["panel:vig:ctx", "panel:home"], f"y deja volver al contexto ({btns(f)})")
vis.r.append(PLAN); r.process(foto(3, "a"))
p = vis.prompts[-1]
ok("Alcance: toda la cocina" in p and "Restricciones: no tirar nada dudoso" in p,
   "el contexto estructurado llega al modelo")
f = out()[-1]
ok("Recoge la basura" in (f["text"] or ""), "entrega el bloque")

print("\n=== SIGUIENTE PASO -> botones de ejecucion ===")
ok(btns(f) == ["/vigia_siguiente", "/vigia_bloque_ok", "/vigia_trabado", "panel:home"],
   f"SIGUIENTE / RECALIBRAR / ME TRABÉ / PANEL ({btns(f)})")

print("\n=== RECALIBRAR pide la foto, no avanza solo ===")
antes = ses()["bloque"]
directos()
r.process(cb("/vigia_bloque_ok"))
ok(any("foto del estado actual" in t for t, _ in tg.directos), "pide la foto, directo")
ok(ses()["bloque"] == antes, "y NO avanza el bloque por si solo")
ok(btn_directo() == ["/vigia_siguiente", "/vigia_trabado", "panel:home"],
   f"salidas ({btn_directo()})")
directos(); out()

print("\n=== ME TRABÉ ===")
r.process(cb("/vigia_trabado")); f = out()[-1]
ok(ses()["trabado"] == 1 and "foto" in (f["text"] or "").lower(), "marca y pide foto")
ok(btns(f) == ["/vigia_bloque", "panel:home"], f"salidas ({btns(f)})")
r.process(cb("/vigia_bloque")); out()
ok(ses()["trabado"] == 0, "VOLVER AL BLOQUE es la salida sin foto y levanta el trabado")

print("\n=== DATOS INSUFICIENTES -> RESPONDER -> reanaliza la MISMA foto ===")
vis.r.append({"estado": "FALTA_CONTEXTO", "estrategia": [], "bloque": "",
              "pregunta": "¿La caja del rincón es basura o hay que guardarla?",
              "nota": "", "estimacion": ""})
r.process(foto(4, "b"))
f = out()[-1]
ok("DATOS INSUFICIENTES" in (f["text"] or ""), "avisa que faltan datos")
ok("La caja del rincón" in (f["text"] or ""), "con la pregunta concreta")
ok(btns(f) == ["panel:vig:aclarar", "/vigia_otra_foto", "panel:home"],
   f"RESPONDER / OTRA FOTO / PANEL ({btns(f)})")
ok(ses()["ultima_foto"].endswith("b.jpg"), "guarda la foto para reanalizarla")
ok(ses()["bloque"] == antes, "y no pierde el bloque")
llamadas = len(vis.prompts)
r.process(cb("panel:vig:aclarar")); out()
vis.r.append(PLAN)
r.process(msg("es basura, tirala", 5))
ok(len(vis.prompts) == llamadas + 1, "reanaliza sin pedir otra foto")
ok("es basura, tirala" in vis.prompts[-1], "con la aclaracion incluida")
ok("Recoge la basura" in " ".join(x["text"] or "" for x in out()), "y entrega bloque")

print("\n=== OTRA FOTO tambien es boton ===")
directos()
r.process(cb("/vigia_otra_foto"))
ok(any("otra foto" in t.lower() for t, _ in tg.directos), "pide otra foto, directo")
directos()

print("\n=== DERIVA con sus botones ===")
vis.r.append({"estado": "DERIVA", "estrategia": ["basura", "ropa"],
              "bloque": "Vuelve a la ropa.",
              "nota": "El escritorio pertenece a una fase posterior.", "estimacion": ""})
r.process(foto(6, "c")); f = out()[-1]
ok("TE ESTÁS DESVIANDO" in (f["text"] or ""), "avisa deriva")
ok(btns(f) == ["/vigia_siguiente", "/vigia_bloque_ok", "/vigia_trabado", "panel:home"], "con los mismos botones")

print("\n=== COMPLETADO ofrece registrar, y no cierra solo ===")
vis.r.append({"estado": "COMPLETADO", "estrategia": [], "bloque": "listo",
              "nota": "", "estimacion": ""})
r.process(foto(7, "d")); f = out()[-1]
ok("OBJETIVO COMPLETADO" in (f["text"] or ""), "avisa el cierre")
ok(btns(f) == ["/vigia_registrar", "/vigia_cerrar", "panel:home"],
   f"REGISTRAR / CERRAR / PANEL ({btns(f)})")
ok(ses()["active"] == 1 and ses()["stage"] == "cerrando",
   "la sesion espera el registro opcional, sin plazo")

print("\n=== la foto final es registro: se guarda y cierra, sin modelo ===")
r.process(cb("/vigia_registrar")); f = out()[-1]
ok("resultado final" in (f["text"] or "").lower(), "pide la foto del resultado")
llamadas_reg = len(vis.prompts)
r.process(foto(8, "e")); f = out()[-1]
ok(len(vis.prompts) == llamadas_reg, "NO pasa por el modelo")
ok("Resultado registrado" in (f["text"] or ""), "avisa que quedo registrado")
ok(ses()["active"] == 0, "y cierra la sesion")
fin = db.one("SELECT * FROM vigia_evidence ORDER BY id DESC LIMIT 1")
ok(fin["stage"] == "final" and fin["decision"] == "REGISTRO",
   "la evidencia queda marcada como registro, no como observacion")

print("\n=== NINGÚN mensaje de Vigía queda sin botones ===")
r.process(cb("panel:vig:ctx")); f = out()[-1]
ok(messages.PANEL_VIG_SIN_TAREA in (f["text"] or ""), "sin tarea, el contexto lo dice")
ok(bool(btns(f)), "y trae botones")
r.process(cb("/vigia_bloque_ok")); f = out()[-1]
ok(btns(f) == ["panel:home"], "sin tarea, RECALIBRAR avisa con salida")
directos()
r.process(cb("/vigia_trabado")); f = out()[-1]
ok(btns(f) == ["panel:home"], "ME TRABÉ igual")
r.process(msg("/vigia", 8)); f = out()[-1]
ok(btns(f) == ["panel:home"], "el uso tambien")
r.process(msg("/vigia otra tarea", 9)); f = out()[-1]
ok(btns(f) == ["panel:vig:ctx", "panel:home"], f"al crear, ofrece contexto ({btns(f)})")
r.process(cb("panel:vigia")); out()
r.process(cb("panel:vig:cancelar")); out()
r.process(cb("panel:vig:cancelar:ok"))
fs = out()
ok(any(btns(x) == ["panel:home"] for x in fs if x["buttons"]), "cancelar tambien")
ok(ses()["active"] == 0, "y cierra")


print("\n=== el fallo de Gemini ofrece REINTENTAR con la misma foto ===")
r.process(msg("/vigia otra mas", 30)); out()
vis.r.append(PLAN); r.process(foto(31, "z")); out()
llamadas = len(vis.prompts)
bloque_previo = ses()["bloque"]
r.process(foto(32, "w"))          # sin respuestas -> TECHNICAL_ERROR
f = out()[-1]
ok("No pude analizar" in (f["text"] or ""), "avisa el fallo")
ok(btns(f) == ["/vigia_reintentar", "/vigia_siguiente", "/vigia_trabado", "panel:home"],
   f"REINTENTAR / ME TRABÉ / PANEL ({btns(f)})")
ok(ses()["ultima_foto"].endswith("w.jpg"), "guarda la foto fallida para reintentar")
ok(ses()["bloque"] == bloque_previo, "y no pierde el bloque")
vis.r.append(PLAN)
r.process(cb("/vigia_reintentar"))
ok(len(vis.prompts) == llamadas + 2, "reintenta sin pedir otra foto")
ok("Recoge la basura" in " ".join(x["text"] or "" for x in out()), "y ahora si responde")

print("\n=== trabado: SIGUIENTE no avanza hasta que llegue la foto ===")
r.process(msg("/vigia_cancelar", 39)); out()   # la seccion anterior dejo una abierta
r.process(msg("/vigia ordenar el escritorio", 40)); out()
vis.r.append(PLAN); r.process(foto(41, "t1")); out()
bloque_t = ses()["bloque"]
r.process(cb("/vigia_trabado")); out()
r.process(cb("/vigia_siguiente")); f = out()[-1]
ok(messages.VIGIA_TRABADO_EXIGE_FOTO in (f["text"] or ""), "pide la foto en vez de avanzar")
ok(ses()["bloque"] == bloque_t, "no declara hecho el bloque en el que te trabaste")
ok(json.loads(ses()["declarados"] or "[]") == [], "y no suma un declarado")

print("\n=== ME TRABÉ recalibra con la foto y conserva el objetivo ===")
vis.r.append({"estado": "EN_RUTA",
              "estrategia": ["Empieza por el cajon de arriba.", "ropa"],
              "bloque": "", "nota": "", "estimacion": ""})
r.process(foto(42, "t2")); t = " ".join(x["text"] or "" for x in out())
ok(ses()["trabado"] == 0, "la foto levanta el trabado")
ok("cajon de arriba" in t, "y entrega el bloque recalibrado")
ok(ses()["title"] == "ordenar el escritorio", "el objetivo no se toca")
ok("LA PERSONA DICE QUE SE TRABÓ: sí" in vis.prompts[-1],
   "el modelo se entera de que estaba trabado")

print("\n=== CERRAR sin foto final tambien termina la tarea ===")
r.process(cb("/vigia_cerrar")); f = out()[-1]
ok(ses()["active"] == 0, "cierra sin pedir nada")
ok(messages.VIGIA_CERRADO in (f["text"] or ""), "y lo dice")

print("\n=== la regla del plan ya no depende solo de la foto ===")
ok("el objetivo, el contexto, las restricciones" in messages.VIGIA_PROMPT_PLAN,
   "un contexto nuevo tambien puede cambiar el plan")

print("\n=== las pantallas del Panel no llevan HTML ===")
ok("<" not in messages.PANEL_VIG_FOTO, "la de la foto es texto plano")
ok("<" not in messages.panel_vigia_contexto("x", {}), "la de contexto tambien")

db.close()

TMP.unlink(missing_ok=True)
for x in F.glob("*"): x.unlink(missing_ok=True)
print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
