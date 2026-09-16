"""Calendario: la hora en reloj de 12, con AM/PM.

`9:30 a` y `9 p` se entienden solos. Una hora de 1 a 12 sin sufijo se pregunta
en vez de adivinarse: agendar el dentista a las 9 de la noche en vez de las 9
de la mañana no es un detalle de formato.

Las 00 no se usan: la medianoche se escribe `12 a`. Dos formas de decir lo
mismo es justo lo que obliga a pensar antes de escribir.
"""

import os, sys, dataclasses
from pathlib import Path

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import messages
from database import Database
from modules.panel import PanelModule
from modules.calendar_commands import (ESTADO_AMBIGUA, ESTADO_INVALIDA,
                                       ESTADO_OK, ESTADO_SIN_CERO,
                                       interpretar_hora, token_hora)

YO = "999"
TMP = Path(os.environ["TEMP"]) / "cal_ampm" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP)

FALLAS = 0


def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c:
        FALLAS += 1


class TimerFalso:
    # AVISAR A cierra volviendo a la pantalla del Timer, que le pregunta al
    # modulo que hay corriendo.
    def resumen_actual(self):
        return ""


class RouterFalso:
    def __init__(self):
        self.comandos = []
        self.modules = {"timer": TimerFalso()}

    def handle_command(self, comando, source_id=None):
        self.comandos.append(comando)
        return True


db = None
panel = None
router = None


def montar():
    global db, panel, router
    if db:
        db.close()
    TMP.unlink(missing_ok=True)
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    panel = PanelModule(cfg, db)
    router = RouterFalso()
    panel.attach(router)


def cb(data, mid=42):
    return {"data": data, "from": {"id": YO},
            "message": {"message_id": mid, "chat": {"id": YO}}}


def escribir(texto):
    panel.handle_text(YO, YO, texto)


def ultimo():
    filas = db.query("SELECT text FROM outbox ORDER BY id")
    return (filas[-1]["text"] or "") if filas else ""


def comando():
    return router.comandos[-1] if router.comandos else ""


# =========================================================================
print("=== 1. el sufijo evita la pregunta ===")
ok(interpretar_hora("9:30 a") == (ESTADO_OK, 9, 30), "9:30 a -> 09:30")
ok(interpretar_hora("9 p") == (ESTADO_OK, 21, 0), "9 p -> 21:00")
ok(interpretar_hora("9:30a") == (ESTADO_OK, 9, 30), "pegado tambien: 9:30a")
ok(interpretar_hora("1:30 pm") == (ESTADO_OK, 13, 30), "la sigla completa sirve igual")
ok(interpretar_hora("11 AM") == (ESTADO_OK, 11, 0), "y en mayusculas")

print("\n=== 2. sin sufijo, de 1 a 12, se pregunta ===")
for texto, hh, mm in (("1:30", 1, 30), ("4", 4, 0), ("9:30", 9, 30),
                      ("12", 12, 0), ("12:30", 12, 30)):
    ok(interpretar_hora(texto) == (ESTADO_AMBIGUA, hh, mm),
       f"{texto} -> hay que preguntar")

print("\n=== 3. de 13 a 23 no hay nada que preguntar ===")
ok(interpretar_hora("21:30") == (ESTADO_OK, 21, 30), "21:30 pasa directo")
ok(interpretar_hora("13") == (ESTADO_OK, 13, 0), "13 tambien")
ok(interpretar_hora("23:59") == (ESTADO_OK, 23, 59), "y 23:59")

print("\n=== 4. las 00 ya no existen ===")
ok(interpretar_hora("0:30")[0] == ESTADO_SIN_CERO, "0:30 se rechaza")
ok(interpretar_hora("00:00")[0] == ESTADO_SIN_CERO, "00:00 tambien")
ok(interpretar_hora("12 a") == (ESTADO_OK, 0, 0), "la medianoche es 12 a")
ok(interpretar_hora("12 p") == (ESTADO_OK, 12, 0), "y el mediodia es 12 p")

print("\n=== 5. lo que no se entiende, no se inventa ===")
for texto in ("25:00", "9:70", "manana", "", "9:30 x", "13 a"):
    ok(interpretar_hora(texto)[0] == ESTADO_INVALIDA, f"{texto!r} -> invalida")

print("\n=== 6. la hora viaja en UN token, para no romper /cal ===")
#
# El token tiene que ser inequivoco para `/cal`. De 13 en adelante ya lo es
# y va tal cual, como se venia mandando siempre. Las de la mañana necesitan
# el sufijo, porque `09:30` a secas volveria a ser una pregunta.
ok(token_hora(9, 30) == "9:30a", "09:30 -> 9:30a")
ok(token_hora(21, 30) == "21:30", "21:30 se manda tal cual: ya es inequivoca")
ok(token_hora(0, 0) == "12:00a", "medianoche -> 12:00a")
ok(token_hora(12, 0) == "12:00p", "mediodia -> 12:00p")
ok(" " not in token_hora(9, 30), "sin espacios: /cal separa por espacios")
ok(interpretar_hora(token_hora(21, 30)) == (ESTADO_OK, 21, 30),
   "y lo que arma se vuelve a leer igual")

print("\n=== 7. el flujo del panel pregunta y arma el comando ===")
montar()
panel.handle_callback(cb("panel:cal:hoy"))
escribir("dentista")
ok("Hora" in ultimo() or "hora" in ultimo(), "pide la hora")
escribir("1:30")
ok(messages.PANEL_CAL_AMPM in ultimo(), "una hora ambigua dispara la pregunta")
ok(not router.comandos, "y todavia no agendo nada")
escribir("pm")
ok(comando() == "/cal dentista 13:30", "con pm arma la hora de la tarde")

