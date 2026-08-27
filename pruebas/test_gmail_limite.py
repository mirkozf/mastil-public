"""Dos revisiones por dia del buzon dedicado, con las dos fricciones."""

import os, sys, dataclasses, json
from pathlib import Path
from datetime import datetime, timedelta

RAIZ = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import messages
import core.scheduler as sched
import modules.gmail as G
from database import Database
from core.router import Router
from modules.gmail import GmailModule, CONTADOR_KEY
from modules.panel import PanelModule

# ---- reloj falso -------------------------------------------------------
BASE = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
RELOJ = {"t": BASE}
def ahora(): return RELOJ["t"]
def avanzar(**kw): RELOJ["t"] = RELOJ["t"] + timedelta(**kw)
sched.now_local = ahora
G.now_local = ahora

YO, AJENO = "999", "555"
TMP = Path(os.environ["TEMP"]) / "gmail_limite.db"
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP)

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1


class Puente:
    enabled = True
    def __init__(self): self.llamadas = []
    def count_unread(self): self.llamadas.append("count"); return 3
    def list_unread(self, limit=10):
        self.llamadas.append("list")
        return [{"id": "m1", "from": "ella@x.cl", "subject": "s", "date": "d"}]
    def get_content(self, mid, max_chars=60000):
        self.llamadas.append("content")
        return {"from": "ella@x.cl", "subject": "s", "date": "d", "body": "hola", "truncated": False}

class VisionFalsa:
    """Gemini falso: guarda el prompt recibido y responde lo que se le diga."""
    def __init__(self, ok_=True, texto="Yo lo dejaría para mañana."):
        self.prompts = []; self.ok_ = ok_; self.texto = texto
    def evaluar_texto(self, prompt):
        self.prompts.append(prompt)
        if not self.ok_:
            return {"ok": False, "texto": "", "error": "caido"}
        return {"ok": True, "texto": self.texto, "error": ""}

class TG:
    def __init__(self): self.enviados = []; self.answered = []
    def answer_callback(self, cid, text="", show_alert=False): self.answered.append(cid)
    def send_message(self, chat_id, text, buttons=None, parse_mode=None):
        self.enviados.append(text); return {"ok": True}

class Nada:
    def handle_command(self, *a, **k): return False
    def stop(self, *a, **k): pass
    def restore_calendar(self, *a, **k): pass
    def matches(self, *a, **k): return False
    def handle_message(self, *a, **k): return False
    def handle_text(self, *a, **k): return False
    def handle_photo(self, *a, **k): return False
    def handle(self, *a, **k): return True

db = None
def montar(vision=None):
    global db
    if db: db.close()
    TMP.unlink(missing_ok=True)
    RELOJ["t"] = BASE
    db = Database(cfg.db_path, cfg.schema_path); db.migrate()
    puente = Puente(); vis = vision or VisionFalsa(); tg = TG()
    gmail = GmailModule(cfg, db, puente, tg, vis)
    panel = PanelModule(cfg, db)
    mods = {"gmail": gmail, "panel": panel, "timer": Nada(),
            "system": Nada(), "pomodoro": Nada(), "guardian": Nada(),
            "calendar": Nada(), "lite": Nada(), "vigia": Nada(), "intervalos": Nada()}
    r = Router(cfg, db, tg, mods); panel.attach(r)
    return r, gmail, puente, vis, tg

def out():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL")
    return f

def textos(): return [x["text"] or "" for x in out()]

def msg(t, mid=1, chat=YO):
    return {"message": {"message_id": mid, "chat": {"id": chat}, "from": {"id": chat}, "text": t}}
def cbq(data, mid=7, chat=YO):
    return {"callback_query": {"id": "c", "data": data, "from": {"id": chat},
                               "message": {"message_id": mid, "chat": {"id": chat}}}}

