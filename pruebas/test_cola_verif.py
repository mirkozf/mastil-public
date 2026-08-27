"""Pasada de verificacion de la cola: reagendado vs ICS, reinicios, duplicados."""

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

# ---- reloj falso: ningun sleep real -------------------------------------
HOY = datetime.now().astimezone().replace(microsecond=0)
def a_las(h, m, dia=0):
    return HOY.replace(hour=h, minute=m, second=0) + timedelta(days=dia)

RELOJ = {"t": a_las(18, 0)}
def ahora(): return RELOJ["t"]
def poner(t): RELOJ["t"] = t
def avanzar(minutos): RELOJ["t"] = RELOJ["t"] + timedelta(minutes=minutos)
sched.now_local = ahora
G.now_local = ahora

# Guardian escala a un momento AL AZAR entre 3 y 7 minutos. Eso es suyo y ya
# está probado aparte; acá sólo lo vuelve no determinista: según el sorteo, el
# activo llega a 'codigo', donde /listo no cierra (y hace bien). Se corre esa
# escalada fuera del alcance de estas pruebas para medir la cola, no el azar.
G.proximo = lambda minimo, maximo: ahora() + timedelta(hours=6)

TMP = Path(os.environ["TEMP"]) / "cola_verif.db"
cfg = dataclasses.replace(cm.load(), owner_chat_id="999", db_path=TMP)

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

db = None
def limpiar(desde=None):
    global db
    if db: db.close()
    TMP.unlink(missing_ok=True)
    poner(desde or a_las(18, 0))
    db = Database(cfg.db_path, cfg.schema_path); db.migrate()
    return GuardianModule(cfg, db)

def out():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL")
    return [x["text"] or "" for x in f]

def ics(eid, titulo, cuando):
    """Un evento tal como lo entrega el ICS: identidad estable, hora original."""
    return {"id": eid, "title": f"** {titulo}", "start": cuando}

def fase(eid):
    r = db.one("SELECT phase FROM guardian_events WHERE event_id=?", (eid,))
    return r["phase"] if r else None

def filas(eid):
    return db.one("SELECT COUNT(*) c FROM guardian_events WHERE event_id=?", (eid,))["c"]

def cola():
    return [r["event_id"] for r in db.query(
        "SELECT event_id FROM guardian_events WHERE phase='queued' ORDER BY queue_seq")]

def cuenta(fase_):
    return db.one("SELECT COUNT(*) c FROM guardian_events WHERE phase=?", (fase_,))["c"]

def rid(eid):
    return db.one("SELECT rowid r FROM guardian_events WHERE event_id=?", (eid,))["r"]

def cb(accion, eid):
    return {"id": "c", "data": f"cola:{accion}:{rid(eid)}",
            "message": {"message_id": 7, "chat": {"id": "999"}}}

def reiniciar():
    """Otro proceso sobre la MISMA base."""
    return GuardianModule(cfg, db)


# =========================================================================
print("=== 0. la decision tiene TRES salidas y ninguna de reagendar ===")
import json
g = limpiar(a_las(18, 0))
g.tick([ics("A", "activo", a_las(18, 0))])
poner(a_las(18, 5)); g.tick([ics("B", "basura", a_las(18, 5))])
g.cancel_active(); g.tick([])
teclado = json.loads(db.query(
    "SELECT * FROM outbox WHERE buttons IS NOT NULL ORDER BY id")[-1]["buttons"])
etiquetas = [b[0] for grupo in teclado for b in grupo]
datos = [b[1] for grupo in teclado for b in grupo]
ok(etiquetas == ["▶️ HACER AHORA", "⏳ DESPUÉS", "🗑️ DESCARTAR"], f"botones: {etiquetas}")
ok(not any("cola:re" in d or "panel:cola" in d for d in datos), "sin callbacks de reagendar")
ok(not hasattr(G.GuardianModule, "_reagendar"), "sin _reagendar")
ok(not hasattr(G.GuardianModule, "reagendar_texto"), "sin reagendar_texto")
ok(not hasattr(G.GuardianModule, "_vencidos"), "sin _vencidos")
ok("scheduled" not in G.FASES_CON_DESTINO, f"sin fase scheduled: {G.FASES_CON_DESTINO}")
out()

print("\n=== 1. un pendiente NO se re-selecciona desde el ICS ===")
g = limpiar(a_las(18, 0))
EV_A = ics("A", "activo", a_las(18, 0))
EV_B = ics("B", "sacar basura", a_las(18, 5))

