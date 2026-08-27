"""Pruebas del Panel. Sólo lo que agrega esta capa: que los botones lleguen
al mismo handler que los comandos y que no cambien nada de lo que ya había."""

import os, sys, dataclasses
from pathlib import Path

RAIZ = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics",
                  MASTIL_TIMEZONE="America/Santiago")

import config as cm
import messages
from database import Database
from core.router import Router
from modules.panel import PanelModule, MENUS

YO, AJENO = "999", "555"
TMP = Path(os.environ["TEMP"]) / "panel_test.db"
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP)
cfg.db_path.unlink(missing_ok=True)
db = Database(cfg.db_path, cfg.schema_path); db.migrate()

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

def outbox():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL")
    return f


class TG:
    def __init__(self): self.answered = []
    def answer_callback(self, cid, text="", show_alert=False): self.answered.append(cid)
    def send_message(self, *a, **k): return {"ok": True}


class Espia:
    """Módulo falso: anota (command, raw_text) sin ejecutar nada.

    `source_id` es opcional porque el de Calendar lo recibe y el resto no."""
    def __init__(self, dueño=()):
        self.visto = []; self.dueño = dueño; self.sorpresas = []
    def enviar_sorpresa(self, texto, foto=None):
        self.sorpresas.append((texto, foto)); return True
    def handle_command(self, command, raw_text, source_id=None):
        self.visto.append((command, raw_text))
        return command in self.dueño
    def handle(self, command, source_id=None): self.visto.append((command, source_id)); return True
    def stop(self, *a, **k): pass
    def restore_calendar(self, *a, **k): pass
    def matches(self, *a, **k): return False
    def handle_message(self, *a, **k): return False
    def handle_text(self, *a, **k): return False
    def handle_photo(self, *a, **k): return False


def montar():
    db.execute("DELETE FROM outbox")
    panel = PanelModule(cfg, db)
    mods = {
        "panel": panel,
        "intervalos": Espia(),
        "calendar": Espia(("/cal",)),
        "timer": Espia(("/timer", "/tm", "/timer_pausar", "/timer_reanudar",
                        "/timer_cancelar", "/apagar")),
        "pomodoro": Espia(("/pomodoro", "/pomo_estado", "/descanso", "/stop")),
        "gmail": Espia(("/gmail_hay", "/gmail_remitentes", "/gmail_ayuda",
                        "/gmail_contenido")),
        "system": Espia(("/admin", "/estado", "/suspender", "/reanudar",
                         "/cancelar", "/reset_estado", "/sorpresa",
                         "/recordatorios_lite")),
        "guardian": Espia(), "lite": Espia(), "vigia": Espia(),
    }
    tg = TG()
    r = Router(cfg, db, tg, mods)
    panel.attach(r)
    return r, mods, tg, panel


def cb(data, chat=YO, mid=77, cid="c1"):
    return {"callback_query": {"id": cid, "data": data, "from": {"id": chat},
                               "message": {"message_id": mid, "chat": {"id": chat}}}}

def msg(text, chat=YO, mid=5):
    return {"message": {"message_id": mid, "chat": {"id": chat},
                        "from": {"id": chat}, "text": text}}

def ultimo():
    filas = outbox()
    return filas[-1] if filas else None

def botones(fila):
    import json
    return json.loads(fila["buttons"]) if fila and fila["buttons"] else []

def datos_de(fila):
    return [b[1] for grupo in botones(fila) for b in (grupo if isinstance(grupo[0], list) else [grupo])]


print("=== 1. /panel muestra los 6 modulos ===")
r, mods, tg, panel = montar()
r.process(msg("/panel"))
f = ultimo()
ok(f is not None and f["text"] == "⚓ MÁSTIL", "titulo ⚓ MÁSTIL")
ok(f["kind"] == "text", "el primero es mensaje nuevo, no edicion")
esperados = ["panel:intervalos", "panel:calendar", "panel:timer",
             "panel:pomodoro", "panel:gmail", "panel:system", "panel:vigia"]
ok(datos_de(f) == esperados, f"los 7 modulos ({datos_de(f)})")
ok(all(d not in datos_de(f) for d in ("/marca", "/tiempo", "/reset")),
   "marca/tiempo/reset NO estan en el panel principal")