def n_hoy(cmd="/gmail_hay"):
    """Igual que `_contador()`, pero por opcion: cada comando tiene su par."""
    estado = db.get_state(CONTADOR_KEY) or {}
    if estado.get("fecha") != ahora().strftime("%Y-%m-%d"):
        return 0
    return int((estado.get("usos", {}).get(cmd) or {}).get("n", 0))


print("=== 1/2. las dos revisiones del dia ===")
r, gmail, puente, vis, tg = montar()
r.process(msg("/gmail_hay"))
ok(any("hilos no leídos" in t for t in textos()), "primera revision responde")
ok(n_hoy() == 1, f"1/2 ({n_hoy()})")
r.process(msg("/gmail_hay"))
ok(any("hilos no leídos" in t for t in textos()), "segunda revision responde")
ok(n_hoy() == 2, f"2/2 ({n_hoy()})")
ok(n_hoy("/gmail_remitentes") == 0, "y remitentes sigue intacto: par propio")

print("\n=== 3. la tercera abre la friccion, no el buzon ===")
llamadas = len(puente.llamadas)
r.process(msg("/gmail_hay"))
filas = out()
ok(any("Ya usaste tus 2 revisiones" in (x["text"] or "") for x in filas), "avisa el limite")
botones = [b[1] for x in filas if x["buttons"] for g in json.loads(x["buttons"]) for b in g]
ok(botones == ["/gmail_igual", "/gmail_dejarlo"], f"REVISAR IGUAL / DEJARLO ({botones})")
ok(len(puente.llamadas) == llamadas, "NO consulto el puente")
ok(n_hoy() == 2, "y no conto nada")

print("\n=== 4. DEJARLO termina el flujo ===")
r.process(cbq("/gmail_dejarlo"))
ok(any(messages.GMAIL_DEJADO in t for t in textos()), "responde y cierra")
ok(gmail._friccion is None, "sin estado colgado")
ok(len(puente.llamadas) == llamadas and n_hoy() == 2, "sin consulta ni conteo")

print("\n=== 5/6. REVISAR IGUAL no abre: pide motivo ===")
r.process(msg("/gmail_hay")); out()
r.process(cbq("/gmail_igual"))
filas = out()
ok(any(messages.GMAIL_PIDE_MOTIVO in (x["text"] or "") for x in filas), "pide el motivo")
b = [x[1] for f in filas if f["buttons"] for g in json.loads(f["buttons"]) for x in g]
ok(b == ["panel:gm:motivo", "/gmail_dejarlo"], f"ESCRIBIR MOTIVO / DEJARLO ({b})")
ok(len(puente.llamadas) == llamadas, "sigue sin abrir el buzon")
ok(n_hoy() == 2, "y sin contar")

print("\n=== 7/8. el contexto que recibe Gemini ===")
db.execute(
    "INSERT INTO guardian_events(event_id,title,start_at,phase,is_active,created_at) "
    "VALUES ('e1','** almorzar','x','brake',1,'x')")
db.execute(
    "INSERT INTO guardian_events(event_id,title,start_at,phase,is_active,created_at) "
    "VALUES ('e2','** barrer','x','queued',0,'x')")
r.process(cbq("panel:gm:motivo")); out()
r.process(msg("solo quería ver si había algo nuevo", 2))
ok(len(vis.prompts) == 1, "Gemini recibio exactamente una consulta")
p = vis.prompts[0]
ok("dedicada exclusivamente a su ex pareja" in p, "declara el buzon")
ok(f"máximo {messages.GMAIL_LIMITE_DIARIO} revisiones" in p, "declara la regla")
ok("USO DE HOY: 2 de 2" in p, f"declara el uso del dia")
ok("Ya la agotó" in p, "y que esa consulta esta agotada")
ok("CONSULTA QUE QUIERE HACER" in p, "y cual es")
ok('"solo quería ver si había algo nuevo"' in p, "el motivo exacto, literal")
ok("Última revisión de este buzón" in p and "Tiempo transcurrido" in p, "el momento")
ok("** almorzar" in p, "el evento de Calendar en curso")
ok("cola: 1" in p, "los pendientes de la cola")
ok("No supongas que se relacionan" in p, "y le advierte que no infiera relacion")
ok("No diagnostiques" in p and "No moralices" in p, "las prohibiciones van explicitas")
ok("token" not in p.lower() and cfg.telegram_bot_token not in p, "sin credenciales")