g.tick([EV_A])
ok(fase("A") == "brake", "18:00 A activo")

poner(a_las(18, 5))
g.tick([EV_A, EV_B])
ok(fase("B") == "queued", "18:05 B entra a cola")
out()

print("  -- el ICS insiste con B mientras su ventana sigue abierta --")
for h, m in [(18, 5), (18, 6)]:
    poner(a_las(h, m))
    g.tick([EV_A, EV_B])
    t = out()
    ok(fase("B") == "queued", f"{h:02d}:{m:02d} B sigue en cola, no se re-encola")
    ok(not any("quedó pendiente" in x for x in t), f"{h:02d}:{m:02d} sin aviso repetido")
    ok(filas("B") == 1, f"{h:02d}:{m:02d} una sola fila para B")

g.cancel_active(); g.tick([EV_A, EV_B])
ok(fase("B") == "decision", "A termina, B pasa a decision")
out()

print("  -- y tampoco durante la decision --")
for h, m in [(18, 6), (18, 20), (19, 0)]:
    poner(a_las(h, m))
    g.tick([EV_A, EV_B])
    t = out()
    ok(fase("B") == "decision", f"{h:02d}:{m:02d} B sigue en decision")
    ok(filas("B") == 1, f"{h:02d}:{m:02d} sin copia")
ok(cuenta("queued") == 0, "y nada volvio a la cola")

print("  -- la hora original nunca se falsifica --")
fila = db.one("SELECT * FROM guardian_events WHERE event_id='B'")
ok(sched.from_iso(fila["start_at"]) == a_las(18, 5), "start_at = 18:05, la original")
ok(sched.from_iso(fila["decision_at"]) > sched.from_iso(fila["start_at"]),
   "decision_at es posterior y va aparte")
ok(fila["event_id"] == "B", "identidad del evento intacta")


# =========================================================================
print("\n=== 3. autoencolado del activo (regresion permanente) ===")
g = limpiar()
EV_A = ics("A", "activo", a_las(18, 0))
g.tick([EV_A]); out()
for i in range(8):
    avanzar(0)
    g.tick([EV_A])          # el ICS devuelve A una y otra vez
ok(fase("A") == "brake", "A sigue siendo el mismo activo")
ok(cuenta("queued") == 0, f"queue count = 0 (dio {cuenta('queued')})")
ok(cuenta("decision") == 0, f"decision count = 0 (dio {cuenta('decision')})")
ok(filas("A") == 1, "A nunca aparece dos veces")
ok(db.one("SELECT COUNT(*) c FROM guardian_events WHERE is_active=1")["c"] == 1,
   "un solo activo")
ok(not any("pendiente" in x for x in out()), "y ningun aviso de cola")


# =========================================================================
print("\n=== 4. reinicio con cola completa ===")
g = limpiar()
EVS = [ics("A", "activo", a_las(18, 0)), ics("B", "beta", a_las(18, 1)),
       ics("C", "charlie", a_las(18, 2))]
g.tick([EVS[0]])
poner(a_las(18, 1)); g.tick(EVS[:2])
poner(a_las(18, 2)); g.tick(EVS)
ok(fase("A") == "brake" and cola() == ["B", "C"], f"A activo, cola {cola()}")
out()

g2 = reiniciar()
g2.tick(EVS)                      # el ICS sigue entregando los tres
t = out()
ok(fase("A") == "brake", "A sigue activo tras reiniciar")
ok(cola() == ["B", "C"], f"orden conservado {cola()}")
ok(not any("quedó pendiente" in x for x in t), "no reenvia el aviso individual de B ni de C")

g2.handle_command("/listo", "/listo"); out()
g2.tick(EVS)
ok(fase("B") == "decision", "al cerrar A, B pasa a decision")
ok(cola() == ["C"], "C sigue en cola")


# =========================================================================
print("\n=== 5. reinicio durante una decision ===")
g = limpiar()
g.tick([EVS[0]]); poner(a_las(18, 1)); g.tick(EVS[:2])
poner(a_las(18, 2)); g.tick(EVS)
g.handle_command("/listo", "/listo"); g.tick(EVS); out()   # t=0 de B
ok(fase("B") == "decision", "B en decision")

avanzar(3); g.tick(EVS)
ok(any(messages.COLA_DECISION_TITULO in x for x in out()), "recordatorio t=+3")
antes = db.one("SELECT decision_step, decision_next_at, decision_at "
               "FROM guardian_events WHERE event_id='B'")
