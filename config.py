"""Configuración de Mástil.

Regla única e innegociable de este archivo: **todas** las rutas se derivan de
`__file__`. Ningún otro módulo del proyecto puede contener una ruta absoluta.
Gracias a eso, copiar la carpeta a otro directorio produce una instalación
independiente, sin tocar la original.

Los secretos viven en `.env`, nunca en el código ni en el repositorio.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Rutas. Todo cuelga de aquí.
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent

DATA_DIR = ROOT / "data"
EVIDENCE_DIR = DATA_DIR / "evidence" / "vigia"
DB_PATH = DATA_DIR / "mastil.db"
SCHEMA_PATH = ROOT / "schema.sql"
LITE_SECRET_PATH = DATA_DIR / "lite_secret.key"
ENV_PATH = ROOT / ".env"


def _load_env(path: Path) -> None:
    """Carga .env sin dependencias externas.

    No pisa variables ya presentes en el entorno: eso permite sobrescribir
    cualquier valor al lanzar el proceso, que es lo que hace útil un ambiente
    de desarrollo.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class LiteUser:
    """Usuaria de Mástil Lite. Su contenido es privado incluso del propietario."""

    chat_id: str
    name: str
    timezone: str


def _parse_lite_users(raw: str) -> tuple[LiteUser, ...]:
    """Formato: `chat_id:Nombre:Zona, chat_id:Nombre:Zona`.

    La zona horaria es opcional y cae en la del sistema.
    """
    users: list[LiteUser] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.split(":")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        timezone = parts[2] if len(parts) > 2 and parts[2] else _str(
            "MASTIL_TIMEZONE", "America/Santiago"
        )
        users.append(LiteUser(parts[0], parts[1], timezone))
    return tuple(users)


@dataclass(frozen=True)
class Config:
    # --- identidad y credenciales -----------------------------------------
    telegram_bot_token: str
    owner_chat_id: str
    ical_url: str
    timezone: str

    # --- Calendar ----------------------------------------------------------
    prefix: str                       # marca de eventos Guardian
    activity_prefix: str              # marca de eventos Vigía
    poll_seconds: float

    # --- Guardian (eventos **) --------------------------------------------
    anticipacion_alerta_minutes: int
    intervalo_arranque_seconds: int
    duracion_tregua_minutes: int
    tolerancia_chequeo_minutes: int
    intervalo_rescate_inicial_seconds: int
    intervalo_rescate_acelerado_seconds: int
    rescate_acelera_despues_minutes: int

    # --- Pomodoro ----------------------------------------------------------
    pomodoro_trabajo_minutes: int
    pomodoro_descanso_corto_seconds: int
    pomodoro_descanso_largo_minutes: int
    pomodoro_tolerancia_retorno_minutes: int
    pomodoro_ciclos: int

    # --- Timer -------------------------------------------------------------
    timer_alarma_cada_seconds: int
    timer_autoapagado_seconds: int
    timer_burst_gap_seconds: int

    # --- Mástil Lite -------------------------------------------------------
    lite_users: tuple[LiteUser, ...]
    lite_alert_every_seconds: int
    lite_max_alert_seconds: int

    # --- Vigía (eventos ++) ------------------------------------------------
    vigia_rescue_every_seconds: int
    vigia_third_photo_probability: float
    vigia_min_presence_messages: int
    vigia_max_presence_messages: int
    vigia_code_digits: int
    vigia_default_duration_minutes: int
    gemini_api_key: str
    gemini_model: str

    # --- Puentes de Apps Script -------------------------------------------
    calendar_webapp_url: str
    calendar_token: str
    calendar_id: str
    gmail_webapp_url: str
    gmail_token: str

    # --- rutas (no se leen del entorno) ------------------------------------
    root: Path = field(default=ROOT)
    db_path: Path = field(default=DB_PATH)
    schema_path: Path = field(default=SCHEMA_PATH)
    evidence_dir: Path = field(default=EVIDENCE_DIR)
    lite_secret_path: Path = field(default=LITE_SECRET_PATH)

    # --- helpers -----------------------------------------------------------

    @property
    def calendar_bridge_enabled(self) -> bool:
        """Sin URL y token no hay forma de escribir en Calendar.

        Dejar esto vacío es el interruptor de seguridad: un ambiente de
        desarrollo sin estas dos variables no puede tocar el calendario real.
        """
        return bool(self.calendar_webapp_url and self.calendar_token)

    @property
    def gmail_enabled(self) -> bool:
        return bool(self.gmail_webapp_url and self.gmail_token)

    @property
    def vision_enabled(self) -> bool:
        return bool(self.gemini_api_key)

    def lite_user(self, chat_id: str) -> LiteUser | None:
        chat_id = str(chat_id)
        for user in self.lite_users:
            if user.chat_id == chat_id:
                return user
        return None

    def is_owner(self, chat_id: object) -> bool:
        return str(chat_id) == self.owner_chat_id


