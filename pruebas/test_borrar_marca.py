"""Boton BORRAR INTERVALO: saca la ultima marca, con confirmacion.

Existe porque un dedo se equivoca y una marca de mas desplaza todo el resto del
ciclo. No cierra nada ni reinicia nada: saca una fila y muestra como queda,
igual que despues de marcar.

Confirma antes, como el RESET del mismo panel.
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
from database import Database
from modules.intervalos import IntervalosModule, RESET_KEY
from modules.panel import PanelModule

YO = "999"
TMP = Path(os.environ["TEMP"]) / "borrar_marca" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP)

FALLAS = 0


def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c:
        FALLAS += 1


class RouterFalso:
    def __init__(self, inter):
        self.modules = {"intervalos": inter}
        self.comandos = []

    def handle_command(self, comando, source_id=None):
        self.comandos.append(comando)
        # El router real entrega estos comandos a Intervalos.
        self.modules["intervalos"].handle(comando, source_id)
        return True


db = None
inter = None
panel = None
router = None


def montar():
    global db, inter, panel, router
    if db:
        db.close()
    TMP.unlink(missing_ok=True)
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    inter = IntervalosModule(cfg, db)
    panel = PanelModule(cfg, db)
    router = RouterFalso(inter)
    panel.attach(router)


def marcar(minutos_atras):
    """Una marca a N minutos del presente.

    Relativa a ahora y no a una fecha fija: el ciclo se cierra solo a las 4
    horas de la ultima marca, asi que un bloque anclado en el pasado no seria
    el ciclo actual y no habria nada que borrar.
    """
    cuando = (datetime.now(timezone.utc)
              - timedelta(minutes=minutos_atras)).isoformat()
    with db.transaction():
        db.execute(
            "INSERT INTO interval_marks(user_id, marked_at_utc, local_day, "
            "request_id) VALUES (?,?,?,?)",
            (YO, cuando, "2026-08-30", f"req-{minutos_atras}"),
        )


def marcas():
    return db.query("SELECT * FROM interval_marks ORDER BY marked_at_utc")


def cb(data, mid=42):
    return {"data": data, "from": {"id": YO},
            "message": {"message_id": mid, "chat": {"id": YO}}}


def ultimo():
    filas = db.query("SELECT text FROM outbox ORDER BY id")
    return (filas[-1]["text"] or "") if filas else ""


def vaciar():
    with db.transaction():
        db.execute("DELETE FROM outbox")


# =========================================================================
print("=== 1. el boton esta en SISTEMA ===")
plano = str(messages.PANEL_SYSTEM_BOTONES)
ok("BORRAR INTERVALO" in plano, "aparece en la botonera de sistema")
ok("panel:sys:borrar" in plano, "y apunta a la confirmacion, no al borrado")

print("\n=== 2. la marca se nombra por numero y tramo ===")
montar()
# Seis marcas; entre las dos ultimas hay 58 minutos.
for minutos_atras in (349, 314, 216, 134, 58, 0):
    marcar(minutos_atras)
ok(len(marcas()) == 6, "hay seis marcas en el ciclo")
ok(inter.ultima_marca_resumen().startswith("6 ("),
   "la ultima es la numero 6")
ok("58m" in inter.ultima_marca_resumen(),
   f"y se la nombra por su tramo: {inter.ultima_marca_resumen()}")

print("\n=== 3. primero confirma, no borra ===")
vaciar()
panel.handle_callback(cb("panel:sys:borrar"))
ok("¿Borrar la marca" in ultimo(), "pregunta antes de tocar nada")
ok("6 (" in ultimo(), "y dice cual va a borrar")
ok(len(marcas()) == 6, "todavia estan las seis")
ok("panel:sys:borrar:ok" in str(messages.PANEL_BORRAR_MARCA_BOTONES),
   "ofrece el boton de confirmar")
ok("panel:system" in str(messages.PANEL_BORRAR_MARCA_BOTONES),
   "y uno para volver sin borrar")

print("\n=== 4. volver no borra ===")
panel.handle_callback(cb("panel:system"))
ok(len(marcas()) == 6, "salir de la confirmacion deja todo como estaba")

print("\n=== 5. confirmar borra SOLO la ultima ===")
vaciar()
ids_antes = [m["id"] for m in marcas()]
panel.handle_callback(cb("panel:sys:borrar:ok"))
ids_ahora = [m["id"] for m in marcas()]
ok(len(ids_ahora) == 5, "queda una marca menos")
ok(ids_ahora == ids_antes[:-1], "y la que se fue es la ultima, no otra")

print("\n=== 6. y muestra la tabla, como despues de marcar ===")
texto = ultimo()
ok("Borré la marca" in texto, "dice que la borro")
ok("6 (" in texto, "y cual era")
ok(messages.INTERVALOS_TITULO in texto, "abajo viene la tabla del ciclo")

print("\n=== 7. no cierra el ciclo ni reinicia nada ===")
ok(not db.get_state(RESET_KEY, ""), "no toco la marca de reset")
ok(len(marcas()) == 5, "las otras cinco siguen enteras")
ok(inter.ultima_marca_resumen().startswith("5 ("), "ahora la ultima es la 5")

print("\n=== 8. se puede borrar de nuevo ===")
vaciar()
panel.handle_callback(cb("panel:sys:borrar"))
ok("5 (" in ultimo(), "la confirmacion ya habla de la 5")
panel.handle_callback(cb("panel:sys:borrar:ok"))
ok(len(marcas()) == 4, "y la borra igual")

print("\n=== 9. sin marcas no se rompe ===")
montar()
vaciar()
panel.handle_callback(cb("panel:sys:borrar"))
ok(messages.PANEL_BORRAR_SIN_MARCAS in ultimo(), "avisa que no hay nada que borrar")
ok(not router.comandos, "y no ejecuta ningun borrado")

vaciar()
inter.handle("/borrar_marca", None)
ok(messages.INTERVALOS_BORRAR_SIN_MARCAS in ultimo(),
   "el comando suelto tampoco se rompe")

print("\n=== 10. con una sola marca la nombra por su inicio ===")
montar()
marcar(0)
ok(messages.INTERVALOS_INICIO in inter.ultima_marca_resumen(),
   "la primera marca no tiene tramo anterior")
inter.handle("/borrar_marca", None)
ok(not marcas(), "y se puede borrar igual")

print("\n=== 11. queda registrado en la auditoria ===")
montar()
marcar(58)
marcar(0)
borrada = marcas()[-1]["id"]
inter.handle("/borrar_marca", None)
filas = db.query("SELECT * FROM audit_events WHERE action = 'borrar_marca'")
ok(len(filas) == 1, "el borrado deja rastro en la auditoria")
ok(str(borrada) in (filas[0]["detail"] or ""), "con el id de la fila que se fue")

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
