"""Pregunta asistida: dos opciones, una respuesta persistente y nada más."""

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ.update(
    MASTIL_TELEGRAM_BOT_TOKEN="0:t",
    MASTIL_OWNER_CHAT_ID="999",
    MASTIL_ICAL_URL="https://x.invalid/a.ics",
)

import config as cm
import messages
from config import LiteUser
from core.router import Router
from database import Database
from modules.panel import PanelModule

YO, ASISTIDA, AJENO = "999", "111", "555"
TMP = Path(os.environ["TEMP"]) / "pregunta_asistida.db"
FALLAS = 0


def ok(condicion, texto):
    global FALLAS
    print(f"  {'ok  ' if condicion else 'MAL '} {texto}")
    if not condicion:
        FALLAS += 1


class TelegramFalso:
    def __init__(self):
        self.enviados = []
        self.editados = []
        self.callbacks = []
        self.siguiente_id = 700
        self.falla_edicion = False
        self.falla_notificacion = False

    def answer_callback(self, callback_id, text="", show_alert=False):
        self.callbacks.append((callback_id, text, show_alert))

    def send_message(self, chat_id, text, buttons=None, parse_mode=None,
                     disable_notification=False):
        if self.falla_notificacion and str(chat_id) == YO and \
                "RESPUESTA ASISTIDA" in text:
            raise RuntimeError("fallo simulado de notificación")
        self.siguiente_id += 1
        item = {
            "chat": str(chat_id), "text": text, "buttons": buttons,
            "message_id": self.siguiente_id,
        }
        self.enviados.append(item)
        return {"ok": True, "result": {"message_id": self.siguiente_id}}

    def edit_message(self, chat_id, message_id, text, buttons=None,
                     parse_mode=None):
        if self.falla_edicion:
            raise RuntimeError("fallo simulado de edición")
        self.editados.append({
            "chat": str(chat_id), "message_id": int(message_id),
            "text": text, "buttons": buttons,
        })
        return {"ok": True, "result": {"message_id": int(message_id)}}


class ModuloFalso:
    enabled = False

    def __init__(self):
        self.comandos = []

    def abandon_contexto(self, *args, **kwargs):
        pass

    def handle_command(self, command, raw_text, source_id=None):
        self.comandos.append((command, raw_text))
        return False

    def handle(self, *args, **kwargs):
        return False

    def handle_message(self, *args, **kwargs):
        return False

    def handle_text(self, *args, **kwargs):
        return False

    def handle_photo(self, *args, **kwargs):
        return False

    def stop(self, *args, **kwargs):
        pass

    def restore_calendar(self, *args, **kwargs):
        pass

    def matches(self, *args, **kwargs):
        return False


class SistemaFalso(ModuloFalso):
    def __init__(self, destino):
        super().__init__()
        self.destino = destino
        self.sorpresas = []

    def _destinataria(self):
        return self.destino

    def handle_command(self, command, raw_text, source_id=None):
        self.comandos.append((command, raw_text))
        return command == "/recordatorios_lite"

    def enviar_sorpresa(self, texto, foto=None):
        self.sorpresas.append((texto, foto))
        return True


def montar(reusar_tg=None, borrar=True):
    if borrar:
        TMP.unlink(missing_ok=True)
    cfg = dataclasses.replace(
        cm.load(), owner_chat_id=YO, db_path=TMP,
        lite_users=(LiteUser(ASISTIDA, "Asistida", "America/Santiago"),),
    )
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    tg = reusar_tg or TelegramFalso()
    panel = PanelModule(cfg, db)
    system = SistemaFalso(cfg.lite_users[0])
    mods = {"panel": panel, "system": system}
    for nombre in ("vigia", "timer", "pomodoro", "gmail",
                   "guardian", "calendar", "lite", "intervalos"):
        mods[nombre] = ModuloFalso()
    router = Router(cfg, db, tg, mods)
    panel.attach(router)
    return cfg, db, tg, panel, router, system


def callback(data, chat=YO, user=None, message_id=77, callback_id="c"):
    return {"callback_query": {
        "id": callback_id,
        "data": data,
        "from": {"id": user if user is not None else chat},
        "message": {"message_id": message_id, "chat": {"id": chat}},
    }}


def mensaje(texto, chat=YO, message_id=80):
    return {"message": {
        "message_id": message_id, "chat": {"id": chat},
        "from": {"id": chat}, "text": texto,
    }}


def pendientes(db):
    filas = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL")
    return filas


def ultima(db):
    filas = pendientes(db)
    return filas[-1] if filas else None


def botones_outbox(fila):
    return json.loads(fila["buttons"]) if fila and fila["buttons"] else []


def callbacks_outbox(fila):
    return [boton[1] for grupo in botones_outbox(fila) for boton in grupo]


