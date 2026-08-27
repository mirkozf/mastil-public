"""Google Calendar: lectura del ICS y el puente de privacidad.

Dos cosas muy distintas conviven acá, y conviene tenerlas claras:

1. **Lectura del ICS.** Es sólo lectura y no puede romper nada. Es de donde
   salen los eventos `**` (Guardian) y `++` (Vigía).

2. **El puente de escritura** (Apps Script), que ofusca títulos mientras Vigía
   espera evidencia, para que el calendario no compita visualmente con la
   acción pedida.

La parte 2 tiene historia: una implementación anterior reemplazó títulos por
texto aleatorio, el respaldo no representaba el estado previo, y la restauración
informó éxito con títulos que ya eran irrecuperables. De ahí las reglas duras:

- sólo Base64 reversible, nunca ruido irreversible;
- el ledger con los originales se escribe **antes** de tocar el calendario;
- si falta `MASTIL_CALENDAR_WEBAPP_URL` o `MASTIL_CALENDAR_TOKEN`, el puente
  queda inerte. Ese es el interruptor de seguridad del ambiente de desarrollo.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

MARKER = "MASTIL64_V1:"

# Ventana de rescate al arrancar: si el proceso estuvo caído varios días, hay
# que barrer hacia atrás para que ningún evento quede ofuscado fuera de alcance.
SCAN_BACK_DAYS = 7
SCAN_FWD_DAYS = 3

JUNK_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789abcdefghijkmnpqrstuvwxyz"


# ==========================================================================
# Títulos de eventos
# ==========================================================================

def is_guardian_event(title: str, prefix: str = "**") -> bool:
    return str(title or "").strip().startswith(prefix)


def is_activity_event(title: str, prefix: str = "++") -> bool:
    return str(title or "").strip().startswith(prefix)


def clean_title(title: str, prefixes: tuple[str, ...] = ("++", "**")) -> str:
    text = str(title or "").strip()
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


# ==========================================================================
# Lectura del ICS
# ==========================================================================

def _clean_ics_text(value: str | None) -> str:
    if not value:
        return ""
    return (
        value.replace("\\n", " ")
        .replace("\\N", " ")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def _get_prop(block: str, name: str) -> str | None:
    match = re.search(rf"(?m)^{name}(?:;[^:]*)?:(.*)$", block)
    return match.group(1).strip() if match else None


def _parse_ics_datetime(block: str, field: str) -> datetime | None:
    match = re.search(rf"(?m)^{field}(?:;[^:]*)?:(\d{{8}}(?:T\d{{4,6}}Z?)?)", block)
    if not match:
        return None

    value = match.group(1)
    local_tz = datetime.now().astimezone().tzinfo

    if value.endswith("Z"):
        raw = value[:-1]
        fmt = "%Y%m%dT%H%M%S" if len(raw) == 15 else "%Y%m%dT%H%M"
        return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).astimezone()

    if len(value) == 8:
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=local_tz)

    fmt = "%Y%m%dT%H%M%S" if len(value) == 15 else "%Y%m%dT%H%M"
    return datetime.strptime(value, fmt).replace(tzinfo=local_tz)


def read_events(ical_url: str, prefix: str = "**",
                activity_prefix: str = "++", timeout: int = 30) -> list[dict[str, Any]]:
    """Devuelve los eventos marcados, ordenados por hora de inicio.

    Se agrega un parámetro con marca de tiempo a la URL porque el feed de
    Google se cachea con ganas, y un evento agregado hace dos minutos tiene que
    verse ahora, no en veinte.
    """
    stamp = urllib.parse.quote(
        datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    )
    separator = "&" if "?" in ical_url else "?"
    url = f"{ical_url}{separator}mastil_cache_bust={stamp}"

    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")

    # El ICS parte líneas largas con un salto seguido de espacio. Reunirlas.
    raw = re.sub(r"(\r\n|\n|\r)[ \t]", "", raw)

    events: list[dict[str, Any]] = []
    for match in re.finditer(r"(?s)BEGIN:VEVENT(.*?)END:VEVENT", raw):
        block = match.group(1)
        title = _clean_ics_text(_get_prop(block, "SUMMARY"))
        if not (title.startswith(prefix) or title.startswith(activity_prefix)):
            continue

        start = _parse_ics_datetime(block, "DTSTART")
        if not start:
            continue

        uid = _get_prop(block, "UID") or title
        events.append({
            "id": f"{uid}|{start.isoformat()}|{title}",
            "title": title,
            "start": start,
            "end": _parse_ics_datetime(block, "DTEND"),
        })

    return sorted(events, key=lambda event: event["start"])


# ==========================================================================
# Puente de escritura (Apps Script)
# ==========================================================================

class CalendarBridge:
    def __init__(self, webapp_url: str, token: str, calendar_id: str = "primary",
                 timezone_name: str = "America/Santiago"):
        self.webapp_url = webapp_url
        self.token = token
        self.calendar_id = calendar_id
        self.tz = ZoneInfo(timezone_name)

    @property
    def enabled(self) -> bool:
        return bool(self.webapp_url and self.token)

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def day(self, offset: int = 0) -> str:
        return (self.now() + timedelta(days=offset)).strftime("%Y-%m-%d")

    def call(self, action: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError(
                "El puente de Calendar está deshabilitado en esta instalación."
            )

        body: dict[str, Any] = {
            "token": self.token,
            "action": action,
            "calendar_id": self.calendar_id,
        }
        if extra:
            body.update(extra)

        request = urllib.request.Request(
            self.webapp_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        raw = urllib.request.urlopen(request, timeout=60).read().decode("utf-8")
        data = json.loads(raw)
        if not data.get("ok"):
            raise RuntimeError(json.dumps(data, ensure_ascii=False))
        return data

    def snapshot_day(self, day: str) -> list[dict[str, Any]]:
        return self.call("snapshot_day", {"day": day}).get("snapshot", [])

    def restore(self, snapshot: list[dict[str, Any]]) -> dict[str, Any]:
        return self.call("restore", {"snapshot": snapshot})

    def create_event(
        self,
        *,
        title: str,
        start_at: datetime,
        end_at: datetime,
        request_id: str,
    ) -> dict[str, Any]:
        """Crea un evento con una clave idempotente del mensaje de Telegram.

        Calendar es externo a SQLite: no podemos incluir ambas escrituras en
        una misma transaccion. `request_id` permite que Apps Script reconozca
        un reintento y devuelva el evento ya creado, en vez de duplicarlo.
        """
        data = self.call(
            "create_event",
            {
                "title": title,
                "start_at": start_at.astimezone(self.tz).isoformat(),
                "end_at": end_at.astimezone(self.tz).isoformat(),
                "timezone": self.tz.key,
                "request_id": request_id,
            },
        )
        event = data.get("event")
        if not isinstance(event, dict) or not event.get("id"):
            raise RuntimeError("El puente de Calendar no devolvio el evento creado.")
        return data

    def find_event(self, event_id: str, day: str) -> dict[str, Any] | None:
        """Relee el día y devuelve el evento si realmente está ahí.

        Sirve para no confiar en la palabra del puente. Que Apps Script
        conteste "ok" no prueba que el evento exista: puede haber fallado
        después de responder, haberlo creado en otro día por una diferencia
        de zona horaria, o devolver un id viejo. La única prueba es verlo.
        """
        for evento in self.snapshot_day(day):
            if str(evento.get("id") or "") == str(event_id):
                return evento
        return None


# ==========================================================================
# Ofuscación reversible
# ==========================================================================

def _encode_payload(data: dict[str, Any]) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_payload(text: str) -> dict[str, Any]:
    raw = base64.urlsafe_b64decode(text.encode("ascii")).decode("utf-8")
    return json.loads(raw)


def _junk_title(seed: str) -> str:
    """Ruido estable e ilegible, sin marca visible.

    El calendario debe verse como basura, no como "algo cifrado": una marca
    visible invita a investigar justo cuando la idea es no competir por la
    atención. Quién es quién lo sabe el ledger.
    """
    digest = hashlib.sha256(("mastil-junk:" + str(seed)).encode("utf-8")).digest()
    return "".join(JUNK_ALPHABET[b % len(JUNK_ALPHABET)] for b in digest[:14])


class CalendarPrivacy:
    """Oculta y repone títulos, con el ledger en SQLite como red de seguridad."""

    def __init__(self, db, bridge: CalendarBridge):
        self.db = db
        self.bridge = bridge

    @property
    def enabled(self) -> bool:
        return self.bridge.enabled

    # ------------------------------------------------------------- ledger

    def _ledger_ids(self) -> set[str]:
        return {
            row["event_id"]
            for row in self.db.query("SELECT event_id FROM calendar_privacy_ledger")
        }

    def _ledger_entry(self, event_id: str):
        return self.db.one(
            "SELECT * FROM calendar_privacy_ledger WHERE event_id = ?", (event_id,)
        )

    def pending_count(self) -> int:
        row = self.db.one("SELECT COUNT(*) AS c FROM calendar_privacy_ledger")
        return int(row["c"]) if row else 0

    def needs_recovery(self) -> bool:
        """Sólo mira la base, ni una llamada al puente.

        Como el ledger se escribe ANTES de tocar el calendario, un ledger vacío
        implica calendario intacto.
        """
        return self.pending_count() > 0

    # ---------------------------------------------------------- ofuscación

    def obfuscate_today_tomorrow(self, reason: str = "") -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "status": "disabled", "changed_count": 0}

        days = [self.bridge.day(0), self.bridge.day(1)]
        known = self._ledger_ids()
        total_changed = 0

        for day in days:
            snapshot = self.bridge.snapshot_day(day)

            pending = []
            for event in snapshot:
                event_id = str(event.get("id") or "")
                if not event_id or event_id in known:
                    continue
                if str(event.get("title") or "").startswith(MARKER):
                    continue
                if str(event.get("description") or "").startswith(MARKER):
                    continue
                pending.append(event)

            if not pending:
                continue

            # ESCRITURA ANTICIPADA: los originales van a la base ANTES de tocar
            # el calendario. Si el proceso muere aquí, el arranque los repone.
            with self.db.transaction():
                for event in pending:
                    self.db.execute(
                        """
                        INSERT OR REPLACE INTO calendar_privacy_ledger
                            (event_id, day, title, description, obfuscated_at, reason, applied)
                        VALUES (?, ?, ?, ?, ?, ?, 0)
                        """,
                        (
                            str(event["id"]), day,
                            event.get("title", ""), event.get("description", ""),
                            self.bridge.now().isoformat(), reason,
                        ),
                    )

            self.bridge.restore([self._as_obfuscated(e) for e in pending])

            with self.db.transaction():
                for event in pending:
                    self.db.execute(
                        "UPDATE calendar_privacy_ledger SET applied = 1 WHERE event_id = ?",
                        (str(event["id"]),),
                    )
                known.add(str(event["id"]))

            total_changed += len(pending)

        return {
            "ok": True,
            "status": "obfuscated" if self.pending_count() else "clear",
            "changed_count": total_changed,
            "days": days,
        }

    def _as_obfuscated(self, event: dict[str, Any]) -> dict[str, Any]:
        original = {
            "id": event.get("id"),
            "title": event.get("title", ""),
            "description": event.get("description", ""),
            "encoded_at": self.bridge.now().isoformat(),
        }
        return {
            "id": event.get("id"),
            "title": _junk_title(f"{original['id']}|{original['title']}"),
            "description": MARKER + _encode_payload(original),
        }

    # -------------------------------------------------------- restauración

    def _decode_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Tres vías de recuperación, en orden de confianza."""
        event_id = str(event.get("id") or "")
        title = str(event.get("title") or "")
        description = str(event.get("description") or "")

        # 1. payload en la descripción (formato actual)
        if description.startswith(MARKER):
            try:
                data = _decode_payload(description.replace(MARKER, "", 1).strip())
                return {
                    "id": event.get("id"),
                    "title": data.get("title", ""),
                    "description": data.get("description", ""),
                }
            except Exception:
                pass

        # 2. payload en el título (formato viejo, compatibilidad)
        if title.startswith(MARKER):
            try:
                data = _decode_payload(title.replace(MARKER, "", 1).strip())
                return {
                    "id": event.get("id"),
                    "title": data.get("title", ""),
                    "description": "" if description.startswith(MARKER) else description,
                }
            except Exception:
                pass

        # 3. el ledger, que sobrevive aunque el evento pierda su descripción
        entry = self._ledger_entry(event_id)
        if entry:
            return {
                "id": event.get("id"),
                "title": entry["title"],
                "description": entry["description"],
            }

        return None

    def restore_last(self, reason: str = "", deep: bool = False) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "status": "disabled", "restored_count": 0}

        days = {
            row["day"]
            for row in self.db.query("SELECT DISTINCT day FROM calendar_privacy_ledger")
        }
        if deep:
            days.update(self.bridge.day(o) for o in range(-SCAN_BACK_DAYS, SCAN_FWD_DAYS + 1))
        else:
            days.update(self.bridge.day(o) for o in range(-1, 3))

        total_restored = 0
        seen_ids: set[str] = set()

        for day in sorted(days):
            try:
                snapshot = self.bridge.snapshot_day(day)
            except Exception as exc:
                print(f"Calendar privacy: no pude leer {day}: {exc}", flush=True)
                continue

            restore_events = []
            for event in snapshot:
                decoded = self._decode_event(event)
                if decoded:
                    restore_events.append(decoded)
                    seen_ids.add(str(event.get("id") or ""))

            if not restore_events:
                continue

            self.bridge.restore(restore_events)
            total_restored += len(restore_events)

            with self.db.transaction():
                for event in restore_events:
                    self.db.execute(
                        "DELETE FROM calendar_privacy_ledger WHERE event_id = ?",
                        (str(event["id"]),),
                    )

        # Entradas cuyo evento ya no aparece (lo borró el usuario). No hay nada
        # que reponer, pero tampoco se tiran en silencio.
        huerfanas = self.pending_count()
        if huerfanas:
            print(
                f"Calendar privacy: {huerfanas} entradas sin evento visible, "
                "se conservan en el ledger",
                flush=True,
            )

        return {
            "ok": True,
            "status": "clear" if not huerfanas else "partial",
            "restored_count": total_restored,
            "pending_in_ledger": huerfanas,
        }