print("\n=== 9/10. la segunda confirmacion ===")
filas = out()
texto = " ".join(x["text"] or "" for x in filas)
ok("ÚLTIMA CONFIRMACIÓN" in texto, "aparece la ultima confirmacion")
ok("Yo lo dejaría para mañana." in texto, "con la recomendacion de Gemini")
b = [x[1] for f in filas if f["buttons"] for g in json.loads(f["buttons"]) for x in g]
ok(b == ["/gmail_si", "/gmail_dejarlo"], f"SI REVISAR / DEJARLO ({b})")
ok(len(puente.llamadas) == llamadas, "todavia NO abrio el buzon")
ok(n_hoy() == 2, "y todavia no conto")

print("\n=== 11/12/13. solo SI REVISAR abre, y una sola vez ===")
r.process(cbq("/gmail_si"))
ok(len(puente.llamadas) == llamadas + 1, "ahora si consulto el puente")
ok(n_hoy() == 3, f"y conto la revision ({n_hoy()})")
ok(any("hilos no leídos" in t for t in textos()), "y devolvio el resultado real")
r.process(cbq("/gmail_si"))
r.process(cbq("/gmail_si"))
ok(n_hoy() == 3, "clics repetidos NO duplican el contador")
ok(len(puente.llamadas) == llamadas + 1, "ni vuelven a consultar")
ok(any(messages.GMAIL_SIN_FRICCION in t for t in textos()), "avisan que no hay nada que confirmar")

print("\n=== 14. dia nuevo, contador en 0 ===")
avanzar(days=1)
ok(n_hoy() == 0, f"el contador del dia nuevo arranca en 0 ({n_hoy()})")
r.process(msg("/gmail_hay"))
ok(any("hilos no leídos" in t for t in textos()), "revisa sin friccion")
ok(n_hoy() == 1, "1/2 del dia nuevo")

print("\n=== el corte es la fecha local, no 24h ===")
r, gmail, puente, vis, tg = montar()
RELOJ["t"] = BASE.replace(hour=23, minute=30)
r.process(msg("/gmail_hay")); r.process(msg("/gmail_hay")); out()
ok(n_hoy() == 2, "dos revisiones a las 23:30")
RELOJ["t"] = (BASE + timedelta(days=1)).replace(hour=1, minute=0)
ok(n_hoy() == 0, "a la 01:00 del dia siguiente ya hay cupo, sin esperar 24h")

print("\n=== 15/16. lo que NO se limita ===")
r, gmail, puente, vis, tg = montar()
r.process(msg("/gmail_hay")); r.process(msg("/gmail_hay")); out()
ok(n_hoy() == 2, "agotado")
r.process(msg("/gmail_remitentes")); out()   # para poblar los numeros
llamadas = len(puente.llamadas)
r.process(msg("/gmail_contenido 1 natural"))
ok(any("Correo 1" in t for t in textos()), "/gmail_contenido NO se bloquea")
ok(len(puente.llamadas) == llamadas + 1, "y si consulta")
ok(n_hoy() == 2 and n_hoy("/gmail_remitentes") == 1, "pero NO cuenta como revision")
r.process(msg("/gmail_ayuda"))
ok(any(messages.GMAIL_AYUDA in t for t in textos()), "/gmail_ayuda intacto")
ok(n_hoy() == 2, "y no cuenta")

