"""/tiempo: primera libre, las demas con una decision delante. Sin prohibicion."""
import os, sys, dataclasses, json
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics", MASTIL_TIMEZONE="UTC")

import config as cm, messages
import modules.intervalos as I
from database import Database
from core.router import Router
from modules.intervalos import IntervalosModule, TIEMPO_USADO_KEY

# Este Python de Windows no trae tzdata; Intervalos usa ZoneInfo solo para el
# dia local de la marca.
I.ZoneInfo = lambda nombre: timezone.utc

YO = "999"
TMP = Path(os.environ["TEMP"]) / "tfric.db"
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP)

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

class TG:
    def answer_callback(s, *a, **k): pass
    def send_message(s, *a, **k): return {"ok": True}
class Nada:
    enabled = False
    def __getattr__(s, n): return lambda *a, **k: False

db = None
def montar():
    global db, inter, r
    if db: db.close()
    TMP.unlink(missing_ok=True)
    db = Database(cfg.db_path, cfg.schema_path); db.migrate()
    inter = IntervalosModule(cfg, db)
    mods = {"intervalos": inter}
    for k in ("panel","vigia","timer","system","pomodoro","gmail",
              "guardian","calendar","lite"):
        mods[k] = Nada()
    r = Router(cfg, db, TG(), mods)
    return inter, r

def out():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL"); return f
def ultimo():
    f = out()
    return f[-1] if f else None
def btns(f): return [b[1] for g in json.loads(f["buttons"]) for b in g] if f and f["buttons"] else []
def etiq(f): return [b[0] for g in json.loads(f["buttons"]) for b in g] if f and f["buttons"] else []

def marcar(n): inter.handle("/marca", f"src-{n}"); out()
def tiempo(): inter.handle("/tiempo", None); return ultimo()
def mostrar(): inter.handle("/tiempo_mostrar", None); return ultimo()
def dejarlo(): inter.handle("/tiempo_dejarlo", None); return ultimo()

def es_tiempo(f):
    """El mensaje con el tiempo real, no la friccion."""
    t = (f["text"] or "") if f else ""
    return "marca" in t.lower() and messages.INTERVALOS_TIEMPO_FRICCION not in t
def es_friccion(f):
    return messages.INTERVALOS_TIEMPO_FRICCION in ((f["text"] or "") if f else "")


print("=== 1. primera consulta: directa ===")
montar(); marcar(1)
f = tiempo()
ok(es_tiempo(f), "muestra el tiempo")
ok(not es_friccion(f), "sin friccion")

print("\n=== 2/3. segunda: friccion, NO el tiempo ===")
f = tiempo()
ok(es_friccion(f), "aparece la friccion")
ok(not es_tiempo(f), "y NO muestra el tiempo")
ok(btns(f) == ["/tiempo_mostrar", "/tiempo_dejarlo"], f"dos botones ({btns(f)})")
ok(etiq(f) == ["✅ MOSTRAR", "↩️ DEJARLO"], f"con esas etiquetas ({etiq(f)})")

print("\n=== 4. DEJARLO cierra sin mostrar ===")
estado_antes = db.get_state(TIEMPO_USADO_KEY)
f = dejarlo()
ok(messages.INTERVALOS_TIEMPO_DEJADO in (f["text"] or ""), "responde y cierra")
ok(not es_tiempo(f), "sin mostrar el tiempo")
ok(db.get_state(TIEMPO_USADO_KEY) == estado_antes, "y no cambia ningun estado")

print("\n=== 5. MOSTRAR si muestra ===")
f = mostrar()
ok(es_tiempo(f), "muestra el tiempo")

print("\n=== 6/7/8. la friccion vuelve, indefinidamente ===")
for vuelta in range(1, 5):
    f = tiempo()
    ok(es_friccion(f), f"consulta extra {vuelta}: friccion otra vez")
    f = mostrar()
    ok(es_tiempo(f), f"  y MOSTRAR funciona la vez {vuelta}")

print("\n=== la secuencia que pediste: /tiempo x4 ===")
montar(); marcar(1)
resultados = []
for _ in range(4):
    resultados.append("tiempo" if es_tiempo(tiempo()) else "friccion")
ok(resultados == ["tiempo", "friccion", "friccion", "friccion"],
   f"solo la primera es directa ({resultados})")
seguidas = ["tiempo" if es_tiempo(mostrar()) else "no" for _ in range(3)]
ok(seguidas == ["tiempo"] * 3, f"y MOSTRAR funciona las 3 veces ({seguidas})")

print("\n=== no hay tope: 15 veces seguidas ===")
for _ in range(15):
    tiempo(); mostrar()
