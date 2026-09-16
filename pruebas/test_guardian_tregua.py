"""Tregua de 11 minutos y baja frecuencia a los 70. Reloj falso: ningun sleep."""

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

TMP = Path(os.environ["TEMP"]) / "guardian_tregua.db"
IMG = Path(os.environ["TEMP"]) / "guardian_tregua_img"; IMG.mkdir(exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id="999", db_path=TMP,
                          evidence_dir=IMG / "evidence")

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

db = None
def limpiar():
    global db
    if db: db.close()
    TMP.unlink(missing_ok=True)
    RELOJ["t"] = BASE
    db = Database(cfg.db_path, cfg.schema_path); db.migrate()
    return GuardianModule(cfg, db)

def filas():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL")
    return f

def out():
    return [x["text"] or "" for x in filas()]

def botones(fila):
    if not fila or not fila["buttons"]:
        return []
    datos = json.loads(fila["buttons"])
    salida = []
    for x in datos:
        if isinstance(x, list) and x and isinstance(x[0], list):
            salida += [b[1] for b in x]
        elif isinstance(x, list) and len(x) == 2 and isinstance(x[1], str):
            salida.append(x[1])
    return salida

def ev(eid, titulo, minutos=0):
    return {"id": eid, "title": f"** {titulo}",
            "start": RELOJ["t"] + timedelta(minutes=minutos)}

def fila_evento(eid):
    return db.one("SELECT * FROM guardian_events WHERE event_id = ?", (eid,))

def hasta_rafaga(g, eid="A", titulo="comer"):
    """Lleva un evento nuevo desde brake hasta su PRIMERA rafaga."""
    g.tick([ev(eid, titulo)]); out()          # nivel 1
    avanzar(8);  g.tick([]); out()            # nivel 2: el codigo de 4 digitos
    avanzar(16); g.tick([])                   # nivel 3: primera rafaga
    return filas()

# La secuencia ya no viaja en texto: se dibuja. Se captura envolviendo el
# renderizador, que es el unico lugar donde pasa en claro.
DIBUJADO = {"codigo": None, "veces": 0}
_dibujar_real = G.make_text_image
def _dibujar(texto, path):
    DIBUJADO["codigo"] = texto
    DIBUJADO["veces"] += 1
    return _dibujar_real(texto, path)
G.make_text_image = _dibujar

def codigo_de(fs):
    """Lo que se dibujo en la ultima imagen de tregua."""
    return DIBUJADO["codigo"]


print("=== 1. la PRIMERA rafaga no ofrece tregua ===")
g = limpiar()
fs = hasta_rafaga(g)
ok(len(fs) == G.RAFAGA_MENSAJES, f"la rafaga son {G.RAFAGA_MENSAJES} mensajes ({len(fs)})")
ok(all("/guardian_tregua" not in botones(f) for f in fs), "ninguno ofrece la tregua")
ok(fila_evento("A")["rafagas"] == 1, "va una rafaga")
inicio = fila_evento("A")["intervencion_at"]
ok(bool(inicio), "y quedo sellado el inicio de la intervencion")

print("\n=== 2. pedir tregua en la primera rafaga no corre ===")
g.handle_command("/guardian_tregua", "/guardian_tregua")
ok(messages.GUARDIAN_TREGUA_VIEJA in out(), "avisa que ese boton no aplica")
ok(not fila_evento("A")["tregua_code_hash"], "y no genera secuencia")

print("\n=== 3. la SEGUNDA rafaga ofrece la tregua en su ultimo mensaje ===")
avanzar(6); g.tick([]); fs = filas()
ok(fila_evento("A")["rafagas"] == 2, "van dos rafagas")
con_tregua = [f for f in fs if "/guardian_tregua" in botones(f)]
ok(len(con_tregua) == 1, f"exactamente un mensaje la ofrece ({len(con_tregua)})")
ok(con_tregua[0]["id"] == fs[-1]["id"], "y es el ultimo de la rafaga")
ok("/listo" in botones(con_tregua[0]), "sin sacar LISTO de al lado")

