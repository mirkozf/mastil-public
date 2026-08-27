"""Cola de eventos que se pisan. Reloj falso: ningun sleep real."""

import os, sys, dataclasses
from pathlib import Path
from datetime import datetime, timedelta

RAIZ = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import messages
import core.scheduler as sched
import modules.guardian as G
from database import Database
from modules.guardian import GuardianModule

# ------------------------------------------------------------- reloj falso
BASE = datetime.now().astimezone().replace(microsecond=0)
RELOJ = {"t": BASE}
def ahora(): return RELOJ["t"]
def avanzar(minutos): RELOJ["t"] = RELOJ["t"] + timedelta(minutes=minutos)
sched.now_local = ahora
G.now_local = ahora

TMP = Path(os.environ["TEMP"]) / "cola_test.db"
cfg = dataclasses.replace(cm.load(), owner_chat_id="999", db_path=TMP)

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

db = None
def limpiar():
    global db, RELOJ
    if db: db.close()
    TMP.unlink(missing_ok=True)
    RELOJ["t"] = BASE
    db = Database(cfg.db_path, cfg.schema_path); db.migrate()
    return GuardianModule(cfg, db)

def out():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL")
    return [x["text"] or "" for x in f]

def ev(eid, titulo, minutos=0):
    return {"id": eid, "title": f"** {titulo}", "start": RELOJ["t"] + timedelta(minutes=minutos)}

def fase(g, eid):
    r = db.one("SELECT phase FROM guardian_events WHERE event_id = ?", (eid,))
    return r["phase"] if r else None

def cola(g):
    return [r["event_id"] for r in db.query(
        "SELECT event_id FROM guardian_events WHERE phase='queued' ORDER BY queue_seq")]

def rid(eid):
    return db.one("SELECT rowid AS r FROM guardian_events WHERE event_id=?", (eid,))["r"]

def cb(accion, eid):
    return {"id": "c", "data": f"cola:{accion}:{rid(eid)}",
            "message": {"message_id": 7, "chat": {"id": "999"}}}


print("=== 1. sin activo, un evento vence y se activa como antes ===")
g = limpiar()
g.tick([ev("A", "comer")])
ok(fase(g, "A") == "brake", "queda en brake (flujo de siempre)")
t = out()
ok(messages.GUARDIAN_ORIENTACION in t, "manda el nivel 1 de siempre")
ok(not any("pendiente" in x for x in t), "y ningun mensaje de cola")

print("\n=== 2/3. con activo, el segundo entra a cola y NO inicia Guardian ===")
g.tick([ev("A", "comer"), ev("B", "basura")])
ok(fase(g, "B") == "queued", "B queda encolado")
ok(fase(g, "A") == "brake", "A sigue siendo el activo")
ok(db.one("SELECT COUNT(*) c FROM guardian_events WHERE is_active=1")["c"] == 1,
   "un solo evento activo")
t = out()
ok(any("quedó pendiente" in x for x in t), "avisa que B quedo pendiente")
ok(not any(x == messages.GUARDIAN_ORIENTACION for x in t), "B NO disparo Guardian")

print("\n=== 4. tres eventos conservan FIFO ===")
g = limpiar()
g.tick([ev("A", "uno")]); out()
g.tick([ev("B", "dos")]); g.tick([ev("C", "tres")]); g.tick([ev("D", "cuatro")])
ok(cola(g) == ["B", "C", "D"], f"orden FIFO {cola(g)}")

print("\n=== 5. un solo aviso individual al entrar ===")
out()
for _ in range(5):
    g.tick([ev("A", "uno"), ev("B", "dos"), ev("C", "tres")])
t = out()
ok(sum("quedó pendiente" in x for x in t) == 0,
   "no repite el aviso individual en ticks siguientes")

print("\n=== 6. mientras hay activo, el recordatorio es agregado ===")
avanzar(16)
g.tick([])
t = out()
agregados = [x for x in t if "eventos pendientes" in x]
ok(len(agregados) == 1, f"un solo mensaje agregado ({len(agregados)})")
ok("3 eventos pendientes" in agregados[0], f"cuenta los 3: {agregados[0]}")
ok(not any("«" in x for x in t), "no nombra evento por evento")

print("\n=== 7. cerrar el activo presenta el primer pendiente ===")
# Escenario propio: sin avanzar el reloj, para que el activo siga en 'brake',
# que es la fase donde /listo cierra (en 'codigo' no cierra, y eso es de antes).
g = limpiar()
g.tick([ev("A", "uno")])
for e in ("B", "C", "D"): g.tick([ev(e, e)])
out()
g.handle_command("/listo", "/listo"); out()
g.tick([])
ok(fase(g, "B") == "decision", "B pasa a decision")
ok(cola(g) == ["C", "D"], "y sale de la cola")
t = out()
ok(any(messages.COLA_DECISION_TITULO in x for x in t), "presenta la decision")
ok(fase(g, "C") == "queued" and fase(g, "D") == "queued", "los otros siguen esperando")

