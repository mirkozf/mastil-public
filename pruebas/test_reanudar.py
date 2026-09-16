import os, sys, dataclasses, json
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")
import config as cm, messages
from database import Database
from core.router import Router
from modules.vigia import VigiaModule
from modules.panel import PanelModule

YO="999"
TMP=Path(os.environ["TEMP"])/"reanudar.db"; TMP.unlink(missing_ok=True)
F=Path(os.environ["TEMP"])/"rean_fotos"; F.mkdir(exist_ok=True)
cfg=dataclasses.replace(cm.load(),owner_chat_id=YO,db_path=TMP,evidence_dir=F)
db=Database(cfg.db_path,cfg.schema_path); db.migrate()
FALLAS=0
def ok(c,t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS+=1
class Vis:
    enabled=True
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
    def send_message(s,*a,**k): return {"ok":True}
    def answer_callback(s,*a,**k): pass
    def download_photo(s,fid,dest):
        p=Path(dest)/f"{fid}.jpg"; p.write_bytes(b"x"); return p
class Nada:
    enabled=False
    def __getattr__(s,n): return lambda *a,**k: False
vis=Vis(); tg=TG()
vigia=VigiaModule(cfg,db,tg,vis,Nada()); panel=PanelModule(cfg,db)
mods={"vigia":vigia,"panel":panel}
for k in ("timer","system","pomodoro","gmail","guardian","calendar","lite","intervalos"): mods[k]=Nada()
r=Router(cfg,db,tg,mods); panel.attach(r)
def out():
    f=db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL"); return f
def btns(f): return [b[1] for g in json.loads(f["buttons"]) for b in g] if f and f["buttons"] else []
def msg(t,m): return {"message":{"message_id":m,"chat":{"id":YO},"from":{"id":YO},"text":t}}
def cb(d,m=7): return {"callback_query":{"id":"c","data":d,"from":{"id":YO},"message":{"message_id":m,"chat":{"id":YO}}}}
def foto(m,f): return {"message":{"message_id":m,"chat":{"id":YO},"from":{"id":YO},"photo":[{"file_id":f}]}}

PLAN={"estado":"EN_RUTA","estrategia":["basura","ropa"],
      "bloque":"Recoge la basura visible. No toques todavia la ropa.","nota":"","estimacion":"1-2 h"}

print("=== sin tarea ===")
r.process(cb("/vigia_bloque")); f=out()[-1]
ok(messages.VIGIA_SIN_OBJETIVO in (f["text"] or ""), "avisa que no hay objetivo")
ok(btns(f)==["panel:home"], "con salida")

print("\n=== con tarea pero sin bloque todavia ===")
r.process(msg("/vigia ordenar la cocina",1)); out()
r.process(cb("/vigia_bloque")); f=out()[-1]
ok("ordenar la cocina" in (f["text"] or ""), "muestra el objetivo")
ok(messages.VIGIA_SIN_BLOQUE in (f["text"] or ""), "y dice que aun no hay bloque")
ok(btns(f)==["panel:vig:ctx","panel:vig:foto:2","panel:home"],
   f"salidas, con la opcion de dos fotos ({btns(f)})")

print("\n=== con bloque en curso ===")
vis.r.append(PLAN); r.process(foto(2,"a")); out()
llamadas=len(vis.prompts)
r.process(cb("/vigia_bloque")); f=out()[-1]
ok("ordenar la cocina" in (f["text"] or ""), "recuerda el objetivo")
ok("Recoge la basura visible" in (f["text"] or ""), "y devuelve el bloque exacto")
ok(btns(f)==["/vigia_siguiente","/vigia_bloque_ok","/vigia_trabado","panel:home"],
   f"con los mismos botones del bloque ({btns(f)})")
ok(len(vis.prompts)==llamadas, "sin llamar al modelo")
ok(f["kind"]=="text", "como mensaje nuevo, al final del chat")

print("\n=== se puede repetir sin efectos ===")
antes=dict(db.one("SELECT * FROM vigia_session WHERE id=1"))
for _ in range(3): r.process(cb("/vigia_bloque")); out()
ok(dict(db.one("SELECT * FROM vigia_session WHERE id=1"))==antes, "no cambia nada del estado")

print("\n=== sobrevive el reinicio del proceso ===")
v2=VigiaModule(cfg,db,tg,vis,Nada())
v2.handle_command("/vigia_bloque","/vigia_bloque"); f=out()[-1]
ok("Recoge la basura visible" in (f["text"] or ""), "tras reiniciar sigue devolviendo el bloque")

print("\n=== esta en el menu de Vigia ===")
r.process(cb("panel:vigia")); f=out()[-1]
ok("/vigia_bloque" in btns(f), f"el boton esta ({btns(f)})")

db.close(); TMP.unlink(missing_ok=True)
for x in F.glob("*"): x.unlink(missing_ok=True)
print("\nFALLAS:",FALLAS)
sys.exit(1 if FALLAS else 0)