print("\n=== 4. la secuencia va DIBUJADA, no en texto ===")
g.handle_command("/guardian_tregua", "/guardian_tregua")
fs = filas()
codigo = codigo_de(fs)
ok(DIBUJADO["veces"] == 1, "se dibujo una imagen")
con_foto = [f for f in fs if f["photo_path"]]
ok(len(con_foto) == 1, f"y sale como foto ({len(con_foto)})")
ok(Path(con_foto[0]["photo_path"]).exists(), "el archivo existe")
ok(codigo not in (con_foto[0]["text"] or ""),
   "la secuencia NO esta en el texto: no se puede copiar y pegar")
ok(codigo not in con_foto[0]["photo_path"], "ni en el nombre del archivo")
ok("imagen" in (con_foto[0]["text"] or "").lower(), "el texto manda a mirarla")

print("\n=== 4b. y trae letras, numeros y simbolos ===")
ok(codigo is not None and len(codigo) == G.TREGUA_CODIGO_LARGO,
   f"largo {G.TREGUA_CODIGO_LARGO} ({codigo!r})")
ok(any(c in G.TREGUA_LETRAS for c in codigo), "tiene letras")
ok(any(c in G.TREGUA_NUMEROS for c in codigo), "tiene numeros")
ok(any(c in G.TREGUA_SIMBOLOS for c in codigo), "tiene simbolos")
ok(not codigo.isdigit(), "no es un PIN de digitos")

print("\n=== 5. una secuencia incorrecta no concede la tregua ===")
malo = ("X" if codigo[0] != "X" else "Y") + codigo[1:]
ok(g.handle_text(malo) is True, "la toma como intento")
ok(messages.GUARDIAN_TREGUA_MAL in out(), "y avisa que no coincide")
ok(not fila_evento("A")["tregua_hasta"], "sin tregua")
ok(bool(fila_evento("A")["tregua_code_hash"]), "la secuencia sigue viva: se puede reintentar")
ok(g.handle_text(codigo.lower()) is True
   and not fila_evento("A")["tregua_hasta"], "en minusculas tampoco sirve")
out()
ok(g.handle_text(codigo[:-1]) is False, "una secuencia parcial ni se considera")

print("\n=== 6. la secuencia correcta concede 11 minutos exactos ===")
pedido = ahora()
ok(g.handle_text(codigo) is True, "la acepta")
ok(any(messages.guardian_tregua_ok(G.TREGUA_MINUTOS) in x for x in out()), "lo confirma")
f = fila_evento("A")
hasta = sched.from_iso(f["tregua_hasta"])
ok(hasta == pedido + timedelta(minutes=G.TREGUA_MINUTOS),
   f"tregua hasta +{G.TREGUA_MINUTOS} min")
ok(not f["tregua_code_hash"], "y la secuencia queda inutilizable")

print("\n=== 7. durante la tregua no sale ni un mensaje ===")
ok(not out(), "la rafaga programada se corto")
for _ in range(5):
    avanzar(2); g.tick([])
ok(not out(), "diez minutos de silencio real")
ok(fila_evento("A")["phase"] == "insiste", "el evento sigue vivo, en su fase")

print("\n=== 8. al cumplirse los 11, Guardian retoma en un ciclo nuevo ===")
avanzar(2); fs_ciclo = []
g.tick([]); fs_ciclo = filas()
ok(len(fs_ciclo) == G.RAFAGA_MENSAJES, "vuelve la rafaga")
ok(fila_evento("A")["rafagas"] == 1, "y cuenta como la PRIMERA del ciclo nuevo")
ok(all("/guardian_tregua" not in botones(f) for f in fs_ciclo),
   "que, por ser primera, no ofrece tregua")

print("\n=== 8b. la segunda rafaga del ciclo nuevo la vuelve a ofrecer ===")
avanzar(6); g.tick([]); fs_ciclo = filas()
ok(fila_evento("A")["rafagas"] == 2, "segunda del ciclo")
con_tregua = [f for f in fs_ciclo if "/guardian_tregua" in botones(f)]
ok(len(con_tregua) == 1, f"la opcion reaparece, una sola vez ({len(con_tregua)})")
ok(con_tregua[0]["id"] == fs_ciclo[-1]["id"], "otra vez en el ultimo mensaje")

