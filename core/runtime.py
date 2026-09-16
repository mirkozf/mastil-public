"""Compone el sistema y corre el ciclo.

El ciclo es deliberadamente aburrido:

    leer updates -> enrutar -> tick de cada módulo -> vaciar la outbox

Los módulos nunca llaman a Telegram. Escriben su estado y su mensaje en la
misma transacción, y el envío ocurre acá, después del commit. Esa es toda la
garantía: si el proceso muere, o se guardaron las dos cosas o ninguna.
"""

from __future__ import annotations

import json
import time
from contextlib import nullcontext
from pathlib import Path

from core.message_policy import MessagePolicy, EFIMERO_SEGUNDOS
from core.router import Router
from core.scheduler import now_local
from integrations.calendar import CalendarBridge, CalendarPrivacy, read_events
from integrations.gmail import GmailBridge
from integrations.telegram import Telegram
from integrations.vision import Vision
from modules.calendar_commands import CalendarCommandsModule
from modules.guardian import GuardianModule
from modules.intervalos import IntervalosModule
from modules.gmail import GmailModule
from modules.lite import LiteModule
from modules.panel import (PanelModule, PANEL_MESSAGE_KEY,
                           PANEL_OUTBOX_KEY)
from modules.pomodoro import PomodoroModule
from modules.system import SystemModule
from modules.timer import TimerModule
from modules.vigia import VigiaModule

import messages

OFFSET_KEY = "telegram_offset"
SUSPENDED_KEY = "suspended"
# Suspensión exclusiva de Guardian. Vive en `system_state` como la global,
# para no inventar un segundo mecanismo de suspensión.
GUARDIAN_SUSPENDED_KEY = "guardian_suspended"
# Fila de la outbox que, al enviarse, se marca para borrarse sola.
EFIMERO_OUTBOX_KEY = "efimero_outbox_id"

# Sólo para no girar en vacío si Telegram falla. El ritmo real del ciclo lo
# marca el long polling de getUpdates.
PAUSA_MINIMA = 0.5


def _buttons(raw: str | None):
    """Devuelve el teclado tal como se guardó: una fila o varias.

    JSON no distingue tupla de lista, así que hay que reconstruir la forma
    para que el cliente de Telegram sepa si es una fila o un conjunto de filas.
    """
    if not raw:
        return None
    datos = json.loads(raw)
    if not datos:
        return None
    if isinstance(datos[0], list) and datos[0] and isinstance(datos[0][0], list):
        return [[tuple(b) for b in fila] for fila in datos]
    return [tuple(b) for b in datos]


