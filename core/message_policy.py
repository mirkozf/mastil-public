"""Orden visual del chat principal de Mastil.

Telegram no ofrece una "ventana" de mensajes: para conservar solo los mas
recientes hay que recordar los ``message_id`` y borrar explicitamente los
anteriores. Este modulo guarda unicamente esos identificadores; nunca texto.

La politica se aplica solo al propietario:

    tres mensajes normales recientes + un unico panel al final

Lite queda fuera a proposito. Sus recordatorios pertenecen a otra persona y
no deben cambiar por una preferencia visual del propietario.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import messages


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


# Botones que pertenecen a un flujo en curso.
#
# Sus mensajes quedan fuera de la ventana de tres mientras la tarea vive
# —perder la mitad de un flujo a medias es peor que verlo largo— y se van
# todos juntos cuando el flujo se cierra.
FLUJOS = ("cola:", "/vigia", "/listo", "/ok", "/reinicio")

# Un mensaje que se borra solo. El aviso de arranque sirve los primeros
# segundos —confirma que el servicio volvio— y despues solo ocupa uno de
# los tres lugares de la ventana, para siempre.
EFIMERO_KEY = "mensaje_efimero"
EFIMERO_SEGUNDOS = 10


def _ya_no_esta(exc: Exception) -> bool:
    """Telegram dice que el mensaje no existe.

    Es un final, no un fallo: reintentarlo no lo va a resucitar. Sin esta
    distincion, un mensaje que se fue por otra via deja al sistema
    intentando borrarlo en cada vuelta del ciclo, para siempre.
    """
    return "not found" in str(exc).lower()


class MessagePolicy:
    KEEP_RECENT = 3
    DELETE_BATCH = 100

    def __init__(self, db, telegram, owner_chat_id: str):
        self.db = db
        self.telegram = telegram
        self.owner_chat_id = str(owner_chat_id)
        self.dirty = False
        self._sending_panel = False

    def bind(self, telegram) -> None:
        """Conecta la politica al cliente real, incluidos envios directos."""
        self.telegram = telegram
        setter = getattr(telegram, "set_message_observer", None)
        if setter:
            setter(self.observe_outgoing)

    @contextmanager
    def panel_send(self) -> Iterator[None]:
        previous = self._sending_panel
        self._sending_panel = True
        try:
            yield
        finally:
            self._sending_panel = previous

    @staticmethod
    def _message_id(response: dict[str, Any] | None) -> int | None:
        value = ((response or {}).get("result") or {}).get("message_id")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def observe_outgoing(
        self,
        chat_id: object,
        response: dict[str, Any] | None,
        kind: str = "text",
    ) -> None:
        self.record(
            chat_id,
            self._message_id(response),
            direction="outgoing",
            kind=kind,
            is_panel=self._sending_panel,
            protected=False,
            flow_key=None,
        )

    def record_incoming(self, chat_id: object, message_id: object) -> None:
        self.record(
            chat_id, message_id, direction="incoming", kind="message",
            is_panel=False, protected=False,
            flow_key=None,
        )

    def record(
        self,
        chat_id: object,
        message_id: object,
        *,
        direction: str,
        kind: str,
        is_panel: bool,
        protected: bool = False,
        flow_key: str | None = None,
    ) -> None:
        if str(chat_id) != self.owner_chat_id:
            return
        try:
            message_id = int(message_id)
        except (TypeError, ValueError):
            return

        with self.db.transaction():
            self.db.execute(
                """
                INSERT INTO telegram_messages
                    (chat_id, message_id, direction, kind, is_panel,
                     protected, flow_key, seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    direction = excluded.direction,
                    kind = excluded.kind,
                    is_panel = MAX(telegram_messages.is_panel,
                                   excluded.is_panel),
                    protected = MAX(telegram_messages.protected,
                                    excluded.protected),
                    flow_key = COALESCE(excluded.flow_key,
                                        telegram_messages.flow_key),
                    seen_at = excluded.seen_at,
                    deleted_at = NULL
                """,
                (
                    self.owner_chat_id, message_id, direction, kind,
                    1 if is_panel else 0,
                    1 if protected or flow_key else 0,
                    str(flow_key) if flow_key else None,
                    _now_iso(),
                ),
            )
        if not is_panel:
            self.dirty = True

    def _normal_messages(self) -> list[int]:
        return [
            int(row["message_id"])
            for row in self.db.query(
                """
                SELECT message_id
                FROM telegram_messages
                WHERE chat_id = ? AND is_panel = 0 AND protected = 0
                  AND deleted_at IS NULL
                ORDER BY message_id DESC
                """,
                (self.owner_chat_id,),
            )
        ]

    def _latest_visible_message(self) -> int:
        row = self.db.one(
            """
            SELECT MAX(message_id) AS message_id
            FROM telegram_messages
            WHERE chat_id = ? AND is_panel = 0 AND deleted_at IS NULL
            """,
            (self.owner_chat_id,),
        )
        return int(row["message_id"] or 0) if row else 0

    @staticmethod
    def protects_flow(buttons: Any) -> bool:
        """Un flujo largo necesita conservar el mensaje que va editando por etapas."""
        stack = list(buttons or [])
        while stack:
            item = stack.pop()
            if isinstance(item, (list, tuple)):
                if (
                    len(item) == 2
                    and isinstance(item[1], str)
                    and item[1].startswith(FLUJOS)
                ):
                    return True
                stack.extend(item)
        return False

    def set_protected(
        self, chat_id: object, message_id: object, protected: bool
    ) -> None:
        if str(chat_id) != self.owner_chat_id:
            return
        try:
            message_id = int(message_id)
        except (TypeError, ValueError):
            return
        with self.db.transaction():
            self.db.execute(
                """
                UPDATE telegram_messages
                SET protected = ?, seen_at = ?
                WHERE chat_id = ? AND message_id = ?
                """,
                (
                    1 if protected else 0, _now_iso(),
                    self.owner_chat_id, message_id,
                ),
            )
        if not protected:
            self.dirty = True

    def _mark_deleted(self, message_ids: list[int]) -> None:
        if not message_ids:
            return
        placeholders = ",".join("?" for _ in message_ids)
        with self.db.transaction():
            self.db.execute(
                f"""
                UPDATE telegram_messages
                SET deleted_at = ?
                WHERE chat_id = ? AND message_id IN ({placeholders})
                """,
                (_now_iso(), self.owner_chat_id, *message_ids),
            )

    def record_deleted(self, chat_id: object, message_id: object) -> None:
        """Actualiza el ledger tras un borrado enviado por la outbox."""
        if str(chat_id) != self.owner_chat_id:
            return
        try:
            message_id = int(message_id)
        except (TypeError, ValueError):
            return
        self._mark_deleted([message_id])
        self.dirty = True

    def _borrar(self, message_ids: list[int]) -> bool:
        """Borra los mensajes indicados, por tandas."""
        ok = True
        for start in range(0, len(message_ids), self.DELETE_BATCH):
            batch = message_ids[start:start + self.DELETE_BATCH]
            try:
                self.telegram.delete_messages(self.owner_chat_id, batch)
            except Exception as exc:
                ok = False
                print(f"[mensajes] no pude limpiar {batch}: {exc}", flush=True)
                continue
            self._mark_deleted(batch)
        return ok

    def _delete_old_normals(self, message_ids: list[int]) -> bool:
        return self._borrar(message_ids[self.KEEP_RECENT:])

    def close_flow(self, flow_key: str | None = None) -> None:
        """Un flujo que se cierra se lleva sus mensajes.

        Con ``flow_key`` se retira sólo una sesión concreta. Primero se
        cancelan sus envíos futuros y después se encolan los borrados de los
        mensajes que Telegram ya aceptó. La tarjeta de pendientes y el panel
        no llevan esa clave, así que nunca caen con el evento activo.

        Sin clave se conserva el comportamiento anterior para flujos legacy
        que sólo alcanzaban a marcar sus mensajes como protegidos.
        """
        if flow_key:
            with self.db.transaction():
                self.db.execute(
                    "DELETE FROM outbox WHERE sent_at IS NULL AND flow_key = ?",
                    (str(flow_key),),
                )
                ids = [
                    int(row["message_id"])
                    for row in self.db.query(
                        """
                        SELECT tm.message_id
                        FROM telegram_messages AS tm
                        WHERE tm.chat_id = ? AND tm.flow_key = ?
                          AND tm.is_panel = 0 AND tm.deleted_at IS NULL
                          AND NOT EXISTS (
                              SELECT 1 FROM outbox AS pending
                              WHERE pending.kind = 'delete'
                                AND pending.message_id = tm.message_id
                                AND pending.sent_at IS NULL
                          )
                        ORDER BY tm.message_id
                        """,
                        (self.owner_chat_id, str(flow_key)),
                    )
                ]
                for message_id in ids:
                    self.db.enqueue_delete(self.owner_chat_id, message_id)
            if ids:
                self.dirty = True
            return

        ids = [
            int(row["message_id"])
            for row in self.db.query(
                """
                SELECT message_id FROM telegram_messages
                WHERE chat_id = ? AND is_panel = 0 AND protected = 1
                  AND deleted_at IS NULL
                ORDER BY message_id
                """,
                (self.owner_chat_id,),
            )
        ]
        if not ids:
            return
        self._borrar(ids)
        self.dirty = True

    def cleanup_legacy_orphans(self) -> None:
        """Retira restos protegidos creados antes de existir ``flow_key``.

        Sólo actúa cuando no hay Guardian ni Vigía activos. La tarjeta
        de la cola se preserva por su id conocido. Así una actualización no
        corta un flujo antiguo a medias, pero cuando ese flujo termina tampoco
        deja sus mensajes protegidos para siempre.
        """
        guardian = self.db.one(
            "SELECT 1 FROM guardian_events WHERE is_active = 1 AND phase != 'done'"
        )
        vigia = self.db.one("SELECT 1 FROM vigia_session WHERE id = 1 AND active = 1")
        if guardian or vigia:
            return

        queue_id = self.db.get_state("guardian_queue_message_id")
        try:
            queue_id = int(queue_id) if queue_id is not None else None
        except (TypeError, ValueError):
            queue_id = None

        rows = self.db.query(
            """
            SELECT tm.message_id
            FROM telegram_messages AS tm
            WHERE tm.chat_id = ? AND tm.is_panel = 0
              AND tm.protected = 1 AND tm.flow_key IS NULL
              AND tm.deleted_at IS NULL
              AND (? IS NULL OR tm.message_id != ?)
              AND NOT EXISTS (
                  SELECT 1 FROM outbox AS pending
                  WHERE pending.kind = 'delete'
                    AND pending.chat_id = tm.chat_id
                    AND pending.message_id = tm.message_id
                    AND pending.sent_at IS NULL
              )
            """,
            (self.owner_chat_id, queue_id, queue_id),
        )
        if not rows:
            return
        with self.db.transaction():
            for row in rows:
                self.db.enqueue_delete(self.owner_chat_id, int(row["message_id"]))
        self.dirty = True

    def marcar_efimero(self, message_id, segundos: int = EFIMERO_SEGUNDOS) -> None:
        """Programa el borrado de un mensaje dentro de N segundos."""
        try:
            message_id = int(message_id)
        except (TypeError, ValueError):
            return
        cuando = datetime.now(timezone.utc) + timedelta(seconds=segundos)
        with self.db.transaction():
            self.db.set_state(EFIMERO_KEY, {
                "message_id": message_id,
                "borrar_a": cuando.isoformat(),
            })

    def borrar_efimeros(self) -> None:
        """Se llama en cada vuelta: barre el efimero cuando cumple su hora."""
        dato = self.db.get_state(EFIMERO_KEY)
        if not isinstance(dato, dict):
            return
        try:
            cuando = datetime.fromisoformat(dato["borrar_a"])
        except (KeyError, TypeError, ValueError):
            cuando = None
        if cuando and datetime.now(timezone.utc) < cuando:
            return

        message_id = dato.get("message_id")
        with self.db.transaction():
            self.db.set_state(EFIMERO_KEY, None)
        if message_id:
            self._borrar([int(message_id)])
            self.dirty = True

    def _paneles_huerfanos(self) -> list[int]:
        """Paneles vivos que ya no son el panel actual.

        Un panel que se apaga sin llegar a borrarse cae en tierra de
        nadie: no es el actual, asi que nadie lo reclama, y no es normal
        —`_normal_messages` filtra `is_panel = 0`—, asi que la ventana de
        tres tampoco lo mira. Se acumulaban de a uno, para siempre.
        """
        actual = self.db.get_state("panel_message_id")
        try:
            actual = int(actual) if actual is not None else None
        except (TypeError, ValueError):
            actual = None
        return [
            int(row["message_id"])
            for row in self.db.query(
                """
                SELECT message_id FROM telegram_messages
                WHERE chat_id = ? AND is_panel = 1 AND deleted_at IS NULL
                ORDER BY message_id
                """,
                (self.owner_chat_id,),
            )
            if actual is None or int(row["message_id"]) != actual
        ]

    def _retirar_huerfanos(self) -> None:
        """Se lleva los paneles sueltos. Se llama en cada vuelta.

        No depende de `dirty`: nada los ensucia, y por eso podian quedarse
        meses. Si Telegram no deja borrarlo (mas de 48 horas) se apaga, y
        se da por ido igual para no reintentarlo en cada vuelta.
        """
        for message_id in self._paneles_huerfanos():
            try:
                self.telegram.delete_message(self.owner_chat_id, message_id)
            except Exception as exc:
                if _ya_no_esta(exc):
                    # Se fue por otra via. No hay nada que borrar ni que
                    # apagar: se anota y no se vuelve a mirar.
                    self._mark_deleted([message_id])
                    continue
                print(f"[mensajes] panel huerfano {message_id} no borrable; "
                      f"lo apago: {exc}", flush=True)
                try:
                    self.telegram.edit_message(
                        self.owner_chat_id, message_id,
                        messages.PANEL_APAGADO, []
                    )
                except Exception as edit_exc:
                    print(f"[mensajes] tampoco pude apagarlo: {edit_exc}",
                          flush=True)
                    if not _ya_no_esta(edit_exc):
                        # Un corte de red si merece otra oportunidad.
                        continue
            self._mark_deleted([message_id])

    def _remove_panel(self, message_id: int) -> bool:
        try:
            self.telegram.delete_message(self.owner_chat_id, message_id)
        except Exception as exc:
            # Si el mensaje ya no existe no hay nada que borrar ni que apagar:
            # se da por ido, y el panel nuevo se arma abajo. Sin esto el ciclo
            # lo reintentaba en cada vuelta y el chat quedaba sin botonera.
            if not _ya_no_esta(exc):
                # Telegram tampoco deja borrar los de mas de 48 horas. Ahi se
                # apaga el teclado para no dejar dos paneles operativos.
                print(f"[mensajes] panel no borrable; lo apago: {exc}",
                      flush=True)
                try:
                    self.telegram.edit_message(
                        self.owner_chat_id, message_id,
                        messages.PANEL_APAGADO, []
                    )
                except Exception as edit_exc:
                    print(f"[mensajes] tampoco pude apagarlo: {edit_exc}",
                          flush=True)
                    if not _ya_no_esta(edit_exc):
                        # Un corte de red si merece otra oportunidad.
                        return False
        self._mark_deleted([message_id])
        with self.db.transaction():
            self.db.set_state("panel_message_id", None)
        return True

    def reconcile(self, panel) -> bool:
        """Limpia el historial y deja el panel debajo de los tres recientes.

        Devuelve True si encolo un panel nuevo y el runtime debe vaciar esa
        fila inmediatamente.
        """
        # Va antes del corte por `dirty`: a los paneles sueltos no los
        # ensucia nadie, y esperar a que algo mas pasara era justamente
        # lo que los dejaba colgados.
        self._retirar_huerfanos()

        if not self.dirty:
            return False

        normals = self._normal_messages()
        all_deleted = self._delete_old_normals(normals)
        # Una pantalla protegida creada despues del panel tambien exige que
        # este se recree abajo. Asi la cola queda antes de los tres recientes
        # y no entre el panel y el ultimo aviso.
        latest = self._latest_visible_message()

        current = self.db.get_state("panel_message_id")
        try:
            current = int(current) if current is not None else None
        except (TypeError, ValueError):
            current = None

        needs_panel = current is None or current <= latest
        if current is not None and current <= latest:
            if not self._remove_panel(current):
                # Conserva el unico panel activo. Duplicarlo durante un corte
                # de red seria peor que dejarlo temporalmente mas arriba.
                self.dirty = True
                return False

        self.dirty = not all_deleted
        if not needs_panel:
            return False

        panel.recreate_current(self.owner_chat_id)
        return True

    def purge(self, keep_days: int = 7) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        with self.db.transaction():
            self.db.execute(
                "DELETE FROM telegram_messages WHERE deleted_at < ?", (cutoff,)
            )