print("\n=== 8c. y se puede tomar una SEGUNDA tregua en la misma intervencion ===")
g.handle_command("/guardian_tregua", "/guardian_tregua")
codigo2 = codigo_de(filas())
ok(codigo2 is not None and codigo2 != codigo, "con una secuencia distinta")
pedido2 = ahora()
g.handle_text(codigo2); out()
f = fila_evento("A")
ok(sched.from_iso(f["tregua_hasta"]) == pedido2 + timedelta(minutes=G.TREGUA_MINUTOS),
   "otros 11 minutos")
ok(f["rafagas"] == 0, "y el ciclo vuelve a empezar de cero")
avanzar(4); g.tick([])
ok(not out(), "silencio otra vez")
avanzar(8); g.tick([])
ok(len(out()) == G.RAFAGA_MENSAJES, "y retoma igual que la primera vez")

print("\n=== 9. ninguna de las dos treguas reinicio el reloj de los 70 ===")
ok(fila_evento("A")["intervencion_at"] == inicio,
   "el inicio sigue siendo el de la primera rafaga de todas")

print("\n=== 10. a los 70 minutos exactos pasa a baja frecuencia ===")
RELOJ["t"] = sched.from_iso(inicio) + timedelta(minutes=G.INTERVENCION_MINUTOS - 1)
g.tick([]); out()
ok(fila_evento("A")["modo"] != "bajo", "a los 69 todavia no")
RELOJ["t"] = sched.from_iso(inicio) + timedelta(minutes=G.INTERVENCION_MINUTOS)
g.tick([]); fs = filas()
ok(fila_evento("A")["modo"] == "bajo", "a los 70 si")
ok(len(fs) == 1, f"con un solo mensaje, no una rafaga ({len(fs)})")
t = fs[0]["text"] or ""
ok("Dejo de insistir" in t, "avisa que baja el volumen")
ok("pendiente" in t.lower(), "dejando claro que sigue pendiente")
ok("fallaste" not in t.lower() and "rendi" not in t.lower(), "sin culpa")

print("\n=== 11. baja frecuencia: un mensaje cada 60 minutos ===")
avanzar(59); g.tick([])
ok(not out(), "a los 59 no manda nada")
avanzar(1); g.tick([])
ok(len(filas()) == 1, "a los 60 manda uno")
avanzar(60); g.tick([])
ok(len(filas()) == 1, "y otro a la hora siguiente")

print("\n=== 12-13. no se olvida el evento ni se vuelve a la rafaga ===")
f = fila_evento("A")
ok(f["phase"] == "insiste" and f["is_active"] == 1, "sigue activo y pendiente")
ok(f["phase"] not in ("done", "discarded"), "el reloj no lo resolvio ni lo descarto")
for _ in range(4):
    avanzar(60); g.tick([]); ok(len(filas()) == 1, "sigue un mensaje por hora")
ok(fila_evento("A")["modo"] == "bajo", "y no vuelve solo a intensidad alta")

print("\n=== 14. en baja frecuencia la tregua ya no se ofrece ===")
avanzar(60); g.tick([]); fs = filas()
ok(all("/guardian_tregua" not in botones(f) for f in fs),
   "el mensaje horario no la trae")
ok(fila_evento("A")["rafagas"] == 0 or fila_evento("A")["modo"] == "bajo",
   "y ya no hay ciclo de rafagas que la pueda ofrecer")
g.handle_command("/guardian_tregua", "/guardian_tregua")
ok(messages.GUARDIAN_TREGUA_VIEJA in out(), "el boton viejo avisa y no hace nada")
f = fila_evento("A")
ok(sched.is_due(f["tregua_hasta"]), "la unica tregua que hubo ya vencio")
ok(not f["tregua_code_hash"], "y no se genera secuencia nueva")

print("\n=== 15. /listo cierra igual que siempre ===")
g.handle_command("/listo", "/listo"); out()
ok(fila_evento("A")["phase"] == "done", "el evento queda done")
f = fila_evento("A")
ok(not f["intervencion_at"] and f["rafagas"] == 0 and not f["modo"],
   "y el estado nuevo queda limpio")

