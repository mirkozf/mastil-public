"""Comando /cal: crear eventos sin salir de Telegram.

El parser es intencionalmente pequeno y estricto. No adivina fechas: hoy,
`next` y DD/MM son las tres formas aceptadas. Un error no crea nada y explica
el formato esperado.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import messages


DEFAULT_DURATION_MINUTES = 30
TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")
DATE_PATTERN = re.compile(r"^\d{2}/\d{2}$")
DATE_LIKE_PATTERN = re.compile(r"^\d{1,2}[-/]\d{1,2}$")


class CalendarCommandError(ValueError):
    """Error de entrada que se puede explicar directamente en Telegram."""


@dataclass(frozen=True)
class CalendarRequest:
    title: str
    start_at: datetime
    end_at: datetime


def _parse_time(value: str) -> time:
    if not TIME_PATTERN.fullmatch(value):
        raise CalendarCommandError(messages.CALENDAR_ERROR_TIME)
    hour, minute = (int(part) for part in value.split(":"))
    if hour > 23 or minute > 59:
        raise CalendarCommandError(messages.CALENDAR_ERROR_TIME)
    return time(hour, minute)


def _parse_date(value: str, year: int) -> date:
    if not DATE_PATTERN.fullmatch(value):
        raise CalendarCommandError(messages.CALENDAR_ERROR_DATE_FORMAT)
    day, month = (int(part) for part in value.split("/"))
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise CalendarCommandError(messages.calendar_error_invalid_date(value, year)) from exc


def parse_calendar_request(raw_text: str, now: datetime) -> CalendarRequest:
    """Parsea /cal titulo [next|DD/MM] HH:MM en la zona local del puente."""
    parts = (raw_text or "").strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        raise CalendarCommandError(messages.CALENDAR_USAGE)

    tokens = parts[1].strip().split()
    if len(tokens) < 2:
        raise CalendarCommandError(messages.CALENDAR_ERROR_TIME)

    at_time = _parse_time(tokens.pop())
    event_day = now.date()

    if tokens and tokens[-1].lower() == "next":
        tokens.pop()
        event_day += timedelta(days=1)
    elif tokens and DATE_PATTERN.fullmatch(tokens[-1]):
        event_day = _parse_date(tokens.pop(), now.year)
    elif tokens and DATE_LIKE_PATTERN.fullmatch(tokens[-1]):
        raise CalendarCommandError(messages.CALENDAR_ERROR_DATE_FORMAT)

    title = " ".join(tokens).strip()
    if not title:
        raise CalendarCommandError(messages.CALENDAR_ERROR_TITLE)

    start_at = datetime.combine(event_day, at_time, tzinfo=now.tzinfo)
    return CalendarRequest(
        title=title,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=DEFAULT_DURATION_MINUTES),
    )


class CalendarCommandsModule:
    def __init__(self, config, db, bridge):
        self.config = config
        self.db = db
        self.bridge = bridge

    def handle_command(self, command: str, raw_text: str, source_id: object = None) -> bool:
        if command != "/cal":
            return False

        if not self.bridge.enabled:
            self._say(messages.CALENDAR_UNAVAILABLE)
            return True

        try:
            request = parse_calendar_request(raw_text, self.bridge.now())
        except CalendarCommandError as exc:
            self._say(str(exc))
            return True

        request_id = self._request_id(source_id, raw_text)
        existing = self.db.one(
            "SELECT status FROM calendar_command_requests WHERE request_id = ?",
            (request_id,),
        )
        if existing and existing["status"] == "created":
            self._say(messages.CALENDAR_ALREADY_CREATED)
            return True

        with self.db.transaction():
            self.db.execute(
                """
                INSERT INTO calendar_command_requests(request_id, status, requested_at)
                VALUES (?, 'pending', ?)
                ON CONFLICT(request_id) DO UPDATE SET status = 'pending', last_error = NULL
                """,
                (request_id, self.bridge.now().isoformat()),
            )

        try:
            result = self.bridge.create_event(
                title=request.title,
                start_at=request.start_at,
                end_at=request.end_at,
                request_id=request_id,
            )
            event_id = str(result["event"]["id"])
        except Exception as exc:
            print(f"[calendar] crear evento: {exc}", flush=True)
            with self.db.transaction():
                self.db.execute(
                    """
                    UPDATE calendar_command_requests
                    SET status = 'failed', last_error = ?
                    WHERE request_id = ?
                    """,
                    (str(exc)[:500], request_id),
                )
                self._say(messages.CALENDAR_CREATE_FAILED)
            return True

        # Que el puente conteste "ok" no prueba que el evento exista. Antes de
        # confirmar, lo releemos del calendario. Si no está donde debería, no
        # se confirma: un aviso de "creado" que no es cierto vale menos que
        # ninguno, porque después no revisás.
        dia = request.start_at.astimezone(self.bridge.tz).strftime("%Y-%m-%d")
        try:
            visto = self.bridge.find_event(event_id, dia)
        except Exception as exc:
            # Creado pero sin poder comprobarlo: ni éxito ni fallo. Se dice.
            print(f"[calendar] no pude verificar el evento: {exc}", flush=True)
            with self.db.transaction():
                self.db.execute(
                    """
                    UPDATE calendar_command_requests
                    SET status = 'created', calendar_event_id = ?, created_at = ?,
                        last_error = ?
                    WHERE request_id = ?
                    """,
                    (event_id, self.bridge.now().isoformat(),
                     f"sin verificar: {str(exc)[:400]}", request_id),
                )
                self.db.enqueue(self.config.owner_chat_id,
                                messages.CALENDAR_UNVERIFIED, parse_mode="HTML")
                self.db.audit("calendar", "create_unverified", event_id)
            return True

        if visto is None:
            with self.db.transaction():
                self.db.execute(
                    """
                    UPDATE calendar_command_requests
                    SET status = 'failed', last_error = ?
                    WHERE request_id = ?
                    """,
                    (f"no aparece en {dia} tras crearlo", request_id),
                )
                self.db.enqueue(self.config.owner_chat_id,
                                messages.CALENDAR_CREATE_FAILED, parse_mode="HTML")
                self.db.audit("calendar", "create_no_visible", event_id)
            return True

        with self.db.transaction():
            self.db.execute(
                """
                UPDATE calendar_command_requests
                SET status = 'created', calendar_event_id = ?, created_at = ?, last_error = NULL
                WHERE request_id = ?
                """,
                (event_id, self.bridge.now().isoformat(), request_id),
            )
            # El título sale de lo que quedó en el calendario, no de lo que se
            # pidió: si el puente lo cambió, el mensaje debe mostrar lo real.
            self.db.enqueue(
                self.config.owner_chat_id,
                messages.calendar_created(
                    visto.get("title") or request.title,
                    request.start_at, request.end_at,
                ),
                parse_mode="HTML",
            )
            self.db.audit("calendar", "create_event", event_id)
        return True

    def _request_id(self, source_id: object, raw_text: str) -> str:
        if source_id is not None:
            return f"calendar:{self.config.owner_chat_id}:{source_id}"
        digest = hashlib.sha256(
            f"{self.config.owner_chat_id}|{raw_text}|{self.bridge.now().isoformat()}".encode("utf-8")
        ).hexdigest()
        return f"calendar:fallback:{digest}"

    def _say(self, text: str) -> None:
        with self.db.transaction():
            self.db.enqueue(self.config.owner_chat_id, text, parse_mode="HTML")
