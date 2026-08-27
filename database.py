"""Acceso a SQLite: conexión, transacciones y la cola de salida.

Todo el estado de Mástil vive aquí. Antes estaba repartido en cinco archivos
JSON que se escribían por separado, así que un corte de luz en el momento justo
podía dejar el estado y el mensaje enviado en desacuerdo.

La regla que ordena este archivo: **el cambio de estado y el mensaje que lo
anuncia se escriben en la misma transacción**. `enqueue()` no envía nada, sólo
deja la fila en `outbox`. El envío real lo hace el runtime después del commit.
Si el proceso muere en el medio, o se guardaron las dos cosas o ninguna.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


class Database:
    def __init__(self, path: Path, schema_path: Path):
        self.path = Path(path)
        self.schema_path = Path(schema_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(
            str(self.path),
            timeout=30,
            isolation_level=None,          # controlamos las transacciones a mano
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self._depth = 0

    # ------------------------------------------------------------------ setup

    def migrate(self) -> None:
        """Aplica el esquema y migraciones aditivas compatibles."""
        sql = self.schema_path.read_text(encoding="utf-8")
        self.connection.executescript(sql)

        # `CREATE TABLE IF NOT EXISTS` no agrega columnas a bases ya creadas.
        # Las migraciones aditivas se aplican aquí para conservar sesiones y
        # permitir que un despliegue actualice una base existente sin pasos
        # manuales en producción.
        self._ensure_column(
            "pomodoro_session",
            "work_minutes",
            "INTEGER NOT NULL DEFAULT 20",
        )
        # Algunos flujos editan un mismo mensaje en vez de encadenar varios.
        self._ensure_column("outbox", "message_id", "INTEGER")
        # Aviso al cumplirse el intervalo, con su escalamiento.
        # Guardian escala en exigencia: guarda cuándo toca el próximo paso
        # (a una hora al azar, no fija) y el código que cierra el nivel 2.
        self._ensure_column("guardian_events", "next_at", "TEXT")
        self._ensure_column("guardian_events", "code_hash", "TEXT")
        # Cola de eventos que vencieron con el canal ocupado.
        self._ensure_column("guardian_events", "queue_seq", "INTEGER")
        self._ensure_column("guardian_events", "decision_at", "TEXT")
        self._ensure_column(
            "guardian_events", "decision_step", "INTEGER NOT NULL DEFAULT 0"
        )
        self._ensure_column("guardian_events", "decision_next_at", "TEXT")
        # Nivel 3 con techo temporal: cuándo empezó la intervención, cuántas
        # ráfagas van, y la tregua deliberada que se compra con un código largo.
        # Timer: tres modalidades sobre el mismo motor y la misma fila.
        self._ensure_column(
            "timer", "modo", "TEXT NOT NULL DEFAULT 'countdown'"
        )
        self._ensure_column(
            "timer", "interval_minutes", "INTEGER NOT NULL DEFAULT 0"
        )
        self._ensure_column("guardian_events", "intervencion_at", "TEXT")
        self._ensure_column(
            "guardian_events", "rafagas", "INTEGER NOT NULL DEFAULT 0"
        )
        self._ensure_column("guardian_events", "modo", "TEXT")
        self._ensure_column("guardian_events", "tregua_hasta", "TEXT")
        self._ensure_column("guardian_events", "tregua_code_hash", "TEXT")
        self._ensure_column("guardian_events", "tregua_code_hasta", "TEXT")
        # Vigía 2.0: objetivo, estrategia y bloque en curso. Lo que permite
        # retomar la tarea días después sin empezar de cero.
        self._ensure_column("vigia_session", "contexto", "TEXT")
        self._ensure_column("vigia_session", "estrategia", "TEXT")
        self._ensure_column("vigia_session", "bloque", "TEXT")
        self._ensure_column("vigia_session", "trabado", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("vigia_session", "ultima_foto", "TEXT")
        self._ensure_column("vigia_session", "declarados", "TEXT")
        # Qué vio el modelo la última vez, para poder marcarle lo nuevo.
        self._ensure_column("vigia_session", "contexto_analizado", "TEXT")
        self._ensure_column("interval_marks", "alerts_sent", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("interval_marks", "alert_ack", "INTEGER NOT NULL DEFAULT 0")

        # Filas únicas de los módulos con una sola sesión a la vez.
        for table in ("pomodoro_session", "timer", "vigia_session"):
            self.connection.execute(
                f"INSERT OR IGNORE INTO {table}(id) VALUES (1)"
            )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self.connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            self.connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def close(self) -> None:
        try:
            self.connection.close()
        except sqlite3.Error:
            pass

    # ----------------------------------------------------------- transacción

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Transacción reentrante.

        Anidar `with db.transaction()` no abre una segunda transacción: sólo la
        más externa hace commit. Así un módulo puede llamar a otro sin que cada
        uno confirme por su cuenta a medio camino.
        """
        if self._depth:
            self._depth += 1
            try:
                yield self.connection
            finally:
                self._depth -= 1
            return

        self._depth = 1
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")
        finally:
            self._depth = 0

    # ------------------------------------------------------------- consultas

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return self.connection.execute(sql, params).fetchall()

    def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return self.connection.execute(sql, params).fetchone()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, params)

    # --------------------------------------------------- estado clave/valor

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM system_state WHERE key = ?", (key,))
        if row is None or row["value"] is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    def set_state(self, key: str, value: Any) -> None:
        self.execute(
            """
            INSERT INTO system_state(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                           updated_at = excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), _now_iso()),
        )

    # ------------------------------------------------------------- outbox

    def enqueue(
        self,
        chat_id: str,
        text: str = "",
        *,
        buttons: Sequence[tuple[str, str]] | None = None,
        photo_path: str | None = None,
        parse_mode: str | None = None,
        send_after: datetime | None = None,
        delete_photo: bool = False,
        message_id: int | None = None,
    ) -> int:
        """Deja un mensaje listo para enviar. NO envía.

        Llamar siempre dentro de la misma transacción que el cambio de estado
        que este mensaje comunica.

        Con `message_id` no envía uno nuevo: reemplaza el contenido de ese
        mensaje. Es lo que permite que un flujo entero ocurra sobre una sola
        pantalla en vez de seis mensajes encadenados.
        """
        if photo_path:
            kind = "photo"
        elif message_id:
            kind = "edit"
        else:
            kind = "text"

        cursor = self.execute(
            """
            INSERT INTO outbox
                (chat_id, kind, text, buttons, message_id, photo_path,
                 parse_mode, delete_photo, send_after, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(chat_id),
                kind,
                text,
                json.dumps(list(buttons), ensure_ascii=False) if buttons else None,
                int(message_id) if message_id else None,
                photo_path,
                parse_mode,
                1 if delete_photo else 0,
                send_after.astimezone().isoformat() if send_after else None,
                _now_iso(),
            ),
        )
        return int(cursor.lastrowid)

    def pending_outbox(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.query(
            """
            SELECT * FROM outbox
            WHERE sent_at IS NULL
              AND (send_after IS NULL OR send_after <= ?)
              AND attempts < 5
            ORDER BY id ASC
            LIMIT ?
            """,
            (_now_iso(), limit),
        )

    def mark_outbox_sent(self, outbox_id: int) -> None:
        with self.transaction():
            self.execute(
                "UPDATE outbox SET sent_at = ? WHERE id = ?",
                (_now_iso(), outbox_id),
            )

    def mark_outbox_failed(self, outbox_id: int, error: str) -> None:
        with self.transaction():
            self.execute(
                """
                UPDATE outbox
                SET attempts = attempts + 1, last_error = ?
                WHERE id = ?
                """,
                (str(error)[:500], outbox_id),
            )

    def purge_outbox(self, keep_days: int = 3) -> None:
        self.execute(
            """
            DELETE FROM outbox
            WHERE sent_at IS NOT NULL
              AND sent_at < datetime('now', ?)
            """,
            (f"-{int(keep_days)} days",),
        )

    # ------------------------------------------------------------ auditoría

    def audit(self, module: str, action: str, detail: str = "") -> None:
        """Registro de qué pasó. Nunca contenido privado."""
        self.execute(
            "INSERT INTO audit_events(module, action, detail, created_at) VALUES (?, ?, ?, ?)",
            (module, action, detail[:300], _now_iso()),
        )


def open_database(config) -> Database:
    db = Database(config.db_path, config.schema_path)
    db.migrate()
    return db