print("\n=== 16. la secuencia expira a los 5 minutos ===")
g = limpiar()
hasta_rafaga(g); avanzar(6); g.tick([]); out()
g.handle_command("/guardian_tregua", "/guardian_tregua")
codigo = codigo_de(filas())
avanzar(G.TREGUA_CODIGO_MINUTOS + 1)
ok(g.handle_text(codigo) is True, "la toma")
ok(messages.GUARDIAN_TREGUA_EXPIRADA in out(), "pero avisa que vencio")
f = fila_evento("A")
ok(not f["tregua_hasta"], "no concede tregua")
ok(not f["tregua_code_hash"], "y la secuencia se limpia")
avanzar(6); g.tick([])
ok(len(out()) == G.RAFAGA_MENSAJES, "Guardian sigue su flujo normal")
ok(bool(fila_evento("A")["intervencion_at"]), "sin tocar el reloj de los 70")

print("\n=== 17. un reinicio del proceso conserva el estado ===")
inicio = fila_evento("A")["intervencion_at"]
rafagas = fila_evento("A")["rafagas"]
g2 = GuardianModule(cfg, db)          # instancia nueva, misma base
f = fila_evento("A")
ok(f["intervencion_at"] == inicio and f["rafagas"] == rafagas,
   "el inicio y las rafagas sobreviven")
RELOJ["t"] = sched.from_iso(inicio) + timedelta(minutes=G.INTERVENCION_MINUTOS)
g2.tick([]); out()
ok(fila_evento("A")["modo"] == "bajo", "y los 70 minutos se cumplen igual")
avanzar(60); g2.tick([])
ok(len(filas()) == 1, "la baja frecuencia sigue despues del reinicio")

print("\n=== 18. un reinicio durante la tregua no la pierde ni duplica ===")
g = limpiar()
hasta_rafaga(g); avanzar(6); g.tick([]); out()
g.handle_command("/guardian_tregua", "/guardian_tregua")
g.handle_text(codigo_de(filas())); out()
g3 = GuardianModule(cfg, db)
avanzar(5); g3.tick([])
ok(not out(), "sigue en silencio tras el reinicio")
avanzar(7); g3.tick([])
ok(len(out()) == G.RAFAGA_MENSAJES, "y retoma una sola vez, sin duplicar")

print("\n=== 19. eventos distintos no comparten timers ===")
g = limpiar()
hasta_rafaga(g, "A", "comer"); avanzar(6); g.tick([]); out()
a = fila_evento("A")
g.handle_command("/listo", "/listo"); out()
avanzar(1)
hasta_rafaga(g, "B", "llamar"); out()
b = fila_evento("B")
ok(b["intervencion_at"] != a["intervencion_at"], "B arranca su propio reloj")
ok(b["rafagas"] == 1, "y su propio contador de rafagas")
ok(fila_evento("A")["phase"] == "done", "sin revivir a A")

print("\n=== 20. un evento que nunca llega a 70 se comporta igual que antes ===")
g = limpiar()
fs = hasta_rafaga(g)
ok(len(fs) == G.RAFAGA_MENSAJES, "rafaga de siempre")
avanzar(6); g.tick([])
ok(len(out()) == G.RAFAGA_MENSAJES, "y la siguiente igual")
g.handle_command("/listo", "/listo")
# El cierre ahora dice primero QUE se cerro y la medalla va debajo, en el
# mismo mensaje: diez minutos despues el chat tiene que decir que quedo hecho.
salida = out()
ok(any(m in x for x in salida for m in messages.MENSAJES_CIERRE),
   "/listo cierra con su medalla")
ok(any(x.startswith("✅ Cerrado:") for x in salida),
   "y nombra la tarea que se cerro")
ok(fila_evento("A")["phase"] == "done", "y queda done")

db.close()
TMP.unlink(missing_ok=True)
for x in (IMG / "guardian").glob("*.png"): x.unlink(missing_ok=True)
print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
