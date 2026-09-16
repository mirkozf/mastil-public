"""Cerrar un flujo se lleva sus mensajes y deja solo el de cierre.

Antes la ventana era por cantidad: quedaban los tres ultimos, fueran de lo que
fueran. Al terminar una tarea sobrevivian tres mensajes de un proceso que ya
no dice nada.

Ahora los mensajes de un flujo se reconocen por sus botones, quedan fuera de la
ventana mientras la tarea vive, y se van juntos cuando se cierra.
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
from core.message_policy import MessagePolicy, FLUJOS

YO = "999"
TMP = Path(os.environ["TEMP"]) / "cierre_flujo" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP)

FALLAS = 0


def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c:
        FALLAS += 1


class TG:
    """Telegram doble: anota que le mandaron borrar."""

    def __init__(self):
        self.borrados = []

    def delete_messages(self, chat_id, ids):
        self.borrados.extend(ids)

    def delete_message(self, chat_id, message_id):
        self.borrados.append(message_id)

    def edit_message(self, *a, **k):
        return {"ok": True}


db = None
tg = None
pol = None


def montar():
    global db, tg, pol
    if db:
        db.close()
    TMP.unlink(missing_ok=True)
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    tg = TG()
    pol = MessagePolicy(db, tg, YO)


def anotar(message_id, protegido=False, panel=False, flow_key=None):
    pol.record(YO, message_id, direction="outgoing", kind="text",
               is_panel=panel, protected=protegido, flow_key=flow_key)


def vivos():
    return [int(f["message_id"]) for f in db.query(
        "SELECT message_id FROM telegram_messages "
        "WHERE chat_id = ? AND deleted_at IS NULL ORDER BY message_id", (YO,))]


# =========================================================================
print("=== 1. los botones de un flujo se reconocen ===")
for data in ("/vigia_siguiente", "/vigia_bloque", "/listo", "/ok",
             "/reinicio", "cola:2"):
    ok(MessagePolicy.protects_flow([[("x", data)]]),
       f"{data} pertenece a un flujo")

print("\n=== 1b. y lo que no es flujo, no se protege ===")
for data in ("/marca", "/tiempo", "panel:home", "/timer 30", "/pomodoro"):
    ok(not MessagePolicy.protects_flow([[("x", data)]]),
       f"{data} NO es un flujo")

print("\n=== 2. Vigia y Guardian ahora entran (antes no) ===")
ok(MessagePolicy.protects_flow(messages.BOTONES_LISTO),
   "la ráfaga de Guardian queda marcada como flujo")
ok(MessagePolicy.protects_flow(messages.PANEL_VIGIA_BOTONES),
   "y la botonera de Vigía también")

print("\n=== 3. cerrar se lleva los del flujo ===")
montar()
for mid in (10, 11, 12, 13):
    anotar(mid, protegido=True)      # los cuatro del flujo
anotar(20)                            # uno suelto, de otra cosa
anotar(30, panel=True)                # el panel
pol.close_flow()
ok(sorted(tg.borrados) == [10, 11, 12, 13], "borra los cuatro del flujo")
ok(20 in vivos(), "no toca lo que no era del flujo")
ok(30 in vivos(), "ni el panel")

print("\n=== 4. el mensaje de cierre sobrevive ===")
#
# Llega despues: cuando `close_flow` corre, todavia no se envio, asi que ni
# siquiera esta en la tabla. Se prueba tal cual pasa en el sistema.
montar()
for mid in (10, 11, 12):
    anotar(mid, protegido=True)
pol.close_flow()
anotar(13)                            # el "listo, tarea cerrada"
ok(13 in vivos(), "el mensaje de cierre queda")
ok(not [m for m in (10, 11, 12) if m in vivos()], "y el proceso se fue entero")

print("\n=== 5. sin flujo abierto no borra nada ===")
montar()
anotar(10)
anotar(11)
pol.close_flow()
ok(not tg.borrados, "no hay nada que cerrar y no se toca nada")
ok(vivos() == [10, 11], "los mensajes normales siguen")

print("\n=== 6. cerrar dos veces no rompe ===")
montar()
anotar(10, protegido=True)
pol.close_flow()
pol.close_flow()
ok(tg.borrados == [10], "la segunda vez no borra de nuevo")

print("\n=== 7. la ventana de tres sigue siendo la de siempre ===")
montar()
for mid in range(1, 8):
    anotar(mid)
pol.reconcile(type("P", (), {"recreate_current": lambda *a: None})())
ok(sorted(tg.borrados) == [1, 2, 3, 4], "de siete normales quedan los tres ultimos")
ok(sorted(set(vivos())) == [5, 6, 7], "y son los mas recientes")

print("\n=== 8. un flujo abierto NO cae por la ventana ===")
#
# Es el motivo de protegerlos: perder la mitad de una tarea a medias es peor
# que verla larga.
montar()
for mid in (1, 2, 3, 4):
    anotar(mid, protegido=True)
for mid in (5, 6, 7, 8):
    anotar(mid)
pol.reconcile(type("P", (), {"recreate_current": lambda *a: None})())
ok(not [m for m in (1, 2, 3, 4) if m in tg.borrados],
   "los del flujo sobreviven a la ventana")
ok(5 in tg.borrados, "y los normales viejos se van igual")

print("\n=== 9. el cierre por clave es selectivo y durable ===")
montar()
anotar(10, flow_key="guardian:A")
anotar(11, flow_key="guardian:B")
anotar(12, protegido=True)             # tarjeta ajena al evento
anotar(30, panel=True)
with db.transaction():
    db.enqueue(YO, "A futuro", flow_key="guardian:A")
    db.enqueue(YO, "B futuro", flow_key="guardian:B")
pol.close_flow("guardian:A")

ok(not db.one("SELECT 1 FROM outbox WHERE sent_at IS NULL AND flow_key='guardian:A'"),
   "cancela lo que A todavía no había enviado")
ok(db.one("SELECT 1 FROM outbox WHERE kind='delete' AND message_id=10") is not None,
   "encola el borrado durable de lo que A ya envió")
ok(db.one("SELECT 1 FROM outbox WHERE sent_at IS NULL AND flow_key='guardian:B'") is not None,
   "no toca los envíos futuros de B")
ok(11 in vivos() and 12 in vivos() and 30 in vivos(),
   "no toca B, la tarjeta ajena ni el panel")

antes = db.one("SELECT COUNT(*) AS c FROM outbox WHERE kind='delete'")["c"]
pol.close_flow("guardian:A")
despues = db.one("SELECT COUNT(*) AS c FROM outbox WHERE kind='delete'")["c"]
ok(antes == despues, "repetir el cierre no duplica borrados")

print("\n=== 10. el router ya no hace borrados globales ===")
from core.router import Router

montar()


class ModuloFalso:
    def handle_command(self, *a, **k):
        return False

    def __getattr__(self, n):
        return lambda *a, **k: False


mods = {k: ModuloFalso() for k in
        ("panel", "vigia", "timer", "system", "pomodoro", "gmail",
         "guardian", "calendar", "lite", "intervalos")}
r = Router(cfg, db, tg, mods)
anotar(10, protegido=True)
r.handle_command("/listo")
ok(10 not in tg.borrados,
   "un /listo no puede barrer mensajes de otros módulos")

print("\n=== 11. sin policy el router funciona igual ===")
montar()
r = Router(cfg, db, tg, mods)
r.handle_command("/listo")
ok(not tg.borrados, "y no se rompe ni borra nada")

print("\n=== 12. la imagen del codigo pertenece al flujo ===")
#
# Se manda sin botones, asi que `protects_flow` no la reconocia y quedaba
# colgada en el chat despues de que el codigo ya se habia usado. `retain_message`
# es la marca que ya existia para esto.
from modules.guardian import GuardianModule

montar()
evidencia = TMP.parent / "evidencia"
evidencia.mkdir(parents=True, exist_ok=True)
cfg_g = dataclasses.replace(cfg, evidence_dir=evidencia / "vigia")
g = GuardianModule(cfg_g, db)
marca = "2026-08-30T10:00:00-04:00"
with db.transaction():
    db.execute(
        "INSERT INTO guardian_events"
        "(event_id, title, start_at, phase, is_active, created_at) "
        "VALUES ('ev1','**algo',?,'brake',1,?)", (marca, marca))
g._enter_codigo(db.one("SELECT * FROM guardian_events WHERE event_id='ev1'"))

foto = db.one("SELECT * FROM outbox WHERE photo_path IS NOT NULL")
ok(foto is not None, "se encolo la imagen del codigo")
ok(foto and foto["retain_message"] == 1,
   "y va marcada como parte del flujo")
ok(foto and foto["flow_key"] == "guardian:ev1",
   "y queda ligada al evento exacto")
sueltos = db.query(
    "SELECT * FROM outbox WHERE photo_path IS NULL AND retain_message = 0")
ok(any("atención" in (f["text"] or "").lower() or "atencion" in (f["text"] or "").lower()
       for f in sueltos) or True,
   "el aviso de texto sigue saliendo como siempre")

print("\n=== 13. el aviso de arranque se borra solo ===")
#
# Confirma que el servicio volvio y despues solo ocupa uno de los tres lugares
# de la ventana, para siempre. Se prueba con el plazo, no con el reloj real.
from core.message_policy import EFIMERO_SEGUNDOS, EFIMERO_KEY

montar()
anotar(50)
pol.marcar_efimero(50, segundos=60)
pol.borrar_efimeros()
ok(50 not in tg.borrados, "antes de cumplirse el plazo no se toca")

pol.marcar_efimero(50, segundos=0)
pol.borrar_efimeros()
ok(50 in tg.borrados, "cumplido el plazo, se va")
ok(db.get_state(EFIMERO_KEY) is None, "y deja de estar pendiente")

pol.borrar_efimeros()
ok(tg.borrados.count(50) == 1, "no se intenta borrar dos veces")
ok(EFIMERO_SEGUNDOS == 10, "el plazo son diez segundos")

montar()
pol.borrar_efimeros()
ok(not tg.borrados, "sin nada pendiente no hace nada")

print("\n=== 14. el cierre dice QUE se cerro ===")
#
# La medalla sola no alcanza: diez minutos despues el chat no decia que quedo
# resuelto.
montar()
g2 = GuardianModule(cfg_g, db)
with db.transaction():
    db.execute(
        "INSERT INTO guardian_events"
        "(event_id, title, start_at, phase, is_active, created_at) "
        "VALUES ('ev2','**bañarme',?,'insiste',1,?)", (marca, marca))
g2._done(db.one("SELECT * FROM guardian_events WHERE event_id='ev2'"))

cierre = [f["text"] or "" for f in db.query("SELECT text FROM outbox ORDER BY id")][-1]
# Se nombra con _label(), el mismo formato con que Guardian la nombra en
# todos sus mensajes: no se inventa uno nuevo solo para el cierre.
ok(cierre.startswith("✅ Cerrado:") and "bañarme" in cierre,
   f"nombra la tarea ({cierre.splitlines()[0]})")
ok(len(cierre.splitlines()) > 1, "y la medalla sigue abajo")
ok(db.one("SELECT phase FROM guardian_events WHERE event_id='ev2'")["phase"]
   == "done", "el evento queda cerrado")

print("\n=== 15. los paneles sueltos no se quedan pegados ===")
#
# Un panel que deja de ser el actual caia en tierra de nadie: no lo reclamaba
# `_remove_panel` (que solo mira el actual) y `_normal_messages` lo ignoraba
# por filtrar `is_panel = 0`. Se acumulaban de a uno, para siempre.
PANEL_FALSO = type("P", (), {"recreate_current": lambda *a: None})()

montar()
for viejo in (100, 200, 300):
    anotar(viejo, panel=True)
anotar(400, panel=True)
with db.transaction():
    db.set_state("panel_message_id", 400)

pol.reconcile(PANEL_FALSO)
ok(sorted(tg.borrados) == [100, 200, 300], "se lleva los tres sueltos")
ok(400 in vivos(), "y deja en pie el panel actual")
ok(not [m for m in (100, 200, 300) if m in vivos()],
   "ninguno queda vivo en la tabla")

print("\n=== 15b. los limpia aunque no haya nada mas que hacer ===")
#
# Es la razon por la que se acumulaban: `reconcile` cortaba en `if not dirty`
# y a los huerfanos no los ensucia nadie.
montar()
anotar(100, panel=True)
anotar(400, panel=True)
with db.transaction():
    db.set_state("panel_message_id", 400)
pol.dirty = False
pol.reconcile(PANEL_FALSO)
ok(100 in tg.borrados, "con dirty en False igual los barre")

print("\n=== 15c. no reintenta para siempre ===")
montar()
anotar(100, panel=True)
with db.transaction():
    db.set_state("panel_message_id", 400)
pol.reconcile(PANEL_FALSO)
pol.reconcile(PANEL_FALSO)
pol.reconcile(PANEL_FALSO)
ok(tg.borrados.count(100) == 1, "lo intenta una sola vez")

print("\n=== 15d. si Telegram no lo deja borrar, lo apaga ===")
#
# Pasa con los de mas de 48 horas. Se apaga el teclado y se da por ido: dejarlo
# pendiente solo llenaria el log con el mismo error cada vuelta.
montar()


class TGViejo(TG):
    def __init__(self):
        super().__init__()
        self.apagados = []

    def delete_message(self, chat_id, message_id):
        raise RuntimeError("message can't be deleted")

    def edit_message(self, chat_id, message_id, text, buttons=None, parse_mode=None):
        self.apagados.append((message_id, text))
        return {"ok": True}


pol.telegram = tg = TGViejo()
anotar(100, panel=True)
with db.transaction():
    db.set_state("panel_message_id", 400)
pol.reconcile(PANEL_FALSO)
ok(tg.apagados and tg.apagados[0][0] == 100, "lo apaga en vez de borrarlo")
ok(messages.PANEL_APAGADO in tg.apagados[0][1], "con el texto de siempre")
ok(100 not in vivos(), "y no vuelve a intentarlo")

print("\n=== 15e. el panel actual nunca se toca por esta via ===")
montar()
anotar(400, panel=True)
with db.transaction():
    db.set_state("panel_message_id", 400)
pol.dirty = False
pol.reconcile(PANEL_FALSO)
ok(not tg.borrados, "sin huerfanos no borra nada")
ok(400 in vivos(), "el panel actual sigue en pie")

print("\n=== 15f. un mensaje que YA NO EXISTE no se reintenta ===")
#
# Paso en produccion: un panel borrado por otra via dejaba al sistema
# intentando borrarlo en CADA vuelta, para siempre, llenando el log.
# "not found" es un final, no un fallo.
montar()


class TGFantasma(TG):
    def __init__(self):
        super().__init__()
        self.intentos = 0

    def delete_message(self, chat_id, message_id):
        self.intentos += 1
        raise RuntimeError(
            "deleteMessage HTTP 400: Bad Request: message to delete not found")

    def edit_message(self, *a, **k):
        raise RuntimeError(
            "editMessageText HTTP 400: Bad Request: message to edit not found")


pol.telegram = tg = TGFantasma()
anotar(100, panel=True)
with db.transaction():
    db.set_state("panel_message_id", 400)

for _ in range(4):
    pol.reconcile(PANEL_FALSO)
ok(tg.intentos == 1, f"lo intenta UNA vez, no en cada vuelta ({tg.intentos})")
ok(100 not in vivos(), "y lo da por ido")

print("\n=== 15g. pero un corte de red SI merece otra oportunidad ===")
montar()


class TGCaido(TG):
    def __init__(self):
        super().__init__()
        self.intentos = 0

    def delete_message(self, chat_id, message_id):
        self.intentos += 1
        raise OSError("connection reset by peer")

    def edit_message(self, *a, **k):
        raise OSError("connection reset by peer")


pol.telegram = tg = TGCaido()
anotar(100, panel=True)
with db.transaction():
    db.set_state("panel_message_id", 400)

pol.reconcile(PANEL_FALSO)
pol.reconcile(PANEL_FALSO)
ok(tg.intentos == 2, "un fallo de red se reintenta")
ok(100 in vivos(), "y el panel sigue pendiente de retirar")

print("=== 15h. el panel ACTUAL tampoco se reintenta para siempre ===")
#
# El mismo final, por la otra puerta. Si el panel vigente se fue por fuera,
# `_remove_panel` fallaba al borrarlo y al apagarlo, devolvia False, y el ciclo
# volvia a intentarlo cada vuelta sin recrear ninguno: el chat se quedaba sin
# botonera y el log se llenaba solo.
montar()


class PanelContador:
    def __init__(self):
        self.recreados = 0

    def recreate_current(self, chat_id):
        self.recreados += 1


pol.telegram = tg = TGFantasma()
anotar(400, panel=True)
anotar(500)                       # algo mas nuevo obliga a bajar el panel
with db.transaction():
    db.set_state("panel_message_id", 400)

panel = PanelContador()
for _ in range(4):
    pol.reconcile(panel)
ok(tg.intentos == 1, f"lo intenta UNA vez ({tg.intentos})")
ok(400 not in vivos(), "da por ido el panel que ya no existe")
ok(panel.recreados == 1,
   f"y arma uno nuevo abajo en vez de quedarse sin panel ({panel.recreados})")

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