def abrir_y_completar(panel, router, db, pregunta="¿Te gustó la canción?",
                       opcion_a="❤️ Sí", opcion_b="😄 Otra"):
    router.process(callback("panel:sor:pregunta"))
    primera = ultima(db)
    router.process(mensaje(pregunta, message_id=81))
    segunda = ultima(db)
    router.process(mensaje(opcion_a, message_id=82))
    tercera = ultima(db)
    router.process(mensaje(opcion_b, message_id=83))
    preview = ultima(db)
    return primera, segunda, tercera, preview


print("=== creador: formulario, validación y preview ===")
cfg, db, tg, panel, router, system = montar()
router.process(callback("panel:sys:sorpresa"))
menu = ultima(db)
ok("panel:sor:pregunta" in callbacks_outbox(menu), "1. botón PREGUNTA ASISTIDA existe")

router.process(callback("panel:sor:pregunta"))
ok(messages.ASISTQ_PIDE_PREGUNTA in ultima(db)["text"], "2. pide pregunta")
ok(panel.handle_text(YO, YO, "", 84) is True and
   messages.ASISTQ_TEXTO_VACIO in ultima(db)["text"], "3. rechaza pregunta vacía")
router.process(mensaje("¿Te gustó la canción?", message_id=85))
ok(messages.ASISTQ_PIDE_OPCION_A in ultima(db)["text"], "4. pide opción A")
ok(panel.handle_text(YO, YO, "   ", 86) is True and
   messages.ASISTQ_TEXTO_VACIO in ultima(db)["text"], "5. rechaza A vacía")
router.process(mensaje("❤️ Sí", message_id=87))
ok(messages.ASISTQ_PIDE_OPCION_B in ultima(db)["text"], "6. pide opción B")
ok(panel.handle_text(YO, YO, "", 88) is True and
   messages.ASISTQ_TEXTO_VACIO in ultima(db)["text"], "7. rechaza B vacía")
router.process(mensaje("  ❤️   SÍ  ", message_id=89))
ok(messages.ASISTQ_OPCIONES_IGUALES in ultima(db)["text"],
   "8. rechaza opciones iguales normalizadas")
router.process(mensaje("😄 Otra", message_id=90))
preview = ultima(db)
ok("¿Te gustó la canción?" in preview["text"], "9. preview conserva pregunta")
respuesta_preview = [c for c in callbacks_outbox(preview)
                     if c.startswith("panel:asistq:preview:")]
ok(respuesta_preview == ["panel:asistq:preview:a", "panel:asistq:preview:b"],
   "10. preview contiene exactamente 2 botones de respuesta")
ok("❤️ Sí" in str(botones_outbox(preview)) and "😄 Otra" in str(botones_outbox(preview)),
   "23. preview conserva emojis")

print("\n=== cancelar y editar ===")
router.process(callback("panel:asistq:cancelar"))
ultima(db)
ok(not tg.enviados and not db.query("SELECT * FROM assisted_questions"),
   "11. cancelar no envía ni persiste")
_, _, _, preview = abrir_y_completar(panel, router, db)
router.process(callback("panel:asistq:editar"))
ok(messages.ASISTQ_PIDE_PREGUNTA in ultima(db)["text"], "12. editar reinicia el flujo")
panel.olvidar_todo()

print("\n=== envío y respuesta A ===")
_, _, _, preview = abrir_y_completar(panel, router, db)
router.process(callback("panel:asistq:enviar"))
ultima(db)
envio = tg.enviados[-1]
row = db.one("SELECT * FROM assisted_questions ORDER BY id DESC LIMIT 1")
ok(envio["chat"] == ASISTIDA, "13. envía al chat configurado de la usuaria asistida")
cb_envio = [b[1] for grupo in envio["buttons"] for b in grupo]
ok(all("Sí" not in data and "Otra" not in data for data in cb_envio),
   "14. callback_data no contiene respuestas")
ok(len(cb_envio) == 2, "20. la usuaria asistida recibe sólo dos botones")

router.process(callback(f"asistq:{row['id']}:a", chat=ASISTIDA,
                        message_id=envio["message_id"], callback_id="a1"))
guardada = db.one("SELECT * FROM assisted_questions WHERE id=?", (row["id"],))
ok(guardada["answered_option"] == "a", "15. opción A se resuelve")
ok(bool(guardada["answered_at"]), "17. respuesta queda persistida")
ok(tg.editados[-1]["buttons"] == [], "20. elimina los botones")
ok("❤️ Sí" in tg.editados[-1]["text"], "21. edita el mensaje con la respuesta")
notificaciones = [e for e in tg.enviados if e["chat"] == YO]
ok(len(notificaciones) == 1 and "¿Te gustó" in notificaciones[0]["text"] and
   "❤️ Sí" in notificaciones[0]["text"], "22. creador recibe pregunta y respuesta")

router.process(callback(f"asistq:{row['id']}:b", chat=ASISTIDA,
                        message_id=envio["message_id"], callback_id="a2"))
