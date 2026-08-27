-- Esquema completo de Mástil.
--
-- Reemplaza los 5 archivos JSON de estado del legacy y la base separada de
-- Mástil Lite. Se aplica entero en cada arranque: todo es CREATE IF NOT EXISTS,
-- así que correrlo de nuevo no destruye nada.
--
-- `lite_reminders` y `lite_settings` conservan EXACTAMENTE las columnas del
-- legacy. Eso permite migrar los recordatorios de la usuaria asistida con un copiado directo,
-- sin recifrar ni reinterpretar una sola fila.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;


-- ---------------------------------------------------------------- sistema

CREATE TABLE IF NOT EXISTS system_state (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT
);


-- --------------------------------------------------------------- guardian
-- Eventos ** : freno -> tregua -> chequeo -> rescate.
--
-- Cada evento conserva su propia fila y su propia fase. `is_active` reproduce
-- el comportamiento del legacy (un solo flujo a la vez), pero al vivir en una
-- columna y no en una variable global, dos eventos ya no pueden pisarse.

CREATE TABLE IF NOT EXISTS guardian_events (
    event_id            TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    start_at            TEXT NOT NULL,
    phase               TEXT NOT NULL DEFAULT 'brake',
    last_sent           TEXT,
    truce_until         TEXT,
    check_until         TEXT,
    restart_until       TEXT,
    rescue_started_at   TEXT,
    minutos_en_rescate  INTEGER NOT NULL DEFAULT 0,
    next_at             TEXT,     -- cuándo toca el próximo escalón
    code_hash           TEXT,     -- código que cierra desde el nivel 2
    is_active           INTEGER NOT NULL DEFAULT 0,
    -- Cola: un evento que vence con el canal ocupado no se pierde ni se
    -- superpone, espera acá hasta que la persona decida qué hacer con él.
    queue_seq           INTEGER,  -- orden FIFO; DESPUÉS reasigna el último
    decision_at         TEXT,     -- cuándo se presentó (≠ start_at, que no se toca)
    decision_step       INTEGER NOT NULL DEFAULT 0,
    decision_next_at    TEXT,     -- próximo recordatorio de la decisión
    -- Nivel 3 acotado en el tiempo. La intervención intensa dura 70 minutos
    -- desde la PRIMERA ráfaga; después el evento sigue pendiente, pero pasa a
    -- un mensaje por hora. Bajar el volumen no es resolver ni olvidar.
    intervencion_at     TEXT,     -- primera ráfaga: el reloj de los 70 minutos
    rafagas             INTEGER NOT NULL DEFAULT 0,
    modo                TEXT,     -- NULL/'normal' mientras insiste, 'bajo' después
    -- Tregua deliberada de 11 minutos, ofrecida sólo en la segunda ráfaga.
    tregua_hasta        TEXT,
    tregua_code_hash    TEXT,
    tregua_code_hasta   TEXT,     -- el código vive 5 minutos y no se reusa
    created_at          TEXT NOT NULL,
    updated_at          TEXT
);

CREATE INDEX IF NOT EXISTS idx_guardian_active ON guardian_events(is_active);
CREATE INDEX IF NOT EXISTS idx_guardian_phase  ON guardian_events(phase);


-- --------------------------------------------------------------- pomodoro
-- Una sola sesión a la vez, igual que el legacy. id = 1 siempre.

CREATE TABLE IF NOT EXISTS pomodoro_session (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    active              INTEGER NOT NULL DEFAULT 0,
    phase               TEXT,
    focus               TEXT,
    cycle               INTEGER NOT NULL DEFAULT 1,
    next_cycle          INTEGER NOT NULL DEFAULT 1,
    phase_until         TEXT,
    return_until        TEXT,
    rescue_started_at   TEXT,
    last_sent           TEXT,
    minutos_en_rescate  INTEGER NOT NULL DEFAULT 0,
	work_minutes        INTEGER NOT NULL DEFAULT 20,
    updated_at          TEXT
);


-- ------------------------------------------------------------------ timer
-- Un solo timer a la vez. id = 1 siempre.

