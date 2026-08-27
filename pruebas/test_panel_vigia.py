"""Vigia accesible desde el Panel, iniciar incluido."""
import os, sys, dataclasses, json
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")
import config as cm, messages
from database import Database
from core.router import Router
from modules.vigia import VigiaModule
from modules.panel import PanelModule

YO = "999"
TMP = Path(os.environ["TEMP"])/"panel_vigia.db"; TMP.unlink(missing_ok=True)
F = Path(os.environ["TEMP"])/"pv_fotos"; F.mkdir(exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP, evidence_dir=F)
db = Database(cfg.db_path, cfg.schema_path); db.migrate()

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

class Vis:
    enabled = True
    def __init__(s): s.r=[]; s.prompts=[]
    def planificar(s,p,prompt,context=None):
        s.prompts.append(prompt)
        d = s.r.pop(0) if s.r else {"decision":"TECHNICAL_ERROR"}
        # Contrato nuevo: la estrategia ES la lista de bloques y el primero
        # es el de ahora. Los fixtures viejos traen "bloque" aparte.
        if isinstance(d, dict) and d.get("bloque"):
            d = dict(d)
            resto = [x for x in (d.get("estrategia") or []) if x != d["bloque"]]
            d["estrategia"] = [d["bloque"]] + resto
        return d
class TG:
    def __init__(s): s.a=[]
    def send_message(s,*a,**k): return {"ok":True}
    def answer_callback(s,cid,text="",show_alert=False): s.a.append(cid)
    def download_photo(s,fid,dest):
        p=Path(dest)/f"{fid}.jpg"; p.write_bytes(b"x"); return p
class Nada:
    enabled=False
    def __getattr__(s,n): return lambda *a,**k: False

vis=Vis(); tg=TG()
vigia=VigiaModule(cfg,db,tg,vis,Nada()); panel=PanelModule(cfg,db)
mods={"vigia":vigia,"panel":panel}
for k in ("timer","system","pomodoro","gmail","guardian","calendar","lite","intervalos"):
    mods[k]=Nada()
r=Router(cfg,db,tg,mods); panel.attach(r)

def out():
    f=db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL"); return f
def datos(f): return [b[1] for g in json.loads(f["buttons"]) for b in g] if f and f["buttons"] else []
def msg(t,m): return {"message":{"message_id":m,"chat":{"id":YO},"from":{"id":YO},"text":t}}
def cbq(d,m=7): return {"callback_query":{"id":"c","data":d,"from":{"id":YO},"message":{"message_id":m,"chat":{"id":YO}}}}
def foto(m,f): return {"message":{"message_id":m,"chat":{"id":YO},"from":{"id":YO},"photo":[{"file_id":f}]}}
def sesion(): return db.one("SELECT * FROM vigia_session WHERE id=1")

print("=== VIGÍA aparece en el panel principal ===")
r.process(msg("/panel",1))
f=out()[-1]
ok("panel:vigia" in datos(f), f"esta el boton ({datos(f)})")
ok(datos(f)[:6]==["panel:intervalos","panel:calendar","panel:timer","panel:pomodoro","panel:gmail","panel:system"],
   "y los seis de antes siguen en su orden")

print("\n=== el submenu ===")
r.process(cbq("panel:vigia"))
f=out()[-1]
ok(f["text"]=="👁️ VIGÍA" and f["kind"]=="edit", "abre editando el mismo mensaje")
ok(datos(f)==["panel:vig:objetivo","/vigia_bloque","panel:vig:ctx",
              "/vigia_trabado","panel:vig:cancelar","panel:home"],
   f"cinco accesos + PANEL ({datos(f)})")

print("\n=== iniciar Vigía desde el panel ===")
r.process(cbq("panel:vig:objetivo"))
f=out()[-1]
ok(messages.PANEL_VIGIA_OBJETIVO in (f["text"] or ""), "pide el objetivo")
r.process(msg("ordenar la cocina",2))
s=sesion()
ok(s["active"]==1 and s["title"]=="ordenar la cocina", "la sesion arranca con ese objetivo")
ok(s["stage"]=="esperando_foto", "y queda esperando la foto")
t=" ".join(x["text"] or "" for x in out())
ok("ordenar la cocina" in t and messages.VIGIA_PIDE_FOTO in t, "responde igual que por comando")

print("\n=== y el flujo sigue con la foto, como siempre ===")
vis.r.append({"estado":"EN_RUTA","estrategia":["basura","loza"],
              "bloque":"Recoge la basura visible. No toques todavía la loza.",
              "nota":"","estimacion":""})
r.process(foto(3,"a"))
ok("Recoge la basura" in " ".join(x["text"] or "" for x in out()), "entrega el bloque")
ok(sesion()["bloque"].startswith("Recoge"), "y lo guarda")

print("\n=== ME TRABÉ desde el submenu ===")
r.process(cbq("panel:vigia")); out()
r.process(cbq("/vigia_trabado"))
ok(sesion()["trabado"]==1, "marca trabado")
ok(any(messages.VIGIA_TRABADO_PIDE_FOTO in (x["text"] or "") for x in out()), "y pide foto")

print("\n=== cancelar pide confirmacion ===")
r.process(cbq("panel:vigia")); out()
r.process(cbq("panel:vig:cancelar"))
f=out()[-1]
ok(f["text"]==messages.PANEL_VIGIA_CANCELAR, "muestra la confirmacion")
ok(datos(f)==["panel:vig:cancelar:ok","panel:vigia"], f"CERRAR / VOLVER ({datos(f)})")
ok(sesion()["active"]==1, "todavia NO cerro")
r.process(cbq("panel:vigia")); out()
ok(sesion()["active"]==1, "VOLVER tampoco cierra")
r.process(cbq("panel:vig:cancelar")); out()
r.process(cbq("panel:vig:cancelar:ok"))
ok(sesion()["active"]==0, "solo CERRAR OBJETIVO cierra")
ok(any(messages.VIGIA_CANCELADO in (x["text"] or "") for x in out()), "y lo avisa")

print("\n=== un comando cancela el formulario del objetivo ===")
r.process(cbq("panel:vig:objetivo")); out()
r.process(msg("/panel",4))
ok(any((x["text"] or "")=="⚓ MÁSTIL" for x in out()), "/panel se ejecuta normal")
ok(not panel._pendientes, "y descarta el formulario")
ok(sesion()["active"]==0, "sin crear ninguna sesion")

print("\n=== el comando /vigia sigue funcionando igual ===")
r.process(msg("/vigia ordenar pieza",5))
ok(sesion()["active"]==1 and sesion()["title"]=="ordenar pieza", "por comando tambien")
out()

db.close(); TMP.unlink(missing_ok=True)
for x in F.glob("*"): x.unlink(missing_ok=True)
print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
