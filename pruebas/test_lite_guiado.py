"""Mástil Lite: el borrador guiado por mensajes.

Se entra escribiendo «recordar» y se sale por la misma palabra. El sistema
pregunta de a una cosa por vez; ella nunca tiene que componer la línea entera.

Lo que más se cuida acá es la privacidad: el borrador guarda lo que escribió
ANTES de que exista la fila definitiva, así que tiene que estar cifrado igual
que el recordatorio. Si eso se rompe, se filtra justo lo que este módulo existe
para proteger.
"""

import os, sys, dataclasses
from pathlib import Path
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import messages
import modules.lite as L
from database import Database
from modules.lite import LiteModule

ASISTIDA = "555"
DUENO = "999"

# ---------------------------------------------------------------- reloj falso
#
# `ZoneInfo("America/Santiago")` no existe en Windows: Python no trae la base
# IANA. Se reemplaza por un offset fijo, que además saca el horario de verano
# del medio y deja la suite determinista.
ZONA = timezone(timedelta(hours=-4))
L.ZoneInfo = lambda nombre: ZONA

BASE = datetime(2026, 8, 28, 10, 0, tzinfo=ZONA)
RELOJ = {"t": BASE}


class Reloj(datetime):
    @classmethod
    def now(cls, tz=None):
        return RELOJ["t"].astimezone(tz) if tz else RELOJ["t"]


L.datetime = Reloj


def avanzar(**kw):
    RELOJ["t"] = RELOJ["t"] + timedelta(**kw)


# ------------------------------------------------------------------ andamiaje
TMP = Path(os.environ["TEMP"]) / "lite_guiado" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)

cfg = dataclasses.replace(
    cm.load(),
    owner_chat_id=DUENO,
    db_path=TMP,
    lite_users=(cm.LiteUser(ASISTIDA, "Asistida", "America/Santiago"),),
    lite_secret_path=TMP.parent / "lite_secret.key",
)

FALLAS = 0


def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c:
        FALLAS += 1


db = None


def limpiar():
    global db
    if db:
        db.close()
    TMP.unlink(missing_ok=True)
    RELOJ["t"] = BASE
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    return LiteModule(cfg, db)


def decir(lite, texto, chat=ASISTIDA):
    lite.handle_message(chat, texto)


def salida(chat=ASISTIDA):
    return [f["text"] or "" for f in
            db.query("SELECT chat_id, text FROM outbox ORDER BY id")
            if f["chat_id"] == chat]


def ultimo(chat=ASISTIDA):
    filas = salida(chat)
    return filas[-1] if filas else ""


def vaciar():
    with db.transaction():
        db.execute("DELETE FROM outbox")


def guardados():
    return db.query("SELECT * FROM lite_reminders ORDER BY id")


# ==========================================================================
print("=== 1. el flujo completo, una pregunta por vez ===")
lite = limpiar()

decir(lite, "recordar")
ok("¿Qué quieres que te recuerde?" in ultimo(), "pregunta primero qué")

decir(lite, "tomar el remedio del corazon")
ok("¿Qué día?" in ultimo(), "después pregunta el día")

decir(lite, "hoy")
ok("¿A qué hora?" in ultimo(), "después la hora")

decir(lite, "21:30")
ok("¿Está bien así?" in ultimo(), "y muestra el resumen para confirmar")
ok("tomar el remedio del corazon" in ultimo(), "el resumen repite lo que ella dijo")

decir(lite, "sí")
filas = guardados()
ok(len(filas) == 1, "queda un recordatorio guardado")
ok(filas[0]["display_time"] == "21:30", "a las 21:30")
ok(filas[0]["display_date"] == "hoy", "para hoy")
ok(lite.decrypt(filas[0]["activity_enc"]) == "tomar el remedio del corazon",
   "con el texto que ella escribió")
ok(filas[0]["status"] == "pending", "y en estado pendiente")

print("\n=== 2. termina ofreciendo la misma puerta por la que entró ===")
ok("Listo. Creé tu recordatorio" in ultimo(), "confirma que lo creó")
ok("escribe <b>recordar</b>" in ultimo(), "y cierra invitando a escribir recordar")

print("\n=== 3. al dueño se le avisa el hecho, NUNCA el contenido ===")
al_dueno = " ".join(salida(DUENO))
ok("creó exitosamente un recordatorio" in al_dueno, "al dueño le llega que creó uno")
ok("remedio" not in al_dueno.lower(), "y su texto no aparece por ningún lado")
ok("corazon" not in al_dueno.lower(), "tampoco a pedazos")