class Runtime:
    def __init__(self, config, db):
        self.config = config
        self.db = db

        self.telegram = Telegram(config.telegram_bot_token)
        self.message_policy = MessagePolicy(
            db, self.telegram, config.owner_chat_id
        )
        self.message_policy.bind(self.telegram)
        # 90s y no los 45 por defecto: este Vision es el de Vigía, y su
        # llamada manda una foto con un prompt largo y espera JSON. Con 45
        # los timeouts eran frecuentes; Gmail usa el suyo, más corto.
        self.vision = Vision(config.gemini_api_key, config.gemini_model,
                             timeout=90)
        self.calendar_bridge = CalendarBridge(
            config.calendar_webapp_url,
            config.calendar_token,
            config.calendar_id,
            config.timezone,
        )
        self.privacy = CalendarPrivacy(db, self.calendar_bridge)
        self.gmail_bridge = GmailBridge(config.gmail_webapp_url, config.gmail_token)

        self.modules = {
            "system": SystemModule(config, db, self.privacy, self.telegram),
            "calendar": CalendarCommandsModule(config, db, self.calendar_bridge),
            "timer": TimerModule(config, db),
            "guardian": GuardianModule(config, db, self.message_policy),
            "pomodoro": PomodoroModule(config, db),
            "lite": LiteModule(config, db),
            "vigia": VigiaModule(
                config, db, self.telegram, self.vision, self.privacy,
                self.message_policy,
            ),
            "gmail": GmailModule(config, db, self.gmail_bridge, self.telegram),
            "intervalos": IntervalosModule(config, db),
            "panel": PanelModule(config, db),
        }
        # /estado necesita mirar a los otros dos sin acoplarse a ellos.
        self.modules["system"].attach(
            guardian=self.modules["guardian"],
            pomodoro=self.modules["pomodoro"],
        )

        self.router = Router(config, db, self.telegram, self.modules)
        # El Panel entrega los comandos que arma a la misma puerta que usa
        # todo el mundo. Se conecta acá porque el router nace después.
        self.modules["panel"].attach(self.router)

    # ------------------------------------------------------------ arranque

    def boot(self) -> None:
        # Red de seguridad: si el proceso murió con el calendario ofuscado, los
        # originales quedaron en el ledger. Reponerlos antes que nada.
        if self.privacy.needs_recovery():
            print("Calendar privacy: recuperando calendario tras corte", flush=True)
            try:
                self.privacy.restore_last("boot", deep=True)
            except Exception as exc:
                print(f"Calendar privacy: fallo al reponer: {exc}", flush=True)

        # Descartar lo que llegó mientras estábamos caídos.
        if self.db.get_state(OFFSET_KEY) is None:
            with self.db.transaction():
                self.db.set_state(OFFSET_KEY, 0)

        try:
            drained = self.telegram.drain_updates()
            if drained:
                with self.db.transaction():
                    self.db.set_state(OFFSET_KEY, drained)
        except Exception as exc:
            print(f"No pude sincronizar el offset inicial: {exc}", flush=True)

        with self.db.transaction():
            fila = self.db.enqueue(self.config.owner_chat_id,
                                   messages.ARRANQUE)
            # Confirma que el servicio volvio y se va solo: es un dato de
            # los primeros segundos, no del resto del dia.
            self.db.set_state(EFIMERO_OUTBOX_KEY, fila)
            self.db.audit("runtime", "boot")

    # --------------------------------------------------------------- ciclo

    def read_updates(self) -> None:
        offset = int(self.db.get_state(OFFSET_KEY, 0) or 0)

        # Long polling: Telegram deja la petición colgada y responde en el
        # instante en que llega un mensaje. Antes se preguntaba con timeout=1
        # y se dormía 5 segundos, así que un mensaje podía esperar hasta 6
        # segundos sólo para ser leído.
        updates = self.telegram.get_updates(
            offset, timeout=max(1, int(self.config.poll_seconds))
        )

        for update in updates:
            # El offset se confirma aunque el módulo falle: un mensaje
            # defectuoso no puede bloquear todos los que vienen detrás.
            with self.db.transaction():
                self.db.set_state(OFFSET_KEY, int(update["update_id"]) + 1)
            try:
                self.router.process(update)
            except Exception as exc:
                print(
                    f"[router] update_id={update.get('update_id')} error: {exc}",
                    flush=True,
                )
            finally:
                message = update.get("message") or {}
                chat_id = str((message.get("chat") or {}).get("id", ""))
                if self.config.is_owner(chat_id):
                    self.message_policy.record_incoming(
                        chat_id, message.get("message_id")
                    )

    def tick(self) -> None:
        events = []
        try:
            events = read_events(
                self.config.ical_url,
                self.config.prefix,
                self.config.activity_prefix,
            )
        except Exception as exc:
            print(f"Calendar: no pude leer el ICS: {exc}", flush=True)

        self.modules["vigia"].tick(events)
        # Guardian se puede apagar solo, sin apagar el resto. Saltar su tick
        # corta ráfagas, baja frecuencia y nuevas intervenciones de una vez.
        # Sus eventos NO se tocan: siguen en su tabla, con su fase y su hora.
        if not self.db.get_state(GUARDIAN_SUSPENDED_KEY, False):
            self.modules["guardian"].tick(events)
        self.modules["pomodoro"].tick()
        self.modules["timer"].tick()
        self.modules["lite"].tick()
        self.modules["intervalos"].tick()
        # Auditoría: deja por escrito qué decía la configuración cada día.
        self.modules["system"].tick()

    def flush_outbox(self) -> None:
        # Las pruebas y un eventual failover pueden reemplazar el adaptador
        # despues del arranque. La politica siempre debe borrar por la misma
        # puerta que acaba de enviar.
        if self.message_policy.telegram is not self.telegram:
            self.message_policy.bind(self.telegram)
        self.message_policy.cleanup_legacy_orphans()
        self._flush_pending_outbox()
        try:
            panel_created = self.message_policy.reconcile(
                self.modules["panel"]
            )
        except Exception as exc:
            print(f"[mensajes] no pude ordenar el chat: {exc}", flush=True)
            return
        if panel_created:
            # La recreacion encola una sola pantalla. Se envia ahora para que
            # el ciclo nunca termine con el panel todavia pendiente.
            self._flush_pending_outbox()

    def _flush_pending_outbox(self) -> None:
        for row in self.db.pending_outbox():
            try:
                is_panel = self.db.get_state(PANEL_OUTBOX_KEY) == row["id"]
                context = (
                    self.message_policy.panel_send()
                    if is_panel else nullcontext()
                )
                enviado = None
                if row["kind"] == "photo" and row["photo_path"]:
                    with context:
                        enviado = self.telegram.send_photo(
                            row["chat_id"], row["photo_path"],
                            row["text"] or "", row["parse_mode"],
                        )
                    if row["delete_photo"]:
                        try:
                            Path(row["photo_path"]).unlink(missing_ok=True)
                        except OSError:
                            pass
                elif row["kind"] == "delete" and row["message_id"]:
                    self.telegram.delete_message(row["chat_id"], row["message_id"])
                    self.message_policy.record_deleted(
                        row["chat_id"], row["message_id"]
                    )
                elif row["kind"] == "edit" and row["message_id"]:
                    buttons = _buttons(row["buttons"])
                    self.telegram.edit_message(
                        row["chat_id"], row["message_id"], row["text"] or "",
                        buttons, row["parse_mode"],
                    )
                    self.message_policy.set_protected(
                        row["chat_id"], row["message_id"],
                        bool(row["retain_message"])
                        or self.message_policy.protects_flow(buttons),
                    )
                else:
                    buttons = _buttons(row["buttons"])
                    with context:
                        # El panel se recrea abajo cada vez que algo lo deja
                        # arriba, asi que cada aviso traia DOS notificaciones:
                        # la del aviso y la del tablero cambiando de lugar. El
                        # panel no da noticias, solo botones: llega callado.
                        enviado = self.telegram.send_message(
                            row["chat_id"], row["text"] or "",
                            buttons, row["parse_mode"],
                            disable_notification=is_panel,
                        )
                    self._anotar_panel(row["id"], enviado)
                    self._anotar_efimero(row["id"], enviado)
                    self.modules["guardian"].adopt_queue_anchor_message_id(
                        row["id"], enviado
                    )

                # Los dobles de Telegram de las pruebas no tienen observer.
                # El UPSERT hace que registrar tambien el cliente real sea
                # inocuo y mantiene esta garantia comprobable sin red.
                if enviado is not None:
                    self.message_policy.record(
                        row["chat_id"],
                        self.message_policy._message_id(enviado),
                        direction="outgoing",
                        kind=row["kind"],
                        is_panel=is_panel,
                        protected=self.message_policy.protects_flow(
                            _buttons(row["buttons"])
                        ) or bool(row["retain_message"])
                        or bool(row["flow_key"]),
                        flow_key=row["flow_key"],
                    )
            except Exception as exc:
                # Editar un mensaje con el mismo contenido devuelve error. No
                # es un fallo: el mensaje ya dice lo que tiene que decir.
                if "not modified" in str(exc):
                    self.db.mark_outbox_sent(row["id"])
                    continue
                self.db.mark_outbox_failed(row["id"], str(exc))
                print(f"[outbox] id={row['id']} error: {exc}", flush=True)
            else:
                self.db.mark_outbox_sent(row["id"])

    def _anotar_efimero(self, outbox_id, respuesta) -> None:
        """Programa el borrado del mensaje que pidio irse solo."""
        if self.db.get_state(EFIMERO_OUTBOX_KEY) != outbox_id:
            return
        destino = ((respuesta or {}).get("result") or {}).get("message_id")
        with self.db.transaction():
            self.db.set_state(EFIMERO_OUTBOX_KEY, None)
        if destino:
            self.message_policy.marcar_efimero(destino, EFIMERO_SEGUNDOS)

    def _anotar_panel(self, outbox_id, respuesta) -> None:
        """Le dice al Panel en que mensaje aterrizo su pantalla.

        El `message_id` no existe hasta que Telegram acepta el envio, y el
        Panel lo necesita para poder apagar esa pantalla cuando se mueva al
        final de la conversacion. Solo se anota la fila que el Panel pidio
        seguir: cualquier otro mensaje no le interesa.
        """
        if self.db.get_state(PANEL_OUTBOX_KEY) != outbox_id:
            return
        destino = ((respuesta or {}).get("result") or {}).get("message_id")
        with self.db.transaction():
            self.db.set_state(PANEL_MESSAGE_KEY, destino)
            self.db.set_state(PANEL_OUTBOX_KEY, None)
        if destino is not None:
            self.modules["panel"].adopt_message_id(
                self.config.owner_chat_id, destino
            )

    def run_once(self) -> None:
        self.read_updates()

        # Responder ANTES del tick. El tick descarga el ICS de Google, y hacer
        # esperar la respuesta de un /tm a que Google conteste es sumarle a
        # cada comando una demora que no tiene nada que ver con él.
        self.flush_outbox()
        self.message_policy.borrar_efimeros()

        if not self.db.get_state(SUSPENDED_KEY, False):
            self.tick()

        # Segunda vuelta: lo que haya generado el tick (avisos, rescates).
        self.flush_outbox()

    def run_forever(self) -> None:
        self.boot()
        last_cleanup = now_local()

        while True:
            try:
                self.run_once()

                if (now_local() - last_cleanup).total_seconds() > 3600:
                    with self.db.transaction():
                        self.modules["guardian"].cleanup_old_events()
                        self.db.purge_outbox()
                        self.message_policy.purge()
                    last_cleanup = now_local()

            except KeyboardInterrupt:
                print("Mástil detenido a mano.", flush=True)
                return
            except Exception as exc:
                print(f"Error temporal: {exc}", flush=True)

            # El ritmo ahora lo marca el long polling, no esta pausa. Queda
            # una espera mínima como válvula: si getUpdates falla, evita que
            # el ciclo gire en vacío consumiendo CPU.
            time.sleep(PAUSA_MINIMA)

    def close(self) -> None:
        self.db.close()
