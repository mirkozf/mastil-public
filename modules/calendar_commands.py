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

# Cuántas veces se relee el día para confirmar un evento. Google entrega la
# respuesta de Apps Script en un segundo paso que a veces contesta 404 aunque
# el script ya corrió; el siguiente intento suele entrar. Dos, no más: cada
# 404 puede tardar medio minuto y el ciclo de Mástil espera.
RELECTURAS = 2
TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")

# Reloj de 12 con sufijo opcional pegado o separado: `9`, `1:30`, `9:30 a`,
# `9p`. El sufijo es la unica forma de no tener que preguntar.
HORA_PATTERN = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm|a|p)?$", re.I)

ESTADO_OK = "ok"
ESTADO_AMBIGUA = "ambigua"
ESTADO_SIN_CERO = "sin_cero"
ESTADO_INVALIDA = "invalida"
DATE_PATTERN = re.compile(r"^\d{2}/\d{2}$")
DATE_LIKE_PATTERN = re.compile(r"^\d{1,2}[-/]\d{1,2}$")


class CalendarCommandError(ValueError):
    """Error de entrada que se puede explicar directamente en Telegram."""


@dataclass(frozen=True)
class CalendarRequest:
    title: str
    start_at: datetime
    end_at: datetime


def franja_de(texto: str) -> str | None:
    """`a`/`am` -> "a"; `p`/`pm` -> "p". Cualquier otra cosa, None."""
    limpio = (texto or "").strip().lower()
    if limpio in ("a", "am"):
        return "a"
    if limpio in ("p", "pm"):
        return "p"
    return None


def aplicar_franja(hora: int, minuto: int, franja: str):
    """Pasa una hora de reloj de 12 a 24. Las 12 a son las 00."""
    h = hora % 12
    return (h + 12 if franja == "p" else h), minuto


def token_hora(hora: int, minuto: int) -> str:
    """La hora en 12h con sufijo, en UN solo token: `9:30a`.

    Un token y no dos porque `/cal` separa por espacios y toma el ultimo
    como la hora: un sufijo suelto se leeria como parte del titulo.
    """
    # De 13 en adelante no hace falta sufijo: ya es inequivoca, y reescribirla
    # cambiaria por nada lo que se venia mandando.
    if hora >= 13:
        return f"{hora:02d}:{minuto:02d}"
    sufijo = "a" if hora < 12 else "p"
    return f"{hora % 12 or 12}:{minuto:02d}{sufijo}"


def interpretar_hora(value: str):
    """(estado, hora, minuto) en formato de 24 horas.

    Con `ambigua`, hora y minuto vuelven tal como se escribieron: falta
    saber la franja para poder convertirlos.

    El cero no se usa: la medianoche se escribe `12 a`. Tener dos formas de
    decir lo mismo es justo lo que obliga a pensar antes de escribir.
    """
    match = HORA_PATTERN.fullmatch((value or "").strip().lower())
    if not match:
        return ESTADO_INVALIDA, 0, 0

    hora = int(match.group(1))
    minuto = int(match.group(2) or 0)
    if minuto > 59:
        return ESTADO_INVALIDA, 0, 0

    sufijo = match.group(3)
    if sufijo:
        if not 1 <= hora <= 12:
            return ESTADO_INVALIDA, 0, 0
        hora, minuto = aplicar_franja(hora, minuto, franja_de(sufijo))
        return ESTADO_OK, hora, minuto

    if hora == 0:
        return ESTADO_SIN_CERO, 0, 0
    if hora > 23:
        return ESTADO_INVALIDA, 0, 0
    # De 13 a 23 no hay nada que preguntar: no pueden ser de la mañana.
    if hora >= 13:
        return ESTADO_OK, hora, minuto
    return ESTADO_AMBIGUA, hora, minuto


def _parse_time(value: str) -> time:
    estado, hora, minuto = interpretar_hora(value)
    if estado == ESTADO_OK:
        return time(hora, minuto)
    if estado == ESTADO_SIN_CERO:
        raise CalendarCommandError(messages.CALENDAR_ERROR_MEDIANOCHE)
    if estado == ESTADO_AMBIGUA:
        raise CalendarCommandError(messages.CALENDAR_ERROR_AMPM)
    raise CalendarCommandError(messages.CALENDAR_ERROR_TIME)


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

        dia = request.start_at.astimezone(self.bridge.tz).strftime("%Y-%m-%d")
        event_id = None
        try:
            result = self.bridge.create_event(
                title=request.title,
                start_at=request.start_at,
                end_at=request.end_at,
                request_id=request_id,
            )
            event_id = str(result["event"]["id"])
        except Exception as exc:
            # Un fallo acá no prueba que no se creó: Apps Script responde en un
            # segundo paso que Google a veces contesta 404 con el evento ya
            # hecho (12 de 13 "fallidos" de septiembre estaban en el
            # calendario). Se decide releyendo, igual que un éxito.
            print(f"[calendar] crear evento: {exc}", flush=True)

        # Que el puente conteste "ok" tampoco prueba que el evento exista. En
        # los dos casos la única prueba es verlo: por su id si llegó, y por la
        # marca de este pedido si se perdió. Un aviso de "creado" que no es
        # cierto vale menos que ninguno, porque después no revisás.
        visto, error = self._releer(dia, request_id, event_id)

        if visto is None and error is not None:
            # Ni releyendo se pudo mirar: no es éxito ni fallo. Se dice.
            if event_id:
                estado, detalle = "created", f"sin verificar: {str(error)[:400]}"
            else:
                estado, detalle = "failed", f"sin confirmar: {str(error)[:400]}"
            with self.db.transaction():
                self.db.execute(
                    """
                    UPDATE calendar_command_requests
                    SET status = ?, calendar_event_id = ?, created_at = ?,
                        last_error = ?
                    WHERE request_id = ?
                    """,
                    (estado, event_id,
                     self.bridge.now().isoformat() if event_id else None,
                     detalle, request_id),
                )
                self.db.enqueue(self.config.owner_chat_id,
                                messages.CALENDAR_UNVERIFIED, parse_mode="HTML")
                self.db.audit("calendar", "create_unverified", event_id or "sin id")
            return True

        if visto is not None:
            event_id = str(visto.get("id") or event_id)

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
                self.db.audit("calendar", "create_no_visible", event_id or "sin id")
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

    def _releer(self, dia: str, request_id: str, event_id: str | None):
        """Busca el evento en su día, por id o por marca, hasta RELECTURAS veces.

        (evento, None) si está; (None, None) si el día se leyó y no está;
        (None, error) si ningún intento pudo leerlo.
        """
        error = None
        for _ in range(RELECTURAS):
            try:
                return self.bridge.find_event(event_id, dia,
                                              request_id=request_id), None
            except Exception as exc:
                error = exc
                print(f"[calendar] no pude releer el día: {exc}", flush=True)
        return None, error

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