print("\n=== 4. el borrador guardado va CIFRADO ===")
lite = limpiar()
decir(lite, "recordar")
decir(lite, "comprar flores para la mesa")
crudo = db.get_state(f"lite_borrador:{ASISTIDA}")
ok(crudo is not None, "hay un borrador a medias guardado")
ok("flores" not in str(crudo), "y NO se lee en claro")
ok("presion" not in str(crudo), "ni una palabra suya")
ok(lite.decrypt(crudo).count("flores") == 1, "pero se descifra bien con la llave")

print("\n=== 4b. en reposo no queda en claro en el archivo de la base ===")
#
# La outbox sí lleva el texto en claro, y tiene que llevarlo: es lo que se le
# muestra a ella en pantalla. Lo que se prueba acá es que una vez despachados
# los mensajes no quede ninguna otra copia legible en el archivo.
decir(lite, "hoy")
decir(lite, "23:15")
decir(lite, "si")


def tablas_con(frase):
    """En qué tablas aparece la frase en claro."""
    halladas = set()
    for tabla in db.query("SELECT name FROM sqlite_master WHERE type='table'"):
        nombre = tabla["name"]
        for fila in db.query(f"SELECT * FROM {nombre}"):
            for valor in tuple(fila):
                if isinstance(valor, str) and frase in valor:
                    halladas.add(nombre)
    return halladas


ok(tablas_con("flores") == {"outbox"},
   "mientras está por enviarse, sólo vive en la outbox")

vaciar()
db.execute("VACUUM")
ok(tablas_con("flores") == set(), "despachada, no queda en ninguna tabla")
bytes_db = TMP.read_bytes()
ok(b"flores" not in bytes_db, "ni suelta en el archivo .db")
ok(b"presion" not in bytes_db, "ni siquiera parcialmente")

print("\n=== 5. una hora ambigua se pregunta, no se adivina ===")
lite = limpiar()
decir(lite, "recordar")
decir(lite, "ir al doctor")
decir(lite, "manana")
vaciar()
decir(lite, "9")
ok("mañana o de la tarde" in ultimo(), "un 9 pelado pregunta la franja")

decir(lite, "de la tarde")
ok("21:00" in ultimo(), "«de la tarde» lo lleva a las 21:00")
decir(lite, "si")
ok(guardados()[0]["display_time"] == "21:00", "y así queda guardado")

print("\n=== 5a. un 9:30 también pregunta: los dos puntos no lo desambiguan ===")
#
# Decisión deliberada. «9:30» puede ser la mañana o la noche, y un recordatorio a
# doce horas de distancia no es un detalle de formato. Se prefiere una pregunta
# de más antes que adivinar.
lite = limpiar()
decir(lite, "recordar")
decir(lite, "tomar el jarabe")
decir(lite, "manana")
vaciar()
decir(lite, "9:30")
ok("mañana o de la tarde" in ultimo(), "9:30 pregunta igual")
decir(lite, "de la manana")
ok("09:30" in ultimo(), "y responde bien a «de la mañana»")

print("\n=== 5b. una hora inequívoca no molesta con la pregunta ===")
lite = limpiar()
decir(lite, "recordar")
decir(lite, "regar las plantas")
decir(lite, "hoy")
vaciar()
decir(lite, "18:00")
ok("¿Está bien así?" in ultimo(), "las 18:00 pasan directo a confirmar")

print("\n=== 6. la hora que ya pasó lo dice, no falla en seco ===")
lite = limpiar()
avanzar(hours=9)              # el reloj falso queda a las 19:00
decir(lite, "recordar")
decir(lite, "almorzar")
decir(lite, "hoy")
vaciar()
decir(lite, "18:00")
ok("ya pasó" in ultimo(), "le dice que esa hora ya pasó")
ok("No pude guardar" not in ultimo(), "y NO le tira el error viejo y mudo")
ok(not guardados(), "no guardó nada todavía")

print("\n=== 6b. «mañana» corre el día sin empezar de nuevo ===")
vaciar()
decir(lite, "manana")
ok("¿A qué hora?" in ultimo(), "vuelve a pedir la hora, ya para mañana")
decir(lite, "18:00")
decir(lite, "si")
filas = guardados()
ok(len(filas) == 1 and filas[0]["display_date"] == "mañana", "queda para mañana")
ok(lite.decrypt(filas[0]["activity_enc"]) == "almorzar",
   "y conservó lo que ya había escrito")

print("\n=== 7. siempre hay salida ===")
lite = limpiar()
decir(lite, "recordar")
decir(lite, "una cosa")
vaciar()
decir(lite, "nada")
ok("no guardé nada" in ultimo(), "«nada» cancela")
ok("escribe <b>recordar</b>" in ultimo(), "y le recuerda la puerta de entrada")
ok(db.get_state(f"lite_borrador:{ASISTIDA}") is None, "el borrador se borró")
ok(not guardados(), "no quedó ningún recordatorio")