ok(antes["decision_step"] == 1, "lleva 1 recordatorio")

g2 = reiniciar()
g2.tick(EVS)
t = out()
ok(not t, "reiniciar no reenvia nada (no vuelve a t=0)")
despues = db.one("SELECT decision_step, decision_next_at, decision_at "
                 "FROM guardian_events WHERE event_id='B'")
ok(dict(antes) == dict(despues), "el plazo absoluto y el paso se conservan")
ok(fase("B") == "decision" and cola() == ["C"], "B decision, C queued")

# el +8 tiene que caer donde correspondia, no 3 min despues del reinicio
poner(sched.from_iso(antes["decision_at"]) + timedelta(minutes=7))
g2.tick(EVS)
ok(not any(messages.COLA_DECISION_TITULO in x for x in out()), "a los +7 todavia no")
poner(sched.from_iso(antes["decision_at"]) + timedelta(minutes=8))
g2.tick(EVS)
vistos = [x for x in out() if messages.COLA_DECISION_TITULO in x]
ok(len(vistos) == 1, f"a los +8 exactamente uno ({len(vistos)}), sin ciclo duplicado")


# =========================================================================
print("\n=== 6. DESPUES + reinicio ===")
g = limpiar()
EV3 = [ics("Z", "activo", a_las(18, 0)), ics("A", "a", a_las(18, 1)),
       ics("B", "b", a_las(18, 2)), ics("C", "c", a_las(18, 3))]
g.tick([EV3[0]])
for i, ev in enumerate(EV3[1:], start=1):
    poner(a_las(18, i)); g.tick(EV3[:i + 1])
g.handle_command("/listo", "/listo"); g.tick(EV3); out()
ok(fase("A") == "decision" and cola() == ["B", "C"], "A en decision, [B, C] en cola")

g.handle_cola_callback(cb("despues", "A")); out()
ok(cola() == ["B", "C", "A"], f"tras DESPUES: {cola()}")

g2 = reiniciar(); g2.tick(EV3); out()
ok(cola() == ["C", "A"] and fase("B") == "decision",
   f"tras reiniciar el orden se respeta: B en decision, cola {cola()}")

g2.handle_cola_callback(cb("descartar", "B")); out()
g2.tick(EV3); out()
ok(fase("C") == "decision", "resuelto B, sigue C")
ok(cola() == ["A"], "y A sigue al final")


# =========================================================================
print("\n=== 7. un pendiente sobrevive indefinidamente sin decision ===")
g = limpiar()
EV_A = ics("A", "activo", a_las(18, 0)); EV_B = ics("B", "beta", a_las(18, 5))
g.tick([EV_A]); poner(a_las(18, 5)); g.tick([EV_A, EV_B])
g.cancel_active(); g.tick([EV_A, EV_B]); out()
ok(fase("B") == "decision", "B en decision")
for horas in (1, 3, 8, 24, 48):
    poner(a_las(18, 5) + timedelta(hours=horas))
    for _ in range(3): g.tick([EV_A, EV_B]); out()
    ok(fase("B") == "decision", f"+{horas}h sigue en decision")
ok(fase("B") not in ("done", "discarded"), "el tiempo no lo completo ni lo descarto")
ok(cuenta("discarded") == 0, "nada quedo descartado por el paso del tiempo")
ok(filas("B") == 1, "y sigue habiendo una sola fila")


# =========================================================================
print("\n=== 8. evento nuevo durante una decision ===")
g = limpiar()
EV_A = ics("A", "activo", a_las(18, 0)); EV_B = ics("B", "beta", a_las(18, 1))
g.tick([EV_A]); poner(a_las(18, 1)); g.tick([EV_A, EV_B])
g.handle_command("/listo", "/listo"); g.tick([EV_A, EV_B]); out()
ok(fase("B") == "decision", "B en decision")

EV_C = ics("C", "charlie", a_las(18, 10))
poner(a_las(18, 10)); g.tick([EV_A, EV_B, EV_C])
ok(fase("B") == "decision" and fase("C") == "queued", "C entra a cola, no adelanta a B")

EV_D = ics("D", "delta", a_las(18, 20))
poner(a_las(18, 20)); g.tick([EV_A, EV_B, EV_C, EV_D])
ok(fase("B") == "decision" and cola() == ["C", "D"], f"B decision, cola {cola()}")
out()


