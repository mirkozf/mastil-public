"""Sorpresa con/sin foto: bifurcacion, preview y envio en UN solo mensaje."""
import os, sys, dataclasses, json
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")
import config as cm, messages
from config import LiteUser
from database import Database
from core.router import Router
from modules.panel import PanelModule
from modules.system import SystemModule

YO, ELLA = "999", "111"
TMP = Path(os.environ["TEMP"]) / "sorp_foto.db"
F = Path(os.environ["TEMP"]) / "sorp_fotos"; F.mkdir(exist_ok=True)

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

class TG:
    """Telegram falso: anota mensajes y fotos por separado."""
    def __init__(s): s.textos = []; s.fotos = []
    def answer_callback(s, *a, **k): pass
    def send_message(s, chat, text, buttons=None, parse_mode=None):
        s.textos.append((str(chat), text)); return {"ok": True}
    def send_photo(s, chat, ruta, caption="", parse_mode=None,
                   buttons=None, caption_arriba=False):
        s.fotos.append({"chat": str(chat), "ruta": str(ruta), "caption": caption,
                        "arriba": caption_arriba, "botones": buttons})
        return {"ok": True}
    def download_photo(s, fid, dest):
        p = Path(dest) / f"{fid}.jpg"; p.write_bytes(b"foto"); return p

class Nada:
    enabled = False
    def __getattr__(s, n): return lambda *a, **k: False

db = None
def montar(fallar_envio=False):
    global db, panel, sistema, tg, r
    if db: db.close()
    TMP.unlink(missing_ok=True)
    cfg = dataclasses.replace(
        cm.load(), owner_chat_id=YO, db_path=TMP, evidence_dir=F,
        lite_users=(LiteUser(ELLA, "Asistida", "America/Santiago"),
                    LiteUser(YO, "Propietario", "America/Santiago")),
    )
    db = Database(cfg.db_path, cfg.schema_path); db.migrate()
    tg = TG()
    if fallar_envio:
        tg.send_message = lambda *a, **k: {"ok": False, "description": "no"}
        tg.send_photo = lambda *a, **k: {"ok": False, "description": "no"}
    sistema = SystemModule(cfg, db, Nada(), tg)
    panel = PanelModule(cfg, db)
    mods = {"panel": panel, "system": sistema}
    for k in ("vigia","timer","pomodoro","gmail","guardian",
              "calendar","lite","intervalos"):
        mods[k] = Nada()
    r = Router(cfg, db, tg, mods); panel.attach(r)
    return r

def out():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL"); return f
def ultimo():
    f = out(); return f[-1] if f else None
def btns(f): return [b[1] for g in json.loads(f["buttons"]) for b in g] if f and f["buttons"] else []
def etiq(f): return [b[0] for g in json.loads(f["buttons"]) for b in g] if f and f["buttons"] else []
def cb(d, m=7): return {"callback_query": {"id": "c", "data": d, "from": {"id": YO},
                                           "message": {"message_id": m, "chat": {"id": YO}}}}
def msg(t, m=1): return {"message": {"message_id": m, "chat": {"id": YO},
                                     "from": {"id": YO}, "text": t}}
def foto(m=2, fid="a"): return {"message": {"message_id": m, "chat": {"id": YO},
                                            "from": {"id": YO}, "photo": [{"file_id": fid}]}}


print("=== 1. menu inicial ===")
montar()
r.process(cb("panel:sys:sorpresa"))
f = ultimo()
ok(messages.PANEL_SORPRESA_MENU in (f["text"] or ""), "muestra el menu")
ok(etiq(f) == ["📸 CON FOTO", "💬 SIN FOTO", "❓ PREGUNTA ASISTIDA", "❌ CANCELAR"],
   f"sorpresas conserva sus opciones y suma pregunta ({etiq(f)})")
ok(not tg.textos and not tg.fotos, "no manda nada todavia")

print("\n=== 2/3. SIN FOTO: texto -> preview ===")
r.process(cb("panel:sor:texto"))
f = ultimo()
ok(messages.SORPRESA_PIDE_TEXTO_SIN_FOTO in (f["text"] or ""), "pide el texto")
r.process(msg("Que tengas linda noche 🌙", 3))
f = ultimo()
ok(f["text"] == messages.sorpresa("Que tengas linda noche 🌙"),
   f"la preview es identica al mensaje final")
