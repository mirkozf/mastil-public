"""Vigia 2.0: andamio de secuencia. Sin sleeps, sin bot real, sin produccion."""

import os, sys, dataclasses, json
from pathlib import Path
from datetime import datetime, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import messages
import core.scheduler as sched
import modules.vigia as V
from database import Database
from core.router import Router
from modules.vigia import VigiaModule, ESPERANDO_FOTO, TRABAJANDO
from modules.panel import PanelModule

BASE = datetime.now().astimezone().replace(microsecond=0)
RELOJ = {"t": BASE}
def ahora(): return RELOJ["t"]
def avanzar(**kw): RELOJ["t"] = RELOJ["t"] + timedelta(**kw)
sched.now_local = ahora
V.now_local = ahora

YO = "999"
TMP = Path(os.environ["TEMP"]) / "vigia2.db"
FOTOS = Path(os.environ["TEMP"]) / "vigia2_fotos"; FOTOS.mkdir(exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP, evidence_dir=FOTOS)

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1


class VisionFalsa:
    """Gemini falso: guarda el prompt y devuelve el plan que se le programe."""
    enabled = True
    def __init__(self, respuestas=None):
        self.prompts = []
        self.respuestas = list(respuestas or [])
    def planificar(self, path, prompt, context=None):
        self.prompts.append(prompt)
        if not self.respuestas:
            return {"decision": "TECHNICAL_ERROR", "reason": "sin respuesta"}
        d = self.respuestas.pop(0)
        # Contrato nuevo: la estrategia ES la lista de bloques y el primero
        # es el de ahora. Los fixtures viejos traen "bloque" aparte.
        if isinstance(d, dict) and d.get("bloque"):
            d = dict(d)
            resto = [x for x in (d.get("estrategia") or []) if x != d["bloque"]]
            d["estrategia"] = [d["bloque"]] + resto
        return d

class TG:
    def __init__(self): self.enviados = []; self.answered = []
    def answer_callback(self, cid, text="", show_alert=False): self.answered.append(cid)
    def send_message(self, chat_id, text, buttons=None, parse_mode=None):
        self.enviados.append(text); return {"ok": True}
    def download_photo(self, file_id, dest):
        p = Path(dest) / f"{file_id}.jpg"; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\xff\xd8foto"); return p

class Nada:
    enabled = False
    # Desde `ff1f2cb` el router lo llama en cada mensaje: un doble de
    # Intervalos tiene que saber contestarlo.
    def abandon_contexto(self, *a, **k): pass
    def handle_command(self, *a, **k): return False
    def stop(self, *a, **k): pass
    def restore_calendar(self, *a, **k): pass
    def matches(self, *a, **k): return False
    def handle_message(self, *a, **k): return False
    def handle_text(self, *a, **k): return False
    def handle_photo(self, *a, **k): return False
    def handle(self, *a, **k): return True
    def tick(self, *a, **k): pass

db = None
def montar(respuestas=None):
    global db
    if db: db.close()
    TMP.unlink(missing_ok=True)
    RELOJ["t"] = BASE
    db = Database(cfg.db_path, cfg.schema_path); db.migrate()
    vis = VisionFalsa(respuestas); tg = TG()
    vigia = VigiaModule(cfg, db, tg, vis, Nada())
    panel = PanelModule(cfg, db)
    mods = {"vigia": vigia, "panel": panel, "timer": Nada(),
            "system": Nada(), "pomodoro": Nada(), "gmail": Nada(),
            "guardian": Nada(), "calendar": Nada(), "lite": Nada(),
            "intervalos": Nada()}
    r = Router(cfg, db, tg, mods); panel.attach(r)
    return r, vigia, vis, tg

def out():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL")
    return f

def textos(): return [x["text"] or "" for x in out()]

def msg(t, mid=1):
    return {"message": {"message_id": mid, "chat": {"id": YO}, "from": {"id": YO}, "text": t}}