print("\n=== 7b. decir «no» en el resumen tampoco guarda ===")
lite = limpiar()
decir(lite, "recordar")
decir(lite, "otra cosa")
decir(lite, "hoy")
decir(lite, "22:00")
decir(lite, "no")
ok(not guardados(), "«no» descarta el borrador")
ok(db.get_state(f"lite_borrador:{ASISTIDA}") is None, "y no queda a medias")

print("\n=== 8. el borrador vence solo, en silencio ===")
lite = limpiar()
decir(lite, "recordar")
decir(lite, "algo que quedó a medias")
vaciar()
avanzar(minutes=16)
ok(lite._borrador_leer(ASISTIDA) is None, "a los 16 minutos ya no existe")
ok(not salida(), "y no le mandó ningún mensaje al vencer")
ok(not salida(DUENO), "tampoco al dueño")

print("\n=== 8b. antes de los 15 minutos sigue vivo ===")
lite = limpiar()
decir(lite, "recordar")
decir(lite, "algo")
avanzar(minutes=14)
ok(lite._borrador_leer(ASISTIDA) is not None, "a los 14 minutos sigue ahí")

print("\n=== 9. la sintaxis de una línea sigue funcionando igual ===")
lite = limpiar()
decir(lite, "recordar hoy 21:30 bañarme")
filas = guardados()
ok(len(filas) == 1, "la línea completa crea el recordatorio derecho")
ok(filas[0]["display_time"] == "21:30", "con su hora")
ok(lite.decrypt(filas[0]["activity_enc"]) == "bañarme", "y su texto")
ok(db.get_state(f"lite_borrador:{ASISTIDA}") is None, "sin abrir ningún borrador")
ok("escribe <b>recordar</b>" not in ultimo(), "y sin cambiarle el mensaje de siempre")

print("\n=== 9b. si la línea trae la tarea pero no la fecha, arranca más adelante ===")
lite = limpiar()
decir(lite, "recordar comprar pan")
ok("¿Qué día?" in ultimo(), "ya no vuelve a preguntar qué, si ella ya lo dijo")
decir(lite, "hoy")
decir(lite, "20:00")
ok("comprar pan" in ultimo(), "y lo lleva bien hasta el resumen")

print("\n=== 9c. una línea rota NO se toma como si fuera la tarea ===")
lite = limpiar()
decir(lite, "recordar hoy 25:00 tomar agua")
ok("¿Qué quieres que te recuerde?" in ultimo(),
   "«hoy 25:00 tomar agua» no queda de nombre del recordatorio")

print("\n=== 10. una alarma sonando le gana al borrador ===")
lite = limpiar()
decir(lite, "recordar hoy 21:30 bañarme")
with db.transaction():
    db.execute("UPDATE lite_reminders SET status='alerting', alert_code='1234', "
               "first_alert_utc=?, last_alert_utc=? WHERE id=1",
               (RELOJ["t"].isoformat(), RELOJ["t"].isoformat()))
decir(lite, "recordar")
decir(lite, "cualquier cosa")
vaciar()
decir(lite, "1234")
ok(guardados()[0]["status"] == "confirmed", "los 4 dígitos apagan la alarma")
ok("apagué este recordatorio" in ultimo(), "y se lo dice")
ok(db.get_state(f"lite_borrador:{ASISTIDA}") is not None,
   "el borrador queda intacto esperándola")

print("\n=== 11. la bienvenida y la ayuda ofrecen la puerta fácil ===")
lite = limpiar()
decir(lite, "hola")
ok("escribe <b>recordar</b>" in ultimo(), "la bienvenida ofrece «recordar»")
vaciar()
decir(lite, "asdfgh")
ok("recordar" in ultimo(), "la ayuda también")
ok("No pude guardar el recordatorio" not in ultimo(), "sin el error viejo")

print("\n=== 12. Lite reclama el texto suelto sólo si hay borrador ===")
lite = limpiar()
ok(not lite.matches(ASISTIDA, "a las nueve"), "sin borrador, un texto suelto no es suyo")
decir(lite, "recordar")
ok(lite.matches(ASISTIDA, "a las nueve"), "con borrador abierto, sí lo reclama")

print("\n=== 13. nada de esto toca a otra usuaria ===")
ok(not lite.handle_message("777", "recordar"), "un chat ajeno no entra a Lite")
ok(db.get_state("lite_borrador:777") is None, "ni deja borrador")

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