# =========================================================================
print("\n=== 9. un callback desconocido no rompe ni mueve nada ===")
g.handle_cola_callback({"id": "c", "data": f"cola:re60:{rid('B')}",
                        "message": {"message_id": 7, "chat": {"id": "999"}}})
ok(fase("B") == "decision", "un 'cola:re60' viejo ya no hace nada")
ok(cola() == ["C", "D"], f"la cola no se mueve: {cola()}")
EV_E = ics("E", "echo", a_las(18, 30))
poner(a_las(18, 30)); g.tick([EV_A, EV_B, EV_C, EV_D, EV_E])
ok(fase("B") == "decision", "B sigue ocupando el canal")
ok(fase("E") == "queued" and cola() == ["C", "D", "E"], f"E a la cola: {cola()}")
out()


# =========================================================================
print("\n=== 10. cambio de dia ===")
g = limpiar(a_las(23, 50))
EV_A = ics("A", "activo", a_las(23, 50)); EV_B = ics("B", "beta", a_las(23, 55))
g.tick([EV_A])                       # 23:50 A entra en su ventana y se activa
ok(fase("A") == "brake", "23:50 A activo")
poner(a_las(23, 55)); g.tick([EV_A, EV_B])
ok(fase("B") == "queued", "23:55 B a la cola")
g.handle_command("/listo", "/listo"); g.tick([EV_A, EV_B]); out()
poner(a_las(23, 58))
EV_C = ics("C", "charlie", a_las(23, 58))
g.tick([EV_A, EV_B, EV_C])
ok(fase("B") == "decision" and fase("C") == "queued", "23:58 B decision, C queued")
out()
poner(a_las(0, 5, dia=1))
for _ in range(5): g.tick([EV_A, EV_B, EV_C]); out()
ok(fase("B") == "decision", "00:05 B sigue en decision")
ok(fase("C") == "queued", "00:05 C sigue en cola")
ok(cuenta("discarded") == 0, "nada se marco descartado por el cambio de dia")
ok(filas("B") == 1 and filas("C") == 1, "y nada se borro")


# =========================================================================
print("\n=== 11. un solo ciclo agregado ===")
g = limpiar()
EVS = [ics("A", "activo", a_las(18, 0)), ics("B", "b", a_las(18, 1)),
       ics("C", "c", a_las(18, 2)), ics("D", "d", a_las(18, 3))]
g.tick([EVS[0]])
for i in range(1, 4):
    poner(a_las(18, i)); g.tick(EVS[:i + 1])
out()
avanzar(16); g.tick(EVS)
agregados = [x for x in out() if "eventos pendientes" in x]
ok(len(agregados) == 1 and "3 eventos" in agregados[0], f"un ciclo, 3 eventos: {agregados}")

EV_E = ics("E", "e", RELOJ["t"])
g.tick(EVS + [EV_E]); out()
avanzar(16); g.tick(EVS + [EV_E])
agregados = [x for x in out() if "eventos pendientes" in x]
ok(len(agregados) == 1, f"sigue habiendo UN solo ciclo ({len(agregados)})")
ok("4 eventos" in agregados[0], f"y refleja la cantidad correcta: {agregados[0]}")


# =========================================================================
print("\n=== 12. transicion activo -> decision: sin avisos solapados ===")
g.handle_command("/listo", "/listo"); out()
g.tick(EVS + [EV_E])
t = out()
ok(any(messages.COLA_DECISION_TITULO in x for x in t), "arranca la cadencia de decision")
ok(not any("eventos pendientes" in x for x in t), "y no manda el agregado en el mismo momento")
ok(db.get_state(G.COLA_AVISO_KEY) is None, "el ciclo agregado quedo apagado")
for _ in range(20):
    avanzar(1); g.tick(EVS + [EV_E])
    ok_agg = [x for x in out() if "eventos pendientes" in x]
    if ok_agg:
        ok(False, f"el agregado revivio sin activo: {ok_agg}")
        break
else:
    ok(True, "en 20 minutos sin activo no vuelve a sonar el agregado")


# =========================================================================
print("\n=== 13. doble select consecutivo ===")
g = limpiar()
EV_A = ics("A", "a", a_las(18, 0)); EV_B = ics("B", "b", a_las(18, 0))
g.tick([EV_A, EV_B])              # los dos vencen a la vez
ok(fase("A") == "brake" and fase("B") == "queued", "uno activo, el otro en cola")
antes = [dict(r) for r in db.query("SELECT event_id, phase, queue_seq FROM guardian_events ORDER BY event_id")]
out()
for _ in range(4):
    g.tick([EV_A, EV_B])          # lecturas consecutivas del mismo estado