CREATE TABLE IF NOT EXISTS timer (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    active              INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'idle',   -- idle|running|paused|ringing
    duration_minutes    INTEGER NOT NULL DEFAULT 0,
    reason              TEXT NOT NULL DEFAULT '',
    started_at          TEXT,
    ends_at             TEXT,
    paused_at           TEXT,
    milestones          TEXT NOT NULL DEFAULT '[]',     -- JSON: [15, 30]
    fired_milestones    TEXT NOT NULL DEFAULT '[]',     -- JSON: [15]
    ringing_started_at  TEXT,
    last_alarm_sent     TEXT,
    -- Tres modalidades sobre el MISMO motor. La fila sigue siendo una sola
    -- (CHECK id = 1), asi que la exclusividad no necesita codigo: es del
    -- esquema. Lo unico que cambia entre modos es como se calcula `ends_at`.
    --   countdown  -> ends_at = ahora + duration_minutes
    --   fixed      -> ends_at = la hora pedida (hoy o manana)
    --   repeating  -> ends_at = ahora + interval_minutes, y se reprograma
    modo                TEXT NOT NULL DEFAULT 'countdown',
    interval_minutes    INTEGER NOT NULL DEFAULT 0,
    updated_at          TEXT
);


-- ------------------------------------------------------------ mástil lite
-- ¡No cambiar estas dos tablas! Son idénticas a las del legacy para que la
-- migración de los recordatorios de la usuaria asistida sea un copiado fila por fila.
-- `activity_enc` va cifrado: el propietario nunca ve el texto.

CREATE TABLE IF NOT EXISTS lite_reminders (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_chat_id      TEXT NOT NULL,
    user_name         TEXT NOT NULL,
    remind_at_utc     TEXT NOT NULL,
    display_date      TEXT NOT NULL,
    display_time      TEXT NOT NULL,
    activity_enc      TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending|alerting|confirmed|timeout
    alert_code        TEXT,
    first_alert_utc   TEXT,
    last_alert_utc    TEXT,
    created_at_utc    TEXT NOT NULL,
    confirmed_at_utc  TEXT,
    timeout_at_utc    TEXT
);

CREATE INDEX IF NOT EXISTS idx_lite_status ON lite_reminders(status, remind_at_utc);

CREATE TABLE IF NOT EXISTS lite_settings (
    user_chat_id    TEXT PRIMARY KEY,
    paused          INTEGER NOT NULL DEFAULT 0,
    updated_at_utc  TEXT
);


-- ------------------------------------------------------------------ vigía
-- Eventos ++ . Una sesión activa a la vez, igual que el legacy. id = 1.
-- Las fotos NO van en la base: quedan en data/evidence/vigia/ y aquí sólo
-- se guarda la ruta.

CREATE TABLE IF NOT EXISTS vigia_session (
    id                      INTEGER PRIMARY KEY CHECK (id = 1),
    active                  INTEGER NOT NULL DEFAULT 0,
    event_id                TEXT,
    raw_title               TEXT,
    title                   TEXT,
    activity_type           TEXT,
    duration_minutes        INTEGER NOT NULL DEFAULT 0,
    duration_confirmed      INTEGER NOT NULL DEFAULT 0,
    stage                   TEXT,
    created_at              TEXT,
    active_started_at       TEXT,
    active_ends_at          TEXT,
    start_photo_ref         TEXT,
    end_photo_ref           TEXT,
    extra_photo_ref         TEXT,
    needs_extra_photo       INTEGER NOT NULL DEFAULT 0,
    presence_times          TEXT NOT NULL DEFAULT '[]',  -- JSON: lista ISO
    sent_presence_indexes   TEXT NOT NULL DEFAULT '[]',  -- JSON: lista int
    last_rescue_at          TEXT,
    code_hash               TEXT,
    first_code_ok           INTEGER NOT NULL DEFAULT 0,
    -- Vigía 2.0: la unidad de estado es la tarea, no el tiempo. `title` guarda
    -- el objetivo; estas cuatro guardan lo que permite retomar días después.
    contexto                TEXT,     -- lo que la persona aclaró antes de la foto
    estrategia              TEXT,     -- JSON: las fases, para no replanificar
    bloque                  TEXT,     -- la única acción en curso
    ultima_foto             TEXT,     -- para reanalizar tras una aclaración
    declarados              TEXT,     -- JSON: bloques dados por hechos sin foto
    trabado                 INTEGER NOT NULL DEFAULT 0,
    -- Snapshot del contexto tal como lo vio la ULTIMA foto analizada. Sirve
    -- para marcarle al modelo qué campos cambiaron desde entonces: sin esto,
    -- un contexto editado a mitad de tarea se diluye entre lo que ya conocía.
    contexto_analizado       TEXT,
    updated_at              TEXT
);

CREATE TABLE IF NOT EXISTS vigia_completed_events (
    event_id      TEXT PRIMARY KEY,
    completed_at  TEXT NOT NULL
);