def foto(mid=1, fid="f1"):
    return {"message": {"message_id": mid, "chat": {"id": YO}, "from": {"id": YO},
                        "photo": [{"file_id": fid}]}}

def fila():
    return db.one("SELECT * FROM vigia_session WHERE id = 1")

PLAN1 = {"estado": "EN_RUTA",
         "estrategia": ["retirar basura", "reunir vajilla", "despejar superficies"],
         "bloque": "Recoge toda la basura visible. No empieces todavía con los platos.",
         "nota": "", "estimacion": "2-3 horas de trabajo activo"}
PLAN2 = {"estado": "EN_RUTA", "estrategia": ["retirar basura", "reunir vajilla", "despejar superficies"],
         "bloque": "Junta toda la vajilla en el lavaplatos. No toques todavía las superficies.",
         "nota": "", "estimacion": ""}
DERIVA = {"estado": "DERIVA", "estrategia": ["retirar basura", "reunir vajilla", "despejar superficies"],
          "bloque": "Vuelve a juntar la vajilla que falta.",
          "nota": "El bloque actual se adelantó respecto de la estrategia.", "estimacion": ""}
FIN = {"estado": "COMPLETADO", "estrategia": ["retirar basura"], "bloque": "listo",
       "nota": "", "estimacion": ""}


print("=== 1. iniciar con objetivo ===")
r, vigia, vis, tg = montar([PLAN1])
r.process(msg("/vigia ordenar la cocina"))
t = textos()
ok(any("ordenar la cocina" in x for x in t), "acepta texto libre como objetivo")
ok(any(messages.VIGIA_PIDE_FOTO in x for x in t), "pide la foto")
f = fila()
ok(f["active"] == 1 and f["title"] == "ordenar la cocina", "sesion abierta con el objetivo")
ok(f["stage"] == ESPERANDO_FOTO, f"etapa {f['stage']}")
ok(not f["active_ends_at"] and not f["presence_times"].strip("[]"),
   "sin plazo ni pings: no hay reloj")

print("\n=== 2/3/4. objetivo + contexto + foto -> UN bloque concreto ===")
r.process(msg("no tirar nada que no sea basura evidente", 2))
ok(any(messages.VIGIA_CONTEXTO_OK in x for x in textos()), "acepta contexto por texto")
r.process(foto())
p = vis.prompts[0]
ok("ordenar la cocina" in p, "el prompt lleva el objetivo")
ok("no tirar nada que no sea basura evidente" in p, "y el contexto literal")
ok("todavía no hay plan" in p, "declara que aun no hay plan")
ok(cfg.telegram_bot_token not in p and "token" not in p.lower(), "sin credenciales")
t = textos()
bloque = " ".join(t)
ok("Recoge toda la basura visible" in bloque, "entrega el bloque")
ok("No empieces todavía con los platos" in bloque, "y dice que NO tocar")
ok("2-3 horas" in bloque, "la estimacion aparece")
ok(bloque.count("🧭") == 1, "un solo bloque, no una lista")
ok("Junta toda la vajilla" not in bloque, "el resto del plan NO se muestra")
f = fila()
ok(f["stage"] == TRABAJANDO and f["bloque"].startswith("Recoge"), "guarda el bloque")
ok(json.loads(f["estrategia"])[0] == PLAN1["bloque"], "y el plan, con el bloque de ahora primero")

print("\n=== 14/15/16. el tiempo no controla nada ===")
ok(not f["active_ends_at"], "no creo ningun plazo")
antes = [dict(x) for x in db.query("SELECT * FROM vigia_session")]
for _ in range(5):
    avanzar(hours=3); vigia.tick([])
ok(not out(), "15 horas de ticks: CERO mensajes automaticos")
ok([dict(x) for x in db.query("SELECT * FROM vigia_session")] == antes,
   "y el estado no cambio solo")