ok(es_tiempo(mostrar()), "a la 15 sigue funcionando")
ok(es_friccion(tiempo()), "y la friccion sigue apareciendo")

print("\n=== 9. una marca nueva devuelve la consulta libre ===")
marcar(2)
f = tiempo()
ok(es_tiempo(f), "primera del intervalo nuevo: directa")
ok(es_friccion(tiempo()), "y la segunda vuelve a la friccion")

print("\n=== 10. el estado sobrevive el reinicio ===")
usado = db.get_state(TIEMPO_USADO_KEY)
inter2 = IntervalosModule(cfg, db)
inter2.handle("/tiempo", None)
ok(es_friccion(ultimo()), "reiniciar NO devuelve la consulta libre")
ok(db.get_state(TIEMPO_USADO_KEY) == usado, "el estado es el mismo")
inter2.handle("/tiempo_mostrar", None)
ok(es_tiempo(ultimo()), "y MOSTRAR sigue andando tras reiniciar")

print("\n=== sin marcas ===")
montar()
f = tiempo()
ok(messages.INTERVALOS_SIN_MARCAS in (f["text"] or ""), "dice que no hay marcas")
ok(db.get_state(TIEMPO_USADO_KEY) is None, "y no gasta la consulta libre")
f = mostrar()
ok(messages.INTERVALOS_SIN_MARCAS in (f["text"] or ""), "MOSTRAR sin marcas tambien avisa")

print("\n=== por el router, como los botones reales ===")
montar(); marcar(1)
def cb(d): return {"callback_query": {"id": "c", "data": d, "from": {"id": YO},
                                      "message": {"message_id": 7, "chat": {"id": YO}}}}
r.process({"message": {"message_id": 1, "chat": {"id": YO}, "from": {"id": YO}, "text": "/tiempo"}})
out()
r.process({"message": {"message_id": 2, "chat": {"id": YO}, "from": {"id": YO}, "text": "/tiempo"}})
ok(es_friccion(ultimo()), "el router entrega la friccion")
r.process(cb("/tiempo_mostrar"))
ok(es_tiempo(ultimo()), "y el boton MOSTRAR llega a Intervalos")
r.process(cb("/tiempo_dejarlo"))
ok(messages.INTERVALOS_TIEMPO_DEJADO in (ultimo()["text"] or ""), "y DEJARLO tambien")

print("\n=== 11/12/13/14. nada mas cambio ===")
from modules.intervalos import (MOMENTOS_AVISO, ESPERA_MINUTOS, HORAS_CIERRE,
                                MAX_FILAS, formato_duracion)
ok(MOMENTOS_AVISO == (0, 150, 180, 420), f"avisos intactos {MOMENTOS_AVISO}")
ok(ESPERA_MINUTOS == 76 and HORAS_CIERRE == 4 and MAX_FILAS == 10, "constantes intactas")
ok(formato_duracion(3661) == "1h 01m 01s" and formato_duracion(0) == "00m 00s",
   "el calculo no cambia")
ok(messages.INTERVALOS_AVISO == "⏱ Intervalo cumplido.", "el aviso intacto")

montar()
inter.handle("/marca", "a"); t1 = out()
ok(any("TRAMO" in (x["text"] or "") for x in t1), "/marca devuelve su tabla igual")
inter.handle("/marca", "a")
ok(len(db.query("SELECT * FROM interval_marks")) == 1, "idempotencia de /marca intacta")
out()
inter.handle("/reset", None)
ok(any("Ciclo cerrado" in (x["text"] or "") for x in out()), "/reset igual")

from modules import reporte
filas, total = reporte.tabla_del_dia([datetime.now(timezone.utc),
                                      datetime.now(timezone.utc) + timedelta(minutes=5)])
ok(filas[0][1] == "Inicio" and total == "05m 00s", "el reporte no cambia")

# El aviso del intervalo es de `tick()` y no tiene nada que ver con /tiempo.
montar()
db.execute(
    "INSERT INTO interval_marks(user_id, marked_at_utc, local_day, request_id) "
    "VALUES (?,?,?,?)",
    (YO, (datetime.now(timezone.utc) - timedelta(minutes=80)).isoformat(),
     "2026-08-19", "viejo"),
)
inter.tick()
ok(any(messages.INTERVALOS_AVISO in (x["text"] or "") for x in out()),
   "el aviso de los 76 min sigue saliendo")
ok(es_tiempo(tiempo()), "y no consumio la consulta libre del intervalo")

db.close(); TMP.unlink(missing_ok=True)
print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