print("\n=== 7b. la hora mostrada es la original, no la de ahora ===")
g = limpiar()
g.tick([ev("A", "uno")])
programado = RELOJ["t"]                    # la hora real de B
g.tick([ev("B", "dos")]); out()
avanzar(38)                                # se presenta bastante despues
g.cancel_active(); g.tick([])
fila = db.one("SELECT * FROM guardian_events WHERE event_id='B'")
ok(sched.from_iso(fila["start_at"]) == programado,
   f"start_at sigue siendo la hora original ({sched.clock(programado)})")
ok(sched.from_iso(fila["decision_at"]) == programado + timedelta(minutes=38),
   "decision_at guarda por separado cuando se presento")
ok(sched.clock(programado) in " ".join(out()),
   "y el mensaje muestra la hora original, no la de ahora")

print("\n=== 8. AHORA activa por el flujo existente ===")
g.handle_cola_callback(cb("ahora", "B")); out()
ok(fase(g, "B") == "brake", "B pasa a brake")
g.tick([])
t = out()
ok(messages.GUARDIAN_ORIENTACION in t, "y entra al Guardian de siempre")

print("\n=== 9. la decision ofrece EXACTAMENTE tres salidas ===")
g = limpiar()
g.tick([ev("A", "uno")]); g.tick([ev("B", "dos")]); out()
g.handle_command("/listo", "/listo"); g.tick([])
import json
fila = db.query("SELECT * FROM outbox WHERE buttons IS NOT NULL ORDER BY id")[-1]
teclado = json.loads(fila["buttons"])
datos = [b[1] for grupo in teclado for b in grupo]
etiquetas = [b[0] for grupo in teclado for b in grupo]
ok(datos == [f"cola:ahora:{rid('B')}", f"cola:despues:{rid('B')}",
             f"cola:descartar:{rid('B')}"], f"tres callbacks: {datos}")
ok(etiquetas == ["▶️ HACER AHORA", "⏳ DESPUÉS", "🗑️ DESCARTAR"], f"tres botones: {etiquetas}")
ok(not any("REAGEND" in e.upper() for e in etiquetas), "no aparece REAGENDAR")
ok(not any("cola:re" in d for d in datos), "ni ningun callback de reagendar")
ok(not hasattr(g, "reagendar_texto") and not hasattr(g, "_reagendar"),
   "y los handlers de reagendar ya no existen")
ok(not hasattr(messages, "cola_reagendar_botones"), "ni su teclado")
out()

print("\n=== 10. DESPUES rota [A,B,C] -> [B,C,A] ===")
g = limpiar()
g.tick([ev("X", "activo")]); out()
for e in ("A", "B", "C"): g.tick([ev(e, e)])
out()
g.handle_command("/listo", "/listo"); g.tick([]); out()
ok(fase(g, "A") == "decision" and cola(g) == ["B", "C"], "A esta en decision")
g.handle_cola_callback(cb("despues", "A")); out()
g.tick([])
ok(cola(g) == ["C", "A"], f"A al final: cola {cola(g)}")
ok(fase(g, "B") == "decision", "y B se presenta enseguida")
t = out()
ok(any(messages.COLA_DECISION_TITULO in x for x in t), "con su pantalla de decision")

print("\n=== 10b. DESPUES con uno solo: espera, no se repite ni se pierde ===")
g = limpiar()
g.tick([ev("X", "activo")]); g.tick([ev("A", "solo")]); out()
g.handle_command("/listo", "/listo"); g.tick([]); out()
g.handle_cola_callback(cb("despues", "A")); out()
g.tick([])
ok(fase(g, "A") == "queued", "sigue pendiente, no se activo ni se borro")
ok(not any(messages.COLA_DECISION_TITULO in x for x in out()), "no se repite enseguida")
avanzar(16); g.tick([])
ok(fase(g, "A") == "decision", "vuelve a ofrecerse a los ~15 min")
out()

print("\n=== 11. DESCARTAR cierra explicitamente, sin borrar historial ===")
g = limpiar()
g.tick([ev("X", "activo")]); g.tick([ev("A", "basura")]); out()
g.handle_command("/listo", "/listo"); g.tick([]); out()
g.handle_cola_callback(cb("descartar", "A"))
ok(fase(g, "A") == "discarded", "queda descartado")
ok(db.one("SELECT COUNT(*) c FROM guardian_events WHERE event_id='A'")["c"] == 1,
   "la fila NO se borro")
t = out()
ok(any("descartado" in x for x in t), "lo avisa")
g.tick([])
ok(any(messages.COLA_LIBRE in x for x in out()), "y sin cola dice sistema libre")

print("\n=== 12. recordatorios ~3, 8, 15, 30 min ===")
g = limpiar()
g.tick([ev("X", "activo")]); g.tick([ev("A", "pendiente")]); out()
g.handle_command("/listo", "/listo"); g.tick([]); out()
vistos = []
for minuto in range(1, 61):
    avanzar(1); g.tick([])
    if any(messages.COLA_DECISION_TITULO in x for x in out()): vistos.append(minuto)
