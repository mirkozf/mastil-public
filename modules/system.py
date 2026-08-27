"""Control global: /admin, /estado, /suspender, /reanudar y las pruebas.

`/suspender` detiene el procesamiento conductual sin apagar el servicio: el bot
sigue escuchando comandos, pero no vigila Calendar, ni corre Pomodoro, ni
insiste. Es la salida de emergencia cuando Mástil estorba en vez de ayudar.
"""

from __future__ import annotations

import messages
from core.scheduler import now_local

SUSPENDED_KEY = "suspended"


class SystemModule:
    def __init__(self, config, db, privacy, telegram=None):
        self.config = config
        self.db = db
        self.privacy = privacy
        # Sólo para /sorpresa: hay que saber si Telegram aceptó el envío antes
        # de confirmarlo, y la outbox envía después de que el handler terminó.
        self.telegram = telegram
        self.guardian = None
        self.pomodoro = None

    def attach(self, guardian, pomodoro) -> None:
        """/estado necesita mirar a los otros módulos sin acoplarse a ellos."""
        self.guardian = guardian
        self.pomodoro = pomodoro

    # ------------------------------------------------------------ calendar

    def restore_calendar(self, reason: str = "") -> None:
        if not self.privacy.enabled:
            return
        try:
            self.privacy.restore_last(reason)
        except Exception as exc:
            print(f"Calendar privacy restore error: {exc}", flush=True)

    # ------------------------------------------------------------ comandos

    def handle_command(self, command: str, raw_text: str) -> bool:
        if command == "/suspender":
            return self._suspend()
        if command == "/reanudar":
            return self._resume()
        if command == "/admin":
            self._say(messages.PANEL_ADMIN)
            return True
        if command == "/estado":
            return self._status()
        if command == "/reset_estado":
            return self._reset()
        if command == "/cancelar":
            return self._cancel()
        if command == "/sorpresa":
            return self._sorpresa(raw_text)
        if command == "/recordatorios_lite":
            return self._lite_count()
        if command.startswith("/test_"):
            return self._test(command)
        return False

    # ------------------------------------------------------------ internos

    def _say(self, text: str, buttons=None) -> None:
        with self.db.transaction():
            self.db.enqueue(self.config.owner_chat_id, text, buttons=buttons)

    def _suspend(self) -> bool:
        with self.db.transaction():
            self.db.set_state(SUSPENDED_KEY, True)
            if self.guardian:
                self.guardian.reset()
            if self.pomodoro:
                self.pomodoro.reset(announce=False)
            self.db.enqueue(self.config.owner_chat_id, messages.SUSPENDIDO)
            self.db.audit("system", "suspend")
        return True

    def _resume(self) -> bool:
        with self.db.transaction():
            self.db.set_state(SUSPENDED_KEY, False)
            self.db.enqueue(self.config.owner_chat_id, messages.REANUDADO)
            self.db.audit("system", "resume")
        return True

    def _status(self) -> bool:
        if self.db.get_state(SUSPENDED_KEY, False):
            self._say(messages.ESTADO_SUSPENDIDO)
            return True

        partes = []
        if self.guardian:
            partes.append(self.guardian.status_text())
        if self.pomodoro:
            partes.append(self.pomodoro.status_text())

        if self.privacy.enabled:
            pendientes = self.privacy.pending_count()
            if pendientes:
                partes.append(
                    f"Calendar: {pendientes} títulos ofuscados pendientes de reponer."
                )

        self._say("\n\n".join(p for p in partes if p))
        return True

    def _reset(self) -> bool:
        with self.db.transaction():
            if self.guardian:
                self.guardian.reset()
            if self.pomodoro:
                self.pomodoro.reset(announce=False)
            self.db.execute("UPDATE timer SET active = 0, status = 'idle' WHERE id = 1")
            self.db.set_state(SUSPENDED_KEY, False)
            self.db.enqueue(self.config.owner_chat_id, messages.ESTADO_RESETEADO)
            self.db.audit("system", "reset")
        return True

    def _cancel(self) -> bool:
        cancelado = self.guardian.cancel_active() if self.guardian else False
        self._say(messages.GUARDIAN_CANCELADO if cancelado else messages.GUARDIAN_SIN_FLUJO)
        return True

    def _destinataria(self):
        """A quién le llega la sorpresa.

        Reusa MASTIL_LITE_USERS, que es donde ya está su chat: no hace falta
        configurar nada nuevo ni escribir un chat_id en el código.

        En producción hay dos usuarias —ella y el propietario en modo espejo—
        y gana la que no es el propietario. En desarrollo sólo está él, así
        que la sorpresa le llega a sí mismo y el comando se puede probar sin
        involucrarla a ella.
        """
        propio = None
        for usuario in self.config.lite_users:
            if not self.config.is_owner(usuario.chat_id):
                return usuario
            propio = usuario
        return propio

    def _sorpresa(self, raw_text: str) -> bool:
        texto = raw_text.replace("/sorpresa", "", 1).strip()
        if not texto:
            self._say(messages.SORPRESA_USO)
            return True
        self.enviar_sorpresa(texto)
        return True

    def enviar_sorpresa(self, texto: str, foto: str | None = None) -> bool:
        """Manda la sorpresa y dice cómo salió. True si Telegram la aceptó.

        Un solo camino de envío para las dos rutas —el comando `/sorpresa` y el
        flujo con botones—, así que la destinataria y el formato se deciden en
        un solo lugar. Con `foto`, va como **un** mensaje: el texto de pie
        pero mostrado por encima de la imagen.
        """
        destino = self._destinataria()
        if not destino:
            self._say(messages.SORPRESA_SIN_DESTINO)
            return False

        # Directo, no por la outbox: confirmar sin saber si Telegram lo aceptó
        # sería inventar un acuse de recibo.
        try:
            if foto:
                respuesta = self.telegram.send_photo(
                    destino.chat_id, foto, messages.sorpresa(texto),
                    caption_arriba=True,
                )
            else:
                respuesta = self.telegram.send_message(
                    destino.chat_id, messages.sorpresa(texto)
                )
            if not (respuesta or {}).get("ok"):
                raise RuntimeError(f"Telegram respondió: {respuesta}")
        except Exception as exc:
            print(f"[sorpresa] no pude enviar: {exc}", flush=True)
            self._say(messages.SORPRESA_ERROR)
            return False

        self._say(messages.sorpresa_enviada(destino.name))
        self.db.audit("system", "sorpresa", "con foto" if foto else "")
        return True

    def _lite_count(self) -> bool:
        """Cuántos recordatorios activos tiene la usuaria asistida. Nunca cuáles."""
        try:
            row = self.db.one(
                """
                SELECT COUNT(*) AS c FROM lite_reminders
                WHERE status IN ('pending', 'alerting')
                """
            )
            self._say(f"Recordatorios activos de la usuaria asistida: {int(row['c'])}.")
        except Exception as exc:
            print(f"[lite] conteo de recordatorios: {exc}", flush=True)
            self._say("No pude consultar los recordatorios activos de la usuaria asistida.")
        return True

    def _test(self, command: str) -> bool:
        if command == "/test_cierre":
            import random
            self._say(random.choice(messages.MENSAJES_CIERRE))
            return True

        if not self.guardian:
            return False

        if command == "/test_freno":
            self._say("Test admin: Fase Freno activada.")
            self.guardian.admin_test("brake")
            return True
        if command == "/test_chequeo":
            self.guardian.admin_test("check")
            return True
        if command == "/test_rescate":
            self._say("Test admin: Rescate normal activado.")
            self.guardian.admin_test("rescue")
            return True
        if command == "/test_rescate30":
            self._say("Test admin: Rescate acelerado activado.")
            self.guardian.admin_test("rescue_fast")
            return True
        return False