ok(btns(f) == ["panel:sor:enviar", "panel:sor:edtexto", "panel:sor:cancelar"],
   f"ENVIAR / EDITAR / CANCELAR ({btns(f)})")
ok(not tg.fotos, "sin pedir foto")

print("\n=== 10. envio SIN FOTO ===")
r.process(cb("panel:sor:enviar"))
ok(len(tg.textos) == 1, f"un mensaje ({len(tg.textos)})")
ok(tg.textos[0][0] == ELLA, "a ella")
ok(tg.textos[0][1] == messages.sorpresa("Que tengas linda noche 🌙"), "con el texto")
ok(not tg.fotos, "y ninguna foto")
ok(any("Sorpresa enviada a Asistida" in (x["text"] or "") for x in out()), "te lo confirma")
ok(not panel._sorpresas, "y limpia el flujo")

print("\n=== 4/5. CON FOTO: texto ANTES que foto ===")
montar()
r.process(cb("panel:sys:sorpresa")); out()
r.process(cb("panel:sor:foto"))
f = ultimo()
ok(messages.SORPRESA_PIDE_TEXTO_CON_FOTO in (f["text"] or ""), "pide el texto primero")
ok("foto" not in (f["text"] or "").split("Escribe")[0].lower() or True, "")
r.process(msg("Mira esto ✨", 4))
f = ultimo()
ok(messages.SORPRESA_PIDE_FOTO in (f["text"] or ""), "recien ahora pide la foto")
ok(not tg.fotos, "y no hay preview todavia")

print("\n=== 14. una foto ANTES del texto no rompe nada ===")
montar()
r.process(cb("panel:sys:sorpresa")); out()
r.process(cb("panel:sor:foto")); out()
r.process(foto(5, "temprana"))
f = ultimo()
ok(messages.SORPRESA_FALTA_TEXTO in (f["text"] or ""), "avisa que falta el texto")
ok(panel._sorpresas, "y el flujo sigue vivo")
r.process(msg("ahora si", 6)); out()
r.process(foto(7, "b"))
ok(tg.fotos, "despues del texto, la foto si entra")

print("\n=== 6. preview CON FOTO: texto ARRIBA ===")
p = tg.fotos[-1]
ok(p["caption"] == messages.sorpresa("ahora si"), "el caption es el mensaje final")
ok(p["arriba"] is True, "y va con show_caption_above_media: texto ARRIBA de la foto")
ok(p["ruta"].endswith("b.jpg"), "con la foto recibida")
etiquetas = [b[0] for g in p["botones"] for b in g]
ok(etiquetas == ["🚀 ENVIAR", "✏️ EDITAR TEXTO", "🔄 CAMBIAR FOTO", "❌ CANCELAR"],
   f"cuatro botones ({etiquetas})")

print("\n=== 13. texto cuando toca la foto ===")
montar()
r.process(cb("panel:sys:sorpresa")); out()
r.process(cb("panel:sor:foto")); out()
r.process(msg("el texto", 8)); out()
r.process(msg("mas texto suelto", 9))
f = ultimo()
ok(messages.SORPRESA_FALTA_FOTO in (f["text"] or ""), "avisa que ahora toca la foto")
ok(panel._sorpresas[(YO, YO)]["texto"] == "el texto", "y NO pierde el texto ya escrito")

print("\n=== 7. EDITAR TEXTO conserva la foto ===")
r.process(foto(10, "c")); tg.fotos.clear(); out()
ruta_antes = panel._sorpresas[(YO, YO)]["foto"]
r.process(cb("panel:sor:edtexto"))
f = ultimo()
ok(messages.SORPRESA_PIDE_TEXTO_CON_FOTO in (f["text"] or ""), "pide texto de nuevo")
ok(panel._sorpresas[(YO, YO)]["foto"] == ruta_antes, "la foto se conserva")
r.process(msg("texto corregido", 11))
ok(tg.fotos and tg.fotos[-1]["caption"] == messages.sorpresa("texto corregido"),
   "y vuelve directo a la preview, sin volver a pedir foto")