print("\n=== 17. si Gemini falla, NO se abre ===")
r, gmail, puente, vis, tg = montar(vision=VisionFalsa(ok_=False))
r.process(msg("/gmail_hay")); r.process(msg("/gmail_hay")); out()
llamadas = len(puente.llamadas)
r.process(msg("/gmail_hay")); out()
r.process(cbq("/gmail_igual")); out()
r.process(cbq("panel:gm:motivo")); out()
r.process(msg("necesito saber si respondio", 3))
filas = out()
ok(any(messages.GMAIL_EVAL_FALLO in (x["text"] or "") for x in filas), "avisa el fallo")
b = [x[1] for f in filas if f["buttons"] for g in json.loads(f["buttons"]) for x in g]
ok(b == ["/gmail_reintentar", "/gmail_dejarlo"], f"REINTENTAR / DEJARLO ({b})")
ok(len(puente.llamadas) == llamadas, "NO abrio el buzon")
ok(n_hoy() == 2, "y no conto ninguna consulta")
r.process(cbq("/gmail_si"))
ok(len(puente.llamadas) == llamadas, "SI REVISAR no funciona sin haber confirmado")
ok(n_hoy() == 2, "sigue sin contar")
out()

print("\n=== reintentar reutiliza el motivo, sin volver a pedirlo ===")
gmail.vision = VisionFalsa(texto="Hay un motivo concreto, tiene sentido revisar.")
r.process(cbq("/gmail_reintentar"))
texto = " ".join(t for t in textos())
ok("ÚLTIMA CONFIRMACIÓN" in texto, "ahora si evalua")
ok("Hay un motivo concreto" in texto, "con la recomendacion nueva")
ok("necesito saber si respondio" in gmail.vision.prompts[0], "y reuso el motivo escrito")

print("\n=== 18/19. reinicio y comandos cancelan el formulario ===")
r, gmail, puente, vis, tg = montar()
r.process(msg("/gmail_hay")); r.process(msg("/gmail_hay")); out()
llamadas = len(puente.llamadas)
r.process(msg("/gmail_hay")); out()
r.process(cbq("/gmail_igual")); out()
r.process(cbq("panel:gm:motivo")); out()
r.process(msg("/gmail_ayuda", 4))
ok(any(messages.GMAIL_AYUDA in t for t in textos()), "el comando se ejecuta normal")
ok(not r.modules["panel"]._pendientes, "y cancela el formulario del Panel")
r.process(msg("texto suelto", 5)); out()
ok(len(puente.llamadas) == llamadas, "un texto posterior no abre nada")
ok(n_hoy() == 2, "ni cuenta")

gmail2 = GmailModule(cfg, db, puente, tg, vis)   # proceso nuevo
ok(gmail2._friccion is None, "reiniciar deja la friccion cancelada")
ok(n_hoy() == 2, "pero el contador del dia se conserva")
gmail2.handle_command("/gmail_si", "/gmail_si")
ok(len(puente.llamadas) == llamadas, "y un SI REVISAR huerfano no abre nada")
out()

print("\n=== un ajeno no toca nada ===")
r, gmail, puente, vis, tg = montar()
llamadas = len(puente.llamadas)
r.process(msg("/gmail_hay", 9, chat=AJENO))
ok(len(puente.llamadas) == llamadas and n_hoy() == 0, "ni consulta ni cuenta")
r.process(cbq("/gmail_si", chat=AJENO))
ok(len(puente.llamadas) == llamadas, "ni por callback")

print("\n=== 20. Panel intacto ===")
r, gmail, puente, vis, tg = montar()
r.process(msg("/panel", 10))
ok(any(t == "⚓ MÁSTIL" for t in textos()), "/panel sigue andando")
r.process(cbq("panel:gmail"))
ok(any(t == "📬 GMAIL" for t in textos()), "y su submenu")

db.close(); TMP.unlink(missing_ok=True)
print("\n" + "=" * 52)
print("FALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