doble = db.one("SELECT * FROM assisted_questions WHERE id=?", (row["id"],))
ok(doble["answered_option"] == "a", "18. segundo toque no cambia respuesta")
ok(len([e for e in tg.enviados if e["chat"] == YO]) == 1,
   "19. segundo toque no notifica de nuevo")
ok(tg.callbacks[-1][1] == messages.ASISTQ_YA_RESPONDIDA,
   "18b. segundo toque recibe acuse amable")

print("\n=== respuesta B y reinicio simulado ===")
_, _, _, _ = abrir_y_completar(panel, router, db, "¿Qué prefieres?", "🎵 Música", "🍰 Torta")
router.process(callback("panel:asistq:enviar"))
ultima(db)
envio_b = tg.enviados[-1]
row_b = db.one("SELECT * FROM assisted_questions ORDER BY id DESC LIMIT 1")
db.close()
cfg, db, tg, panel, router, system = montar(reusar_tg=tg, borrar=False)
router.process(callback(f"asistq:{row_b['id']}:b", chat=ASISTIDA,
                        message_id=envio_b["message_id"], callback_id="b1"))
despues = db.one("SELECT * FROM assisted_questions WHERE id=?", (row_b["id"],))
ok(despues["answered_option"] == "b", "16. opción B se resuelve")
ok("🍰 Torta" in tg.editados[-1]["text"], "24. responde después de reiniciar")

print("\n=== autorización, fallos e independencia ===")
_, _, _, _ = abrir_y_completar(panel, router, db, "¿Uno?", "A", "B")
router.process(callback("panel:asistq:enviar")); ultima(db)
envio_c = tg.enviados[-1]
row_c = db.one("SELECT * FROM assisted_questions ORDER BY id DESC LIMIT 1")
router.process(callback(f"asistq:{row_c['id']}:a", chat=AJENO, user=AJENO,
                        message_id=envio_c["message_id"], callback_id="x"))
ok(db.one("SELECT answered_option FROM assisted_questions WHERE id=?",
          (row_c["id"],))["answered_option"] is None,
   "25. callback ajeno se rechaza")

tg.falla_edicion = True
router.process(callback(f"asistq:{row_c['id']}:a", chat=ASISTIDA,
                        message_id=envio_c["message_id"], callback_id="e"))
ok(db.one("SELECT answered_option FROM assisted_questions WHERE id=?",
          (row_c["id"],))["answered_option"] == "a",
   "26. fallo de edición no borra respuesta")
ok(any(e["chat"] == ASISTIDA and e["text"] == messages.ASISTQ_RESPUESTA_REGISTRADA
       for e in tg.enviados), "26b. edición fallida usa fallback breve")
tg.falla_edicion = False

_, _, _, _ = abrir_y_completar(panel, router, db, "¿Dos?", "A", "B")
router.process(callback("panel:asistq:enviar")); ultima(db)
envio_d = tg.enviados[-1]
row_d = db.one("SELECT * FROM assisted_questions ORDER BY id DESC LIMIT 1")
tg.falla_notificacion = True
router.process(callback(f"asistq:{row_d['id']}:b", chat=ASISTIDA,
                        message_id=envio_d["message_id"], callback_id="n"))
ok(db.one("SELECT answered_option FROM assisted_questions WHERE id=?",
          (row_d["id"],))["answered_option"] == "b",
   "27. fallo al notificar no revierte respuesta")
tg.falla_notificacion = False

router.process(callback("panel:sor:pregunta")); ultima(db)
router.process(mensaje("/recordatorios_lite", message_id=200))
ok(not panel._pendientes and not panel._preguntas_asistidas,
   "28. slash command cancela formulario")
ok(system.comandos[-1][0] == "/recordatorios_lite",
   "31. /recordatorios_lite conserva su ruta")

panel.handle_callback(callback("panel:sor:pregunta")["callback_query"])
panel.handle_text(YO, YO, "Pregunta uno", 201)
panel.handle_callback(callback("panel:sor:pregunta", chat="998",
                               user="998")["callback_query"])
panel.handle_text("998", "998", "Pregunta dos", 202)
ok(panel._pendientes[(YO, YO)]["datos"]["question"] == "Pregunta uno" and
   panel._pendientes[("998", "998")]["datos"]["question"] == "Pregunta dos",
   "29. formularios de usuarios/chats no se mezclan")
panel.olvidar_todo()

print("\n=== regresiones de alcance ===")
router.process(callback("panel:sys:sorpresa")); ultima(db)
router.process(callback("panel:sor:texto")); ultima(db)
router.process(mensaje("Sorpresa normal", message_id=210)); ultima(db)
router.process(callback("panel:sor:enviar")); ultima(db)
ok(system.sorpresas == [("Sorpresa normal", None)],
   "30. Sorpresa normal sigue por su camino anterior")
ok(not any("gemini" in evento["text"].lower() for evento in tg.enviados),
   "32. el flujo no llama ni menciona Gemini")

db.close()
TMP.unlink(missing_ok=True)
print("\n" + "=" * 58)
print("FALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