-- Evidencia fotográfica: ruta en disco + huella, nunca el binario.
CREATE TABLE IF NOT EXISTS vigia_evidence (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL,
    stage        TEXT NOT NULL,               -- start|end|extra
    path         TEXT NOT NULL,
    sha256       TEXT,
    approved     INTEGER,
    decision     TEXT,
    reason       TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_event ON vigia_evidence(event_id);


-- ----------------------------------------------------- privacidad calendar
-- El ledger es la fuente de verdad para revertir una ofuscación. Se escribe
-- ANTES de tocar el calendario: si el proceso muere, el arranque repone.

CREATE TABLE IF NOT EXISTS calendar_privacy_ledger (
    event_id        TEXT PRIMARY KEY,
    day             TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    obfuscated_at   TEXT NOT NULL,
    reason          TEXT,
    applied         INTEGER NOT NULL DEFAULT 0
);


-- ------------------------------------------------- comandos de Calendar
-- La clave es el message_id de Telegram. Permite reintentar una solicitud sin
-- duplicar un evento si la red se corta despues de que Calendar lo creo.

CREATE TABLE IF NOT EXISTS calendar_command_requests (
    request_id          TEXT PRIMARY KEY,
    status              TEXT NOT NULL CHECK(status IN ('pending', 'created', 'failed')),
    calendar_event_id   TEXT,
    requested_at        TEXT NOT NULL,
    created_at          TEXT,
    last_error          TEXT
);

CREATE INDEX IF NOT EXISTS idx_calendar_command_status
ON calendar_command_requests(status, requested_at);


-- ------------------------------------------------------------------ gmail
-- Sólo metadatos de la última consulta, para poder pedir "el número 3".
-- El cuerpo del correo jamás se guarda.

CREATE TABLE IF NOT EXISTS gmail_session (
    n           INTEGER PRIMARY KEY,
    message_id  TEXT NOT NULL,
    sender      TEXT,
    subject     TEXT,
    date        TEXT,
    created_at  TEXT NOT NULL
);


-- ----------------------------------------------------------------- outbox
-- El corazón de la garantía: el mensaje a enviar se escribe en la MISMA
-- transacción que el cambio de estado. Si el proceso muere, o se hicieron
-- ambas cosas o ninguna. Nunca se insiste dos veces ni se pierde un aviso.
--
-- `send_after` permite programar ráfagas (los 3 avisos del timer separados
-- por 4 segundos) sin bloquear el loop con sleep().

CREATE TABLE IF NOT EXISTS outbox (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'text',   -- text|photo|edit
    text         TEXT,
    buttons      TEXT,                           -- JSON: [[label, command], ...]
    message_id   INTEGER,                        -- solo kind='edit': qué mensaje reemplazar
    photo_path   TEXT,
    parse_mode   TEXT,
    delete_photo INTEGER NOT NULL DEFAULT 0,     -- borrar el archivo tras enviar
    send_after   TEXT,
    created_at   TEXT NOT NULL,
    sent_at      TEXT,
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(sent_at, send_after);




-- ------------------------------------------------------------- intervalos
-- Cronómetro de vueltas, como el del teléfono. Cada marca guarda una hora y
-- nada más.
--
-- Deliberadamente sin opinión: no calcula rachas, no compara con récords y no
-- felicita ni sanciona. Sólo registra hechos. Un cronómetro que opina deja de
-- ser un cronómetro.
--
-- El tramo y el total NO se guardan: se calculan al mostrarlos. Un solo dato
-- por fila, imposible que discrepe consigo mismo.

CREATE TABLE IF NOT EXISTS interval_marks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        TEXT NOT NULL,
    marked_at_utc  TEXT NOT NULL,   -- ISO-8601 en UTC
    local_day      TEXT NOT NULL,   -- YYYY-MM-DD en la zona local
    request_id     TEXT NOT NULL UNIQUE,  -- evita duplicar por reintento
    alerts_sent    INTEGER NOT NULL DEFAULT 0,  -- avisos ya emitidos
    alert_ack      INTEGER NOT NULL DEFAULT 0   -- se apretó "ok"
);

CREATE INDEX IF NOT EXISTS idx_interval_marks_user_day
ON interval_marks(user_id, local_day, marked_at_utc);


-- ---------------------------------------------------------------- auditoría
-- Qué pasó y cuándo. Nunca contenido privado: ni texto de recordatorios de
-- la usuaria asistida, ni cuerpos de correo, ni títulos de Calendar.

CREATE TABLE IF NOT EXISTS audit_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    module      TEXT NOT NULL,
    action      TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at);