despues = [dict(r) for r in db.query("SELECT event_id, phase, queue_seq FROM guardian_events ORDER BY event_id")]
ok(antes == despues, "ticks repetidos no cambian nada")
ok(not out(), "ni generan mensajes")
ok(cuenta("queued") == 1 and db.one("SELECT COUNT(*) c FROM guardian_events")["c"] == 2,
   "sin duplicados de fase ni de fila")


# =========================================================================
print("\n=== 14. identidad del evento ===")
g = limpiar()
# Mismo titulo y misma hora, ids distintos: son dos eventos distintos.
g.tick([ics("id-1", "comer", a_las(18, 0)), ics("id-2", "comer", a_las(18, 0))])
ok(db.one("SELECT COUNT(*) c FROM guardian_events")["c"] == 2,
   "dos ids distintos = dos eventos, aunque coincidan titulo y hora")
out()
# Mismo id con titulo cambiado en el ICS: sigue siendo el mismo evento.
g.tick([ics("id-1", "comer distinto", a_las(18, 0))])
ok(db.one("SELECT COUNT(*) c FROM guardian_events")["c"] == 2,
   "cambiar el texto no crea un evento nuevo: la identidad es el id")


# =========================================================================
print("\n=== 15. las cuatro decisiones + doble click ===")
def escenario():
    g = limpiar()
    evs = [ics("A", "activo", a_las(18, 0)), ics("B", "b", a_las(18, 1)),
           ics("C", "c", a_las(18, 2))]
    g.tick([evs[0]]); poner(a_las(18, 1)); g.tick(evs[:2])
    poner(a_las(18, 2)); g.tick(evs)
    g.handle_command("/listo", "/listo"); g.tick(evs); out()
    return g, evs

g, evs = escenario()
g.handle_cola_callback(cb("ahora", "B")); out()
ok(fase("B") == "brake", "AHORA -> brake")
g.tick(evs)
ok(messages.GUARDIAN_ORIENTACION in out(), "  y entra al Guardian de siempre")
g.handle_cola_callback({"id": "c", "data": f"cola:ahora:{rid('B')}",
                        "message": {"message_id": 7, "chat": {"id": "999"}}})
ok(fase("B") == "brake", "doble click en AHORA no cambia nada")
ok(any(messages.COLA_BOTON_EXPIRADO in x for x in out()), "  y avisa que el boton expiro")

g, evs = escenario()
g.handle_cola_callback(cb("despues", "B")); out()
ok(cola() == ["C", "B"], f"DESPUES rota al final: {cola()}")
g.handle_cola_callback({"id": "c", "data": f"cola:despues:{rid('B')}",
                        "message": {"message_id": 7, "chat": {"id": "999"}}})
ok(cola() == ["C", "B"], "doble click no vuelve a rotar")
out()

g, evs = escenario()
g.handle_cola_callback(cb("descartar", "B")); out()
ok(fase("B") == "discarded" and filas("B") == 1, "DESCARTAR -> discarded, fila conservada")
g.handle_cola_callback({"id": "c", "data": f"cola:descartar:{rid('B')}",
                        "message": {"message_id": 7, "chat": {"id": "999"}}})
ok(fase("B") == "discarded", "doble click no crea un estado imposible")
ok(any(messages.COLA_BOTON_EXPIRADO in x for x in out()), "  avisa que expiro")


# =========================================================================
print("\n=== 17. Intervalos sin tocar ===")
from modules.intervalos import MOMENTOS_AVISO, ESPERA_MINUTOS, HORAS_CIERRE, MAX_FILAS
ok(MOMENTOS_AVISO == (0, 150, 180, 420), f"MOMENTOS_AVISO {MOMENTOS_AVISO}")
ok(ESPERA_MINUTOS == 76 and HORAS_CIERRE == 4 and MAX_FILAS == 10, "constantes intactas")
ok(messages.INTERVALOS_AVISO == "⏱ Intervalo cumplido.", "aviso intacto")
ok(messages.INTERVALOS_TITULO and messages.INTERVALOS_SIN_MARCAS, "textos presentes")

db.close(); TMP.unlink(missing_ok=True)
print("\n" + "=" * 52)
print("FALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