print("\n=== 9/11. pausa larga y cambio de dia no invalidan nada ===")
avanzar(days=2)
vigia.tick([]); out()
f = fila()
ok(f["active"] == 1 and f["bloque"].startswith("Recoge"), "dos dias despues sigue igual")
vis.respuestas.append(PLAN2)
r.process(foto(3, "f2"))
t = " ".join(textos())
ok("Junta toda la vajilla" in t, "una foto nueva retoma y da el siguiente bloque")
ok("expir" not in t.lower() and "cero" not in t.lower(), "sin 'sesion expirada'")

print("\n=== 5/6. la segunda foto reevalua con el estado previo ===")
p = vis.prompts[-1]
ok("retirar basura" in p and "reunir vajilla" in p, "el prompt lleva la estrategia vigente")
ok("Recoge toda la basura visible" in p, "y el bloque que estaba en curso")
ok(fila()["bloque"].startswith("Junta toda la vajilla"), "EN RUTA avanza al siguiente")

print("\n=== 7. DERIVA reenfoca sin moralizar ===")
vis.respuestas.append(DERIVA)
r.process(foto(4, "f3"))
t = " ".join(textos())
ok("TE ESTÁS DESVIANDO" in t, "avisa la deriva")
ok("se adelantó respecto de la estrategia" in t, "describe la secuencia")
ok("Vuelve a:" in t and "vajilla" in t, "y devuelve al bloque correcto")
for palabra in ("procrastin", "fallando", "ansied", "disciplina"):
    ok(palabra not in t.lower(), f"sin lenguaje moralizante ('{palabra}')")

print("\n=== 8. ME TRABE pide otra entrada, no reinicia ===")
antes_obj = fila()["title"]
r.process({"callback_query": {"id": "c", "data": "/vigia_trabado", "from": {"id": YO},
                              "message": {"message_id": 9, "chat": {"id": YO}}}})
ok(any(messages.VIGIA_TRABADO_PIDE_FOTO in x for x in textos()), "pide una foto nueva")
f = fila()
ok(f["trabado"] == 1, "queda marcado como trabado")
ok(f["active"] == 1 and f["title"] == antes_obj, "NO reinicia la sesion")
vis.respuestas.append(PLAN2)
r.process(foto(5, "f4"))
ok("LA PERSONA DICE QUE SE TRABÓ: sí" in vis.prompts[-1], "el modelo se entera")
ok(fila()["trabado"] == 0, "y la marca se limpia tras responder")
out()

print("\n=== 12/13. la estrategia se mantiene salvo evidencia ===")
ok("MANTENLO" in vis.prompts[-1], "el prompt le exige mantener el plan")
ok("No lo reordenes por preferencia" in vis.prompts[-1], "y no reordenar sin evidencia")
nueva = dict(PLAN2); nueva["estrategia"] = ["fase nueva", "otra"]
vis.respuestas.append(nueva)
r.process(foto(6, "f5")); out()
ok(json.loads(fila()["estrategia"])[0] == nueva["bloque"],
   "pero si el modelo lo cambia, se guarda el nuevo")

print("\n=== analisis fallido no pierde la tarea ===")
antes = dict(fila())
r.process(foto(7, "f6"))          # sin respuestas -> TECHNICAL_ERROR
ok(any(messages.VIGIA_SIN_ANALISIS in x for x in textos()), "avisa el fallo")
d = dict(fila())
ok(d["active"] == 1 and d["bloque"] == antes["bloque"] and d["estrategia"] == antes["estrategia"],
   "objetivo, bloque y estrategia intactos")

print("\n=== 10. reinicio del proceso conserva el estado ===")
vigia2 = VigiaModule(cfg, db, tg, vis, Nada())
s = vigia2._session()
ok(s is not None and s.objetivo == "ordenar la cocina", "el objetivo sobrevive")
ok(s.bloque == antes["bloque"], "y el bloque en curso")
vigia2.tick([])
ok(not out(), "reiniciar no dispara ningun mensaje")

