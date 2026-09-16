"""/cal: el evento se confirma viéndolo en el calendario, no por la respuesta.

Google entrega la respuesta de Apps Script en un segundo paso que a veces
contesta 404 aunque el script ya creó el evento. Mástil lo anunciaba como
"No se creó nada": 12 de 13 de esos "fallidos" estaban en el calendario.
"""

import os, sys, dataclasses
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics",
                  MASTIL_TIMEZONE="America/Santiago")

import config as cm
import messages
from database import Database
from integrations.calendar import CalendarBridge, REQUEST_MARKER
from modules.calendar_commands import CalendarCommandsModule

# Desfase fijo y no la zona por nombre: Windows no trae la base de zonas.
TZ = timezone(timedelta(hours=-3))
AHORA = datetime(2026, 9, 14, 10, 0, tzinfo=TZ)
TMP = Path(os.environ["TEMP"]) / "calendar_crear.db"
cfg = dataclasses.replace(cm.load(), owner_chat_id="999", db_path=TMP)
PEDIDO = "/cal comer 18:30"

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1


def e404():
    return urllib.error.HTTPError("https://x.invalid", 404, "Not Found", {}, None)


class Puente(CalendarBridge):
    """El puente real con la red cambiada por un guion, así `find_event` y su
    búsqueda por marca son el código de verdad.

    crear: "ok" | "404" | "sin_evento" (en los dos últimos el script SÍ corrió)
    lecturas, en orden: "404" | "con_evento" | "vacio" | lista de eventos
    """
    def __init__(self, crear="ok", lecturas=()):
        # Sin `super().__init__`: pide la zona por nombre. Lo que se prueba
        # del puente es `find_event`, y ése es el real.
        self.webapp_url, self.token, self.calendar_id = "https://x.invalid/exec", "t", "primary"
        self.tz = TZ
        self.crear = crear; self.lecturas = list(lecturas)
        self.creados = 0; self.leidos = 0; self.evento = None
    def now(self): return AHORA
    def create_event(self, *, title, start_at, end_at, request_id):
        self.creados += 1
        self.evento = {"id": "ev-1", "title": title,
                       "description": REQUEST_MARKER + request_id}
        if self.crear == "404": raise e404()
        if self.crear == "sin_evento":
            raise RuntimeError("El puente de Calendar no devolvio el evento creado.")
        return {"ok": True, "event": {"id": "ev-1", "title": title}}
    def snapshot_day(self, day):
        self.leidos += 1
        paso = self.lecturas.pop(0) if self.lecturas else "vacio"
        ajeno = {"id": "otro", "title": "otro", "description": ""}
        if paso == "404": raise e404()
        if paso == "con_evento": return [ajeno, self.evento]
        if paso == "vacio": return [ajeno]
        return paso


db = None
def montar(crear, *lecturas):
    global db
    if db: db.close()
    TMP.unlink(missing_ok=True)
    db = Database(cfg.db_path, cfg.schema_path); db.migrate()
    puente = Puente(crear, lecturas)
    return CalendarCommandsModule(cfg, db, puente), puente

def pedir(mod, mid=10):
    mod.handle_command("/cal", PEDIDO, mid)
    filas = db.query("SELECT text FROM outbox ORDER BY id")
    return filas[-1]["text"] if filas else ""

def fila(mid=10):
    return db.one("SELECT * FROM calendar_command_requests WHERE request_id = ?",
                  (f"calendar:999:{mid}",))


print("=== 0. el pedido de prueba se entiende ===")
mod, p = montar("ok", "con_evento")
t = pedir(mod)
ok(p.creados == 1, f"el parser acepta {PEDIDO!r} ({t[:60]!r})")

print("\n=== 1. creado y visto: se confirma ===")
ok("comer" in t and "No pude" not in t, "confirma con el titulo")
ok(fila()["status"] == "created" and fila()["last_error"] is None, "creado, sin error")
ok(p.leidos == 1, "una sola relectura")

print("\n=== 2. 404 de Google con el evento ya hecho: se encuentra por la marca ===")
mod, p = montar("404", "con_evento")
t = pedir(mod)
ok("No se creó nada" not in t and "No pude" not in t, "ya no dice que no se creo nada")
ok("comer" in t, "lo confirma porque lo vio en el calendario")
ok(fila()["status"] == "created" and fila()["calendar_event_id"] == "ev-1",
   "queda creado con su id real")
ok(p.creados == 1, "sin volver a crear: nada de duplicados")

print("\n=== 3. respuesta sin evento: lo mismo ===")
mod, p = montar("sin_evento", "con_evento")
t = pedir(mod)
ok("comer" in t and fila()["status"] == "created", "lo encuentra por la marca")

print("\n=== 4. releido y no esta: ahi si es un fallo ===")
mod, p = montar("404", "vacio")
t = pedir(mod)
ok(t == messages.CALENDAR_CREATE_FAILED and "lo busqué" in t,
   "avisa que lo busco y no esta")
ok(fila()["status"] == "failed", "queda fallido")

print("\n=== 5. la relectura tambien da 404: un reintento ===")
mod, p = montar("404", "404", "con_evento")
t = pedir(mod)
ok("comer" in t and fila()["status"] == "created", "al segundo intento lo encuentra")
ok(p.leidos == 2, "con exactamente dos lecturas")

print("\n=== 6. dos 404 al releer: no sabe, y lo dice ===")
mod, p = montar("404", "404", "404", "con_evento")
t = pedir(mod)
ok(t == messages.CALENDAR_UNVERIFIED, "avisa que no pudo confirmarlo")
ok(p.leidos == 2, "no insiste mas de dos veces")
ok(fila()["status"] == "failed" and fila()["last_error"].startswith("sin confirmar"),
   "sin id: queda fallido 'sin confirmar'")

print("\n=== 7. creado pero la verificacion da 404 ===")
mod, p = montar("ok", "404", "con_evento")
t = pedir(mod)
ok("comer" in t and fila()["last_error"] is None, "el segundo intento lo confirma")
mod, p = montar("ok", "404", "404")
t = pedir(mod)
ok(t == messages.CALENDAR_UNVERIFIED and fila()["status"] == "created"
   and fila()["last_error"].startswith("sin verificar"),
   "con id pero sin poder releer: creado sin verificar, como antes")

print("\n=== 8. creado, releido y no esta ===")
mod, p = montar("ok", "vacio")
t = pedir(mod)
ok(t == messages.CALENDAR_CREATE_FAILED and fila()["status"] == "failed", "no aparece: fallo")

print("\n=== 9. la marca calza exacta ===")
ajena = Puente("ok", [[{"id": "ajeno", "title": "x",
                         "description": REQUEST_MARKER + "calendar:999:1234"}]])
ok(ajena.find_event(None, "2026-09-14", request_id="calendar:999:123") is None,
   "la marca de …:1234 no es la de …:123")
propia = Puente("ok", [[{"id": "mio", "title": "x",
                          "description": REQUEST_MARKER + "calendar:999:123"}]])
ok((propia.find_event(None, "2026-09-14", request_id="calendar:999:123") or {}).get("id") == "mio",
   "la propia si")

print("\n=== 10. el mismo mensaje dos veces no duplica ===")
mod, p = montar("404", "con_evento")
pedir(mod); t = pedir(mod)
ok(t == messages.CALENDAR_ALREADY_CREATED and p.creados == 1, "reconoce que ya se creo")

db.close(); TMP.unlink(missing_ok=True)
print("\n" + "=" * 52)
print("FALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