def load(env_path: Path | None = None) -> Config:
    _load_env(env_path or ENV_PATH)

    timezone = _str("MASTIL_TIMEZONE", "America/Santiago")

    config = Config(
        telegram_bot_token=_str("MASTIL_TELEGRAM_BOT_TOKEN"),
        owner_chat_id=_str("MASTIL_OWNER_CHAT_ID"),
        ical_url=_str("MASTIL_ICAL_URL"),
        timezone=timezone,

        prefix=_str("MASTIL_PREFIX", "**"),
        activity_prefix=_str("MASTIL_ACTIVITY_PREFIX", "++"),
        poll_seconds=_float("MASTIL_POLL_SECONDS", 5),

        anticipacion_alerta_minutes=_int("MASTIL_ANTICIPACION_ALERTA_MINUTES", 2),
        intervalo_arranque_seconds=_int("MASTIL_INTERVALO_ARRANQUE_SECONDS", 60),
        duracion_tregua_minutes=_int("MASTIL_DURACION_TREGUA_MINUTES", 5),
        tolerancia_chequeo_minutes=_int("MASTIL_TOLERANCIA_CHEQUEO_MINUTES", 2),
        intervalo_rescate_inicial_seconds=_int("MASTIL_INTERVALO_RESCATE_INICIAL_SECONDS", 60),
        intervalo_rescate_acelerado_seconds=_int("MASTIL_INTERVALO_RESCATE_ACELERADO_SECONDS", 30),
        rescate_acelera_despues_minutes=_int("MASTIL_RESCATE_ACELERA_DESPUES_MINUTES", 5),

        pomodoro_trabajo_minutes=_int("MASTIL_POMODORO_TRABAJO_MINUTES", 20),
        pomodoro_descanso_corto_seconds=_int("MASTIL_POMODORO_DESCANSO_CORTO_SECONDS", 330),
        pomodoro_descanso_largo_minutes=_int("MASTIL_POMODORO_DESCANSO_LARGO_MINUTES", 20),
        pomodoro_tolerancia_retorno_minutes=_int("MASTIL_POMODORO_TOLERANCIA_RETORNO_MINUTES", 2),
        pomodoro_ciclos=_int("MASTIL_POMODORO_CICLOS", 4),

        timer_alarma_cada_seconds=_int("MASTIL_TIMER_ALARMA_CADA_SECONDS", 20),
        timer_autoapagado_seconds=_int("MASTIL_TIMER_AUTOAPAGADO_SECONDS", 360),
        timer_burst_gap_seconds=_int("MASTIL_TIMER_BURST_GAP_SECONDS", 4),

        lite_users=_parse_lite_users(_str("MASTIL_LITE_USERS")),
        lite_alert_every_seconds=_int("MASTIL_LITE_ALERT_EVERY_SECONDS", 30),
        lite_max_alert_seconds=_int("MASTIL_LITE_MAX_ALERT_SECONDS", 600),

        vigia_rescue_every_seconds=_int("MASTIL_VIGIA_RESCUE_EVERY_SECONDS", 60),
        vigia_third_photo_probability=_float("MASTIL_VIGIA_THIRD_PHOTO_PROBABILITY", 0.33),
        vigia_min_presence_messages=_int("MASTIL_VIGIA_MIN_PRESENCE_MESSAGES", 1),
        vigia_max_presence_messages=_int("MASTIL_VIGIA_MAX_PRESENCE_MESSAGES", 3),
        vigia_code_digits=_int("MASTIL_VIGIA_CODE_DIGITS", 4),
        vigia_default_duration_minutes=_int("MASTIL_VIGIA_DEFAULT_DURATION_MINUTES", 20),
        gemini_api_key=_str("MASTIL_GEMINI_API_KEY"),
        gemini_model=_str("MASTIL_GEMINI_MODEL", "gemini-3.5-flash"),

        calendar_webapp_url=_str("MASTIL_CALENDAR_WEBAPP_URL"),
        calendar_token=_str("MASTIL_CALENDAR_TOKEN"),
        calendar_id=_str("MASTIL_CALENDAR_ID", "primary"),
        gmail_webapp_url=_str("MASTIL_GMAIL_WEBAPP_URL"),
        gmail_token=_str("MASTIL_GMAIL_TOKEN"),
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        DATA_DIR.chmod(0o700)
    except OSError:
        pass

    return config


def require(config: Config) -> None:
    """Falla temprano y con un mensaje claro si falta lo imprescindible."""
    faltantes = [
        nombre
        for nombre, valor in (
            ("MASTIL_TELEGRAM_BOT_TOKEN", config.telegram_bot_token),
            ("MASTIL_OWNER_CHAT_ID", config.owner_chat_id),
            ("MASTIL_ICAL_URL", config.ical_url),
        )
        if not valor
    ]
    if faltantes:
        raise RuntimeError(
            "Faltan variables obligatorias en .env: " + ", ".join(faltantes)
        )