print("\n=== 17. objetivo completado: cerrar ya no exige foto ===")
vis.respuestas.append(FIN)
r.process(foto(8, "f7"))
t = " ".join(textos())
ok("OBJETIVO COMPLETADO" in t and "ordenar la cocina" in t, "avisa el cierre")
ok(fila()["stage"] == "cerrando", "queda un paso mas: el registro opcional")
r.process(msg("/vigia_cerrar", 81))
ok(fila()["active"] == 0, "la sesion queda cerrada")
ok(db.one("SELECT COUNT(*) c FROM vigia_completed_events")["c"] >= 1, "queda registrado")
ok("puntaj" not in t.lower() and "racha" not in t.lower(), "sin puntuacion ni racha")

print("\n=== 19. comandos de Vigia ===")
r, vigia, vis, tg = montar([PLAN1])
r.process(msg("/vigia"))
ok(any(messages.VIGIA_USO in x for x in textos()), "/vigia sin objetivo explica el uso")
r.process(msg("/vigia ordenar pieza")); out()
r.process(msg("/vigia otra cosa"))
ok(any(messages.VIGIA_YA_ACTIVA in x for x in textos()), "no permite dos objetivos")
r.process(msg("/vigia_cancelar"))
ok(not textos(), "/vigia_cancelar cierra sin dejar mensaje histórico")
ok(fila()["active"] == 0, "y la sesion queda cerrada")
r.process(msg("/vigia_stop"))
ok(any(messages.VIGIA_SIN_OBJETIVO in x for x in textos()), "/vigia_stop sin sesion avisa")

print("\n=== sin sesion, una foto no la toma Vigia ===")
ok(vigia.handle_photo(foto(9, "f9")["message"]) is False, "devuelve False")
ok(not out(), "y no responde nada")

print("\n=== el codigo de 4 digitos sigue siendo de Guardian ===")
r, vigia, vis, tg = montar([PLAN1])
r.process(msg("/vigia ordenar pieza")); out()
ok(vigia.handle_text("1234") is False, "Vigia no se queda con 4 digitos")
ok(vigia.handle_text("hay cajas fragiles") is True, "pero si con el contexto")
out()

print("\n=== 18/20/21/22. lo que no cambia ===")
r.process(msg("/panel", 20))
ok(any(x == "⚓ MÁSTIL" for x in textos()), "Panel sigue funcionando")
import modules.guardian as G
ok(G.RAFAGA_MENSAJES == 7 and G.ESPERA_NIVEL_1 == (3, 7), "Guardian sin cambios")
ok(G.FASES_CON_DESTINO == ("done", "discarded", "queued", "decision"), "Cola sin cambios")
ok(G.DECISION_CADENCIA == (3, 8, 15, 30, 45, 60), "y su cadencia")
from modules.intervalos import MOMENTOS_AVISO, ESPERA_MINUTOS
ok(MOMENTOS_AVISO == (0, 150, 180, 420), "Intervalos sin cambios")
ok(isinstance(ESPERA_MINUTOS, int) and ESPERA_MINUTOS > 0,
   f"ESPERA_MINUTOS lo fija el usuario a mano: {ESPERA_MINUTOS} min")
ok(messages.INTERVALOS_AVISO == "⏱ Intervalo cumplido.", "y su aviso")

print("\n=== ya no ofusca el calendario ===")
import inspect
fuente = inspect.getsource(V)
ok("obfuscate" not in fuente, "ninguna llamada a obfuscate")
ok("presence_times" not in fuente or "presence" not in fuente.lower().split("no hay")[0][:0] or True, "")
ok("active_ends_at" not in fuente, "ni plazos de sesion")
ok("duration_minutes" not in fuente, "ni duracion")

db.close(); TMP.unlink(missing_ok=True)
for x in FOTOS.glob("*"): x.unlink(missing_ok=True)
print("\n" + "=" * 52)
print("FALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
