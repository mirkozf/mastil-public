"""Reglas de tiempo. Deterministas y sin IA.

Todo lo que decide *cuándo* pasa algo vive acá: cuándo toca insistir, cuándo el
rescate acelera, cuándo vence un plazo. Ningún modelo interviene en esto.

Es también el único lugar del proyecto donde un error no se ve como una
excepción en el log sino como un comportamiento silenciosamente equivocado:
insistir de más, insistir de menos, o no insistir. Por eso está aislado.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


# ------------------------------------------------------------------ reloj

# La zona en la que Mástil piensa. Se fija una vez al arrancar, desde el
# `.env`, y no vuelve a cambiar.
#
# Antes se usaba la del sistema operativo, y eso hacía que el MISMO código se
# comportara distinto según dónde corriera: en el equipo del dueño la zona ya
# era la correcta, pero en un servidor en UTC "avísame a las 21:40" agendaba
# las 21:40 UTC — cuatro horas antes— y todas las horas mostradas venían
# corridas. Un error que las pruebas no podían ver, porque corren en la
# máquina donde sí coincidía.
_ZONA: ZoneInfo | None = None


def set_timezone(nombre: str | None) -> None:
    """Fija la zona del proceso. La llama `main.py` al arrancar."""
    global _ZONA
    if not nombre:
        _ZONA = None
        return
    try:
        _ZONA = ZoneInfo(nombre)
    except Exception as exc:
        # No puede tumbar el arranque: se cae a la zona del sistema, que es
        # exactamente el comportamiento anterior.
        #
        # Pasa en Windows, donde Python no trae la base de zonas IANA. En Linux
        # —donde corre producción, que es donde el error importaba— sí está.
        _ZONA = None
        print(
            f"[scheduler] no pude cargar la zona {nombre} ({exc}). "
            f"Uso la del sistema: {datetime.now().astimezone().tzname()}.",
            flush=True,
        )


def timezone_actual() -> ZoneInfo | None:
    """La zona vigente, o None si se está usando la del sistema."""
    return _ZONA


def now_local() -> datetime:
    """Ahora, en la zona configurada. Siempre consciente de tz."""
    return datetime.now(_ZONA) if _ZONA else datetime.now().astimezone()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(_ZONA).isoformat()


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        # Sin zona escrita, la hora es de pared: pertenece a la zona en la
        # que Mástil piensa, no a la del servidor que la está leyendo.
        return parsed.replace(tzinfo=_ZONA) if _ZONA else parsed.astimezone()
    return parsed


# ----------------------------------------------------------- insistencia

def should_send(last_sent: str | datetime | None, interval_seconds: float,
                now: datetime | None = None) -> bool:
    """¿Pasó suficiente tiempo desde el último aviso?

    Sin aviso previo la respuesta es sí: el primer mensaje nunca espera.
    """
    now = now or now_local()
    last = from_iso(last_sent) if isinstance(last_sent, (str, type(None))) else last_sent
    if not last:
        return True
    return (now - last).total_seconds() >= interval_seconds


def rescue_interval(
    rescue_started_at: str | datetime | None,
    initial_seconds: int,
    accelerated_seconds: int,
    accelerate_after_minutes: int,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Intervalo de rescate y minutos acumulados.

    El rescate empieza espaciado y se acelera si la persona sigue sin
    responder. No es castigo: es que la señal suave ya se demostró
    insuficiente para romper la captura atencional.

    Devuelve (segundos_entre_avisos, minutos_en_rescate).
    """
    now = now or now_local()
    started = from_iso(rescue_started_at) if isinstance(
        rescue_started_at, (str, type(None))
    ) else rescue_started_at

    if not started:
        return initial_seconds, 0

    elapsed = (now - started).total_seconds()
    minutos = int(elapsed // 60)

    if elapsed < accelerate_after_minutes * 60:
        return initial_seconds, minutos
    return accelerated_seconds, minutos


def is_due(deadline: str | datetime | None, now: datetime | None = None) -> bool:
    """¿Ya venció este plazo? Un plazo ausente nunca vence."""
    now = now or now_local()
    when = from_iso(deadline) if isinstance(deadline, (str, type(None))) else deadline
    if not when:
        return False
    return now >= when


def deadline(minutes: float = 0, seconds: float = 0,
             now: datetime | None = None) -> datetime:
    now = now or now_local()
    return now + timedelta(minutes=minutes, seconds=seconds)


def within_window(
    start: datetime,
    before: timedelta,
    after: timedelta,
    now: datetime | None = None,
) -> bool:
    """¿Estamos en la ventana [start - before, start + after]?"""
    now = now or now_local()
    return start - before <= now <= start + after


# -------------------------------------------------------------- formato

def format_duration(seconds: float) -> str:
    """`05:30`, o `01:05:30` si pasa de una hora."""
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    rest = seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{rest:02d}"
    return f"{minutes:02d}:{rest:02d}"


def clock(value: datetime | None) -> str:
    """Hora del reloj, `21:30`, en la zona configurada.

    Importa que convierta: en la base pueden convivir marcas guardadas con
    offsets distintos —las anteriores a este arreglo quedaron en UTC— y
    todas tienen que verse en la misma hora de pared.
    """
    if value is None:
        return "--:--"
    return value.astimezone(_ZONA).strftime("%H:%M")


def remaining_seconds(until: str | datetime | None,
                      now: datetime | None = None) -> float:
    now = now or now_local()
    when = from_iso(until) if isinstance(until, (str, type(None))) else until
    if not when:
        return 0.0
    return (when - now).total_seconds()