ok(vistos == [3, 8, 15, 30, 45, 60], f"cadencia {vistos}")
for minuto in range(61, 91):
    avanzar(1); g.tick([])
    if any(messages.COLA_DECISION_TITULO in x for x in out()): vistos.append(minuto)
ok(vistos[-2:] == [75, 90], f"despues cada 15: {vistos[-2:]}")

print("\n=== 13/14. el tiempo NUNCA resuelve el evento ===")
avanzar(60 * 30)          # 30 horas: cruza la medianoche
for _ in range(40): g.tick([]); out()
ok(fase(g, "A") == "decision", "sigue esperando decision tras 30 h y cambio de dia")
ok(db.one("SELECT COUNT(*) c FROM guardian_events WHERE phase IN ('done','discarded')")["c"] == 1,
   "el unico cerrado sigue siendo el que cerro /listo")

print("\n=== 15/16. reinicio recupera cola y decision, sin duplicar ===")
g = limpiar()
g.tick([ev("X", "activo")]); out()
for e in ("A", "B"): g.tick([ev(e, e)])
g.handle_command("/listo", "/listo"); g.tick([]); out()
estado_antes = db.query("SELECT event_id, phase, queue_seq, decision_next_at, decision_step "
                        "FROM guardian_events ORDER BY event_id")
g2 = GuardianModule(cfg, db)          # proceso nuevo, misma base
g2.tick([])
ok(not out(), "al reanudar no reenvia nada (sin avisos duplicados)")
estado_despues = db.query("SELECT event_id, phase, queue_seq, decision_next_at, decision_step "
                          "FROM guardian_events ORDER BY event_id")
ok([dict(r) for r in estado_antes] == [dict(r) for r in estado_despues],
   "cola, orden y decision se reconstruyen identicos")
ok(fase(g2, "A") == "decision" and cola(g2) == ["B"], "A en decision, B en cola")
avanzar(4); g2.tick([])
ok(any(messages.COLA_DECISION_TITULO in x for x in out()),
   "y la cadencia continua desde donde iba")

print("\n=== 17. vence un evento durante una decision -> a la cola ===")
g = limpiar()
g.tick([ev("X", "activo")]); g.tick([ev("A", "uno")]); out()
g.handle_command("/listo", "/listo"); g.tick([]); out()
ok(fase(g, "A") == "decision" and g._active() is None, "hay decision y no hay activo")
g.tick([ev("N", "nuevo")])
ok(fase(g, "N") == "queued", "el nuevo entra a la cola")
ok(fase(g, "A") == "decision", "y no se salta al que ya esperaba")

print("\n=== 18/19. Guardian intacto para el unico evento ACTIVO ===")
g = limpiar()
g.tick([ev("A", "uno")]); out()
ok(g.handle_command("/ok", "/ok") is True, "/ok sigue dando tregua")
ok(fase(g, "A") == "truce", "  fase truce")
avanzar(cfg.duracion_tregua_minutes + 1); g.tick([])
ok(fase(g, "A") == "check", "  pasa a chequeo solo")
t = out()
ok(any("Pasaron los 5 minutos de tregua" in x for x in t), "  con su texto de siempre")
ok(g.handle_command("/reinicio", "/reinicio") is True, "/reinicio sigue andando")
ok(g.handle_command("/listo", "/listo") is True, "/listo cierra")
ok(fase(g, "A") == "done", "  fase done")
ok(G.RAFAGA_MENSAJES == 7 and G.MOMENTOS_RAFAGA if hasattr(G, "MOMENTOS_RAFAGA") else True,
   "constantes de rafaga sin tocar")
ok(G.ESPERA_NIVEL_1 == (3, 7) and G.SILENCIO_NIVEL_3 == 5, "esperas de Guardian intactas")

print("\n=== 19b. boton viejo no actua sobre otro evento ===")
g = limpiar()
g.tick([ev("X", "activo")]); g.tick([ev("A", "uno")]); g.tick([ev("B", "dos")]); out()
g.handle_command("/listo", "/listo"); g.tick([]); out()
viejo = cb("descartar", "A")
g.handle_cola_callback(cb("descartar", "A")); out()
g.tick([]); out()                       # ahora la decision es B
g.handle_cola_callback(viejo)
ok(fase(g, "B") == "decision", "B sigue en decision")
ok(any(messages.COLA_BOTON_EXPIRADO in x for x in out()), "avisa que el boton expiro")

print("\n=== 20. Intervalos sin cambios ===")
from modules.intervalos import MOMENTOS_AVISO, ESPERA_MINUTOS
ok(MOMENTOS_AVISO == (0, 150, 180, 420), f"MOMENTOS_AVISO {MOMENTOS_AVISO}")
ok(ESPERA_MINUTOS == 76, "ESPERA_MINUTOS 76")
ok(messages.INTERVALOS_AVISO == "⏱ Intervalo cumplido.", "su aviso intacto")

db.close(); TMP.unlink(missing_ok=True)
print("\n" + "=" * 52)
print("FALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