print("\n=== 2. cada modulo abre su submenu EDITANDO ===")
for data, titulo in [("panel:intervalos", "⏱️ INTERVALOS"),
                     ("panel:calendar", "📅 CALENDARIO"),
                     ("panel:pomodoro", "🍅 POMODORO"),
                     ("panel:gmail", "📬 GMAIL"),
                     ("panel:system", "⚙️ SISTEMA")]:
    r, mods, tg, panel = montar()
    r.process(cb(data))
    f = ultimo()
    ok(f["text"] == titulo and f["kind"] == "edit" and f["message_id"] == 77,
       f"{data} -> {titulo} editando el mismo mensaje")
    ok("panel:home" in datos_de(f), f"   y tiene [🏠 PANEL]")
    ok(tg.answered == ["c1"], "   responde el callback (sin spinner)")

print("\n=== 2b. TIMER se dibuja segun lo que haya corriendo ===")
r, mods, tg, panel = montar()
r.process(cb("panel:timer"))
f = ultimo()
ok(f["text"] == messages.PANEL_TIMER_SIN_ACTIVO and f["kind"] == "edit",
   "sin timer: lo dice, editando el mismo mensaje")
ok(datos_de(f) == ["panel:tm:cuenta", "panel:tm:hora", "panel:tm:cada", "panel:home"],
   f"y ofrece las tres modalidades ({datos_de(f)})")
ok(all(d not in datos_de(f) for d in ("/timer_pausar", "/timer_cancelar", "/apagar")),
   "sin botones para un timer que no existe")

print("\n=== 2c. con timer activo ofrece salir de el, no crear otro ===")
db.execute("UPDATE timer SET active=1, status='running', modo='repeating', "
           "interval_minutes=50 WHERE id=1")
mods["timer"].resumen_actual = lambda: "🔁 Repetitivo, cada 50 min"
outbox()
r.process(cb("panel:timer"))
f = ultimo()
ok("Repetitivo" in (f["text"] or ""), "muestra el resumen de lo que corre")
ok("/timer_cancelar" in datos_de(f), "y DETENER")
ok("/timer_pausar" not in datos_de(f), "sin PAUSAR: no aplica a un repetitivo")
ok("panel:tm:modos" in datos_de(f), "con salida para cambiar de modalidad")
outbox()
r.process(cb("panel:tm:modos"))
ok(datos_de(ultimo())[:3] == ["panel:tm:cuenta", "panel:tm:hora", "panel:tm:cada"],
   "que lleva a las tres, sin obligar a detener antes")
db.execute("UPDATE timer SET active=0, status='idle', modo='countdown', "
           "interval_minutes=0 WHERE id=1")

print("\n=== 2d. las tres modalidades por boton, sin escribir comandos ===")
r, mods, tg, panel = montar()
r.process(cb("panel:tm:cuenta"))
ok("/timer 30" in datos_de(ultimo()), "cuenta atras trae atajos de minutos")
r.process(cb("panel:tm:cada"))
ok("panel:tm:cada:50" in datos_de(ultimo()), "repetitivo trae atajos de intervalo")
outbox()
r.process(cb("panel:tm:cada:50"))
f = ultimo()
ok("cada 50" in (f["text"] or ""), "elegido el intervalo, pregunta por cuanto rato")
ok("/timer_cada 50 120" in datos_de(f),
   f"y los topes ya llevan el intervalo adentro ({datos_de(f)})")
ok(not any(d.startswith("/timer_cada 50") and len(d.split()) == 2
           for d in datos_de(f)), "ninguna salida crea un repetitivo sin tope")
r.process(cb("panel:tm:hora"))
ok("panel:tm:hora:pedir" in datos_de(ultimo()), "avisar a pide elegir la hora")
outbox()
r.process(cb("panel:tm:hora:pedir"))
ok("hora" in (ultimo()["text"] or "").lower(), "y pregunta cual")
r.process(msg("21:40"))
visto = mods["timer"].visto
ok(visto and visto[0][1] == "/timer_a 21:40",
   f"la hora escrita arma /timer_a (dio: {visto[0][1] if visto else None})")
r, mods, tg, panel = montar()
r.process(cb("panel:tm:cada:otro")); outbox()
r.process(msg("35"))
f = ultimo()
ok("cada 35" in (f["text"] or ""), "el intervalo escrito tambien pasa por el tope")
ok("/timer_cada 35 240" in datos_de(f),
   f"con sus cuatro duraciones (dio: {datos_de(f)})")
ok(not mods["timer"].visto, "y todavia NO creo nada: falta elegir el tope")

print("\n=== 3. 🏠 PANEL vuelve editando ===")
r, mods, tg, panel = montar()
r.process(cb("panel:timer")); outbox()
r.process(cb("panel:home"))
f = ultimo()
ok(f["text"] == "⚓ MÁSTIL" and f["kind"] == "edit" and f["message_id"] == 77,
   "vuelve al panel sobre el mismo mensaje")