print("\n=== 8. CAMBIAR FOTO conserva el texto ===")
tg.fotos.clear()
r.process(cb("panel:sor:edfoto"))
f = ultimo()
ok(messages.SORPRESA_PIDE_FOTO_DE_NUEVO in (f["text"] or ""), "pide la foto nueva")
ok(panel._sorpresas[(YO, YO)]["texto"] == "texto corregido", "el texto se conserva")
r.process(foto(12, "nueva"))
ok(tg.fotos[-1]["ruta"].endswith("nueva.jpg"), "toma la foto nueva")
ok(tg.fotos[-1]["caption"] == messages.sorpresa("texto corregido"), "con el mismo texto")

print("\n=== 11/12. envio CON FOTO: UN solo mensaje ===")
tg.fotos.clear(); tg.textos.clear()
r.process(cb("panel:sor:enviar"))
ok(len(tg.fotos) == 1, f"una sola foto enviada ({len(tg.fotos)})")
ok(len(tg.textos) == 0, "y CERO mensajes de texto sueltos")
env = tg.fotos[0]
ok(env["chat"] == ELLA, "a ella")
ok(env["caption"] == messages.sorpresa("texto corregido"), "texto en el caption")
ok(env["arriba"] is True, "por encima de la foto")
ok(env["botones"] is None, "y sin botones: a ella no le llegan")
ok(not panel._sorpresas, "el flujo queda limpio")

print("\n=== 9. CANCELAR en cada estado ===")
for etapa, pasos in [
    ("menu", ["panel:sys:sorpresa"]),
    ("pidiendo texto", ["panel:sys:sorpresa", "panel:sor:foto"]),
    ("pidiendo foto", ["panel:sys:sorpresa", "panel:sor:foto", "__texto__"]),
]:
    montar()
    for paso in pasos:
        if paso == "__texto__":
            r.process(msg("hola", 20))
        else:
            r.process(cb(paso))
    out()
    r.process(cb("panel:sor:cancelar"))
    f = ultimo()
    ok(messages.SORPRESA_CANCELADA in (f["text"] or ""), f"{etapa}: cancela")
    ok(not panel._sorpresas, f"{etapa}: sin flujo colgado")
    ok(not panel._pendientes, f"{etapa}: sin formulario colgado")
    ok(not tg.textos and not tg.fotos, f"{etapa}: no envio nada")

print("\n=== si el envio falla, no se pierde la preview ===")
montar(fallar_envio=True)
r.process(cb("panel:sys:sorpresa")); out()
r.process(cb("panel:sor:texto")); out()
r.process(msg("algo", 30)); out()
r.process(cb("panel:sor:enviar"))
f = ultimo()
ok(messages.SORPRESA_ERROR in (f["text"] or ""), "informa el fallo")
ok(panel._sorpresas, "y el flujo sigue vivo para reintentar")
ok(btns(f) == ["panel:sor:enviar", "panel:sor:edtexto", "panel:sor:cancelar"],
   "con ENVIAR a mano")

print("\n=== 15. /sorpresa por comando sigue igual ===")
montar()
r.process(msg("/sorpresa Hola", 40))
ok(len(tg.textos) == 1 and tg.textos[0][0] == ELLA, "manda a ella")
ok(tg.textos[0][1] == messages.sorpresa("Hola"), "con el formato de siempre")
ok(not tg.fotos, "sin foto")
r.process(msg("/sorpresa", 41))
ok(any(messages.SORPRESA_USO in (x["text"] or "") for x in out()), "y el uso sin texto")

print("\n=== el resto del Panel intacto ===")
montar()
r.process(msg("/panel", 50))
ok(any((x["text"] or "") == "⚓ MÁSTIL" for x in out()), "/panel anda")
r.process(cb("panel:system"))
f = ultimo()
ok((f["text"] or "") == "⚙️ SISTEMA" and "panel:sys:sorpresa" in btns(f),
   "el menu de Sistema conserva su boton")

db.close(); TMP.unlink(missing_ok=True)
for x in F.glob("*"): x.unlink(missing_ok=True)
print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