print("\n=== 7b. la misma pregunta se responde con el boton ===")
montar()
panel.handle_callback(cb("panel:cal:hoy"))
escribir("dentista")
escribir("1:30")
panel.handle_callback(cb("panel:cal:am"))
ok(comando() == "/cal dentista 1:30a", "el boton AM hace lo mismo que escribir am")

print("\n=== 7c. con sufijo no pregunta nada ===")
montar()
panel.handle_callback(cb("panel:cal:hoy"))
escribir("dentista")
escribir("9:30 a")
ok(comando() == "/cal dentista 9:30a", "va derecho, sin preguntar")

print("\n=== 7d. mañana y otra fecha siguen funcionando ===")
montar()
panel.handle_callback(cb("panel:cal:manana"))
escribir("reunion")
escribir("4")
panel.handle_callback(cb("panel:cal:pm"))
ok(comando() == "/cal reunion next 16:00", "mañana conserva su 'next'")

montar()
panel.handle_callback(cb("panel:cal:otro"))
escribir("12/11")
escribir("barrer")
escribir("8 p")
ok(comando() == "/cal barrer 12/11 20:00", "otra fecha conserva la fecha")

print("\n=== 8. los errores explican, no solo rechazan ===")
montar()
panel.handle_callback(cb("panel:cal:hoy"))
escribir("algo")
escribir("0:30")
ok("12 a" in ultimo(), "las 00 explican como escribir la medianoche")
ok(not router.comandos, "y no agenda nada")
escribir("chirimoya")
ok(messages.PANEL_CAL_HORA_INVALIDA in ultimo(), "una hora ilegible se repregunta")
escribir("8 p")
ok(comando() == "/cal algo 20:00",
   "y despues de errar dos veces sigue funcionando")

print("\n=== 9. /cal escrito a mano acepta lo mismo ===")
from modules.calendar_commands import parse_calendar_request, CalendarCommandError
from datetime import datetime

ahora = datetime(2026, 8, 30, 10, 0)
pedido = parse_calendar_request("/cal dentista 9:30p", ahora)
ok(pedido.start_at.hour == 21 and pedido.start_at.minute == 30,
   "/cal dentista 9:30p agenda a las 21:30")
pedido = parse_calendar_request("/cal dentista 21:30", ahora)
ok(pedido.start_at.hour == 21, "y el formato viejo de 24h sigue valiendo")

for texto, esperado in (("/cal dentista 1:30", "AM o PM"),
                        ("/cal dentista 0:30", "12 a")):
    try:
        parse_calendar_request(texto, ahora)
        ok(False, f"{texto} deberia fallar")
    except CalendarCommandError as exc:
        ok(esperado in str(exc), f"{texto} explica que falta ({esperado})")

print("\n=== 9b. AVISAR A del Timer lee la hora igual que el Calendario ===")
#
# Un aviso temprano puede caer a la misma hora de la manana o de la noche:
# adivinar ahi es avisar doce horas corrido. Se pregunta igual que al agendar.
montar()
panel.handle_callback(cb("panel:tm:hora"))
ok(messages.PANEL_TIMER_PIDE_HORA in ultimo(), "pide la hora directo")
escribir("1 p")
ok(comando() == "/timer_a 13:00", f"1 p son las 13:00 ({comando()})")

montar()
panel.handle_callback(cb("panel:tm:hora"))
escribir("7:30 a")
ok(comando() == "/timer_a 07:30", f"7:30 a son las 07:30 ({comando()})")

montar()
panel.handle_callback(cb("panel:tm:hora"))
escribir("7")
ok(messages.PANEL_CAL_AMPM in ultimo(), "sin a/p pregunta AM o PM")
ok(not router.comandos, "y todavia no crea el aviso")
panel.handle_callback(cb("panel:cal:pm"))
ok(comando() == "/timer_a 19:00", f"con el boton PM son las 19:00 ({comando()})")

montar()
panel.handle_callback(cb("panel:tm:hora"))
escribir("9:15")
escribir("a")
ok(comando() == "/timer_a 09:15",
   f"escribir a hace lo mismo que el boton ({comando()})")

montar()
panel.handle_callback(cb("panel:tm:hora"))
escribir("21:40")
ok(comando() == "/timer_a 21:40", "de 13 a 23 no pregunta nada")

montar()
panel.handle_callback(cb("panel:tm:hora"))
escribir("12 a")
ok(comando() == "/timer_a 00:00", f"12 a es la medianoche ({comando()})")

montar()
panel.handle_callback(cb("panel:tm:hora"))
escribir("0:30")
ok(messages.PANEL_CAL_SIN_CERO in ultimo(), "las 00 se piden como 12 a")
escribir("hola")
ok(messages.PANEL_CAL_HORA_INVALIDA in ultimo(), "lo que no es hora no se inventa")
ok(not router.comandos, "y en ningun caso crea un aviso a ciegas")

montar()
panel.handle_callback(cb("panel:tm:hora:pedir"))
escribir("8 p")
ok(comando() == "/timer_a 20:00",
   "el boton viejo que quede en pantalla sigue andando")

print("\n=== 10. Lite NO cambio: a ella se le sigue hablando distinto ===")
import modules.lite as L

ok(hasattr(L, "PASO_FRANJA"), "Lite conserva su propio paso de franja")
ok("mañana o de la tarde" in messages.LITE_GUIA_FRANJA,
   "y le pregunta mañana/tarde, no AM/PM")

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