print("\n=== 4/5. MARCA y TIEMPO usan el handler existente ===")
r, mods, tg, panel = montar()
ok(dict(zip(*[iter([])]*1)) == {} or True, "")
for etiqueta, data, comando in [("📍 MARCA", "/marca", "/marca"),
                                ("⌛ TIEMPO", "/tiempo", "/tiempo")]:
    r, mods, tg, panel = montar()
    r.process(cb(data))
    ok(mods["intervalos"].visto and mods["intervalos"].visto[0][0] == comando,
       f"{etiqueta} -> intervalos.handle({comando})")
    ok(not outbox(), "   el panel no genero mensaje propio")

print("\n=== 6. RESET pide confirmacion ===")
r, mods, tg, panel = montar()
r.process(cb("panel:int:reset"))
f = ultimo()
ok(f["text"] == "🔄 ¿Cerrar el ciclo actual?", "muestra la confirmacion")
ok(datos_de(f) == ["panel:int:reset:ok", "panel:intervalos"], "CERRAR CICLO / VOLVER")
ok(not mods["intervalos"].visto, "todavia NO ejecuto /reset")
r.process(cb("panel:int:reset:ok"))
ok(mods["intervalos"].visto and mods["intervalos"].visto[0][0] == "/reset",
   "solo CERRAR CICLO ejecuta /reset")

print("\n=== 7/8/9. Calendario arma el /cal equivalente ===")
casos = [
    ("panel:cal:hoy",    ["**comer", "18:30"],          "/cal **comer 18:30"),
    ("panel:cal:manana", ["++ordenar", "19:30"],        "/cal ++ordenar next 19:30"),
    ("panel:cal:otro",   ["12/11", "barrer", "20:00"],  "/cal barrer 12/11 20:00"),
]
for boton, entradas, esperado in casos:
    r, mods, tg, panel = montar()
    r.process(cb(boton))
    for t in entradas:
        r.process(msg(t))
    visto = mods["calendar"].visto
    ok(visto and visto[0][1] == esperado, f"{boton} -> {esperado}   (dio: {visto[0][1] if visto else None})")

r, mods, tg, panel = montar()
r.process(cb("panel:cal:manana")); r.process(msg("++ordenar")); r.process(msg("19:30"))
ok("++ordenar" in mods["calendar"].visto[0][1], "MAÑANA no toca la razon ++")
ok(mods["calendar"].visto[0][1].count("next") == 1, "MAÑANA agrega next una sola vez")

print("\n=== 10. Timer preset llama al mismo handler ===")
for minutos in (5, 10, 15, 20, 30, 45):
    r, mods, tg, panel = montar()
    r.process(cb(f"/timer {minutos}"))
    v = mods["timer"].visto
    ok(v and v[0] == ("/timer", f"/timer {minutos}"), f"[{minutos} MIN] -> /timer {minutos}")

print("\n=== 11. Timer configurable conserva minutos/avisos/razon ===")
r, mods, tg, panel = montar()
r.process(cb("panel:tm:config"))
ok(ultimo()["text"] == "⏲️ ¿Cuántos minutos?", "paso 1 pide minutos")
r.process(msg("60"))
f = ultimo()
ok(f["text"] == "🔔 ¿Avisos?" and datos_de(f)[:2] == ["panel:tm:avisos:no", "panel:tm:avisos:si"],
   "paso 2 ofrece avisos")
r.process(cb("panel:tm:avisos:si")); r.process(msg("15 30"))
f = ultimo()
ok(f["text"] == "📝 ¿Razón?", "paso 3 pide razon")
r.process(cb("panel:tm:razon:si")); r.process(msg("terminar informe"))
v = mods["timer"].visto
ok(v and v[0][1] == "/timer 60 15 30 terminar informe", f"arma /timer 60 15 30 terminar informe (dio: {v[0][1] if v else None})")

r, mods, tg, panel = montar()
r.process(cb("panel:tm:config")); r.process(msg("25"))
r.process(cb("panel:tm:avisos:no")); r.process(cb("panel:tm:razon:no"))
ok(mods["timer"].visto[0][1] == "/timer 25", "sin avisos ni razon -> /timer 25")

r, mods, tg, panel = montar()
r.process(cb("panel:tm:otro")); r.process(msg("7"))
ok(mods["timer"].visto[0][1] == "/timer 7", "OTRO -> /timer 7")

print("\n=== 12. Gmail contenido conserva N + formato ===")
r, mods, tg, panel = montar()
r.process(cb("panel:gm:contenido"))
ok(ultimo()["text"] == "📨 ¿Número del correo?", "pide el numero")
r.process(msg("1"))
f = ultimo()
ok(f["text"] == "📄 Formato", "muestra formato")
ok(datos_de(f) == ["/gmail_contenido 1 natural", "/gmail_contenido 1 base64", "panel:gmail"],
   f"los botones llevan N y el formato ({datos_de(f)})")
r.process(cb("/gmail_contenido 1 base64"))
ok(mods["gmail"].visto[0] == ("/gmail_contenido", "/gmail_contenido 1 base64"),
   "y llega al handler existente")

print("\n=== 13. Sorpresa conserva el mensaje literal ===")
r, mods, tg, panel = montar()
r.process(cb("panel:sys:sorpresa"))
ok(messages.PANEL_SORPRESA_MENU in (ultimo()["text"] or ""), "abre el menu con/sin foto")
r.process(cb("panel:sor:texto"))
ok(messages.SORPRESA_PIDE_TEXTO_SIN_FOTO in (ultimo()["text"] or ""), "pide el mensaje")
r.process(msg("Que tengas  linda noche 🌙"))
ok(ultimo()["text"] == messages.sorpresa("Que tengas  linda noche 🌙"),
   "la preview conserva el texto literal, con emoji y espacios")
r.process(cb("panel:sor:enviar"))
ok(mods["system"].sorpresas == [("Que tengas  linda noche 🌙", None)],
   f"y lo envia tal cual ({mods['system'].sorpresas})")

print("\n=== 14. usuario no autorizado ===")
r, mods, tg, panel = montar()
r.process(cb("panel:timer", chat=AJENO))
ok(not outbox(), "un ajeno no abre menus")
r.process(cb("/timer 10", chat=AJENO))
ok(not mods["timer"].visto, "ni ejecuta acciones")
r.process(msg("/panel", chat=AJENO))
ok(not outbox(), "ni /panel")

print("\n=== 15. un pendiente NO se traga comandos ===")
r, mods, tg, panel = montar()
r.process(cb("panel:sys:sorpresa")); outbox()
r.process(msg("/estado"))
ok(mods["system"].visto and mods["system"].visto[0][0] == "/estado", "/estado se ejecuta normal")
ok(all(v[0] != "/sorpresa" for v in mods["system"].visto), "y NO se convirtio en sorpresa")
ok(not panel._pendientes, "el formulario abandonado se descarta")
r.process(msg("texto suelto"))
ok(all("texto suelto" not in (v[1] or "") for v in mods["system"].visto),
   "un texto posterior ya no lo captura el panel")

r, mods, tg, panel = montar()
r.process(cb("panel:cal:hoy")); outbox()
r.process(cb("panel:home"))
ok(not panel._pendientes, "🏠 PANEL tambien sale del formulario")

print("\n=== 16. los comandos de siempre siguen andando ===")
r, mods, tg, panel = montar()
for texto, modulo, comando in [
    ("/marca", "intervalos", "/marca"), ("/tiempo", "intervalos", "/tiempo"),
    ("/cal **comer 18:30", "calendar", "/cal"), ("/timer 10", "timer", "/timer"),
    ("/pomodoro", "pomodoro", "/pomodoro"), ("/gmail_hay", "gmail", "/gmail_hay"),
    ("/estado", "system", "/estado"),
]:
    r, mods, tg, panel = montar()
    r.process(msg(texto))
    v = mods[modulo].visto
    ok(v and v[0][0] == comando, f"{texto} -> {modulo}")

print("\n=== 17. navegar no encadena mensajes nuevos ===")
r, mods, tg, panel = montar()
r.process(msg("/panel")); outbox()
for d in ["panel:timer", "panel:home", "panel:gmail", "panel:home", "panel:intervalos"]:
    r.process(cb(d))
filas = outbox()
ok(len(filas) == 5, f"5 navegaciones -> 5 filas ({len(filas)})")
ok(all(f["kind"] == "edit" and f["message_id"] == 77 for f in filas),
   "todas ediciones del MISMO mensaje, cero mensajes nuevos")

print("\n=== 18. no toque Intervalos ===")
from modules.intervalos import MOMENTOS_AVISO, ESPERA_MINUTOS
ok(MOMENTOS_AVISO == (0, 150, 180, 420), f"MOMENTOS_AVISO intacto {MOMENTOS_AVISO}")
ok(ESPERA_MINUTOS == 76, "ESPERA_MINUTOS intacto")
ok(messages.INTERVALOS_AVISO == "⏱ Intervalo cumplido.", "su aviso intacto")

db.close(); cfg.db_path.unlink(missing_ok=True)
print("\n" + "=" * 52)
print("FALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
