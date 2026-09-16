"""Todo el texto que Mástil le dice a una persona.

Está junto a propósito. Mástil es un sistema conductual: el tono importa tanto
como la lógica. Tener el copy repartido en siete módulos hace que cada uno
derive por su lado y que "interrumpe sin castigar" se pierda de a poco. Acá se
lee entero de una sentada.

Los textos son los del legacy, palabra por palabra. Cambiar uno es una decisión
conductual, no un arreglo de estilo.
"""

from __future__ import annotations

import html

# ==========================================================================
# Guardian y Pomodoro comparten rescate y medallas
# ==========================================================================

# ==========================================================================
# Calendar -- creacion simple desde Telegram
# ==========================================================================

CALENDAR_USAGE = (
    "No pude leer el evento. Usa uno de estos formatos:\n\n"
    "Hoy: <code>/cal **ir a comer 18:30</code>\n"
    "Mañana: <code>/cal **ir a comer next 19:30</code>\n"
    "Otra fecha: <code>/cal barrer 12/11 20:00</code>\n\n"
    "La hora va en reloj de 12: agrega <code>a</code> o <code>p</code> al final,\n"
    "o te pregunto. Cada evento dura 30 minutos."
)

CALENDAR_ERROR_TITLE = (
    "Falta el nombre del evento.\n\n"
    "Ejemplo: <code>/cal **ir a comer 18:30</code>"
)

CALENDAR_ERROR_TIME = (
    "No entendí la hora. Va al final, en reloj de 12.\n\n"
    "Ejemplos: <code>9:30 a</code> · <code>1:30 p</code> · <code>21:30</code>"
)

CALENDAR_ERROR_AMPM = (
    "Falta saber si es AM o PM.\n\n"
    "Agrega <code>a</code> o <code>p</code> al final: "
    "<code>9:30 a</code>, <code>1:30 p</code>."
)

CALENDAR_ERROR_MEDIANOCHE = (
    "Las 00 no se usan. La medianoche se escribe <code>12 a</code>."
)

CALENDAR_ERROR_DATE_FORMAT = (
    "La fecha debe ser <code>DD/MM</code>.\n\n"
    "Ejemplo: <code>/cal barrer 12/11 20:00</code>"
)

CALENDAR_UNAVAILABLE = (
    "Calendar no está conectado en esta instalación. No se creó ningún evento."
)

# Sólo después de releer el día y no encontrarlo. Antes salía apenas fallaba
# la respuesta del puente, diciendo "No se creó nada", y casi siempre sí se
# había creado.
CALENDAR_CREATE_FAILED = (
    "No pude crear el evento: lo busqué en Google Calendar y no está. "
    "Inténtalo de nuevo."
)

CALENDAR_ALREADY_CREATED = (
    "Ese mismo mensaje ya creó su evento. No hice un duplicado."
)

# Cuando el evento se creó pero no se pudo releer para comprobarlo. No es un
# fallo ni un éxito: es no saber, y decirlo.
CALENDAR_UNVERIFIED = (
    "⚠️ <b>Envié el evento, pero no pude confirmarlo</b>\n\n"
    "Puede que esté creado. Revisa el calendario antes de volver a intentarlo."
)


def calendar_error_invalid_date(value: str, year: int) -> str:
    return (
        f"La fecha <code>{html.escape(value)}</code> no existe en {year}.\n\n"
        "Usa una fecha real, por ejemplo: <code>/cal barrer 12/11 20:00</code>"
    )


def calendar_created(title, start_at, end_at) -> str:
    return (
        "📅 <b>Evento creado</b>\n\n"
        f"<b>{html.escape(str(title))}</b>\n"
        f"Fecha: <b>{start_at.strftime('%d/%m/%Y')}</b>\n"
        f"Hora: <b>{start_at.strftime('%H:%M')} - {end_at.strftime('%H:%M')}</b>\n"
        "Duración: <b>30 minutos</b>"
    )

FRASES_RESCATE = [
    "El piloto automático tomó el control. Suelta la pantalla o el teclado ahora mismo, estira el cuerpo y muévete. Tu único escape es presionar /listo.",
    "Captura atencional detectada. Deja de mirar fijo, parpadea, respira profundo y ponte de pie. Sal de la Matrix y presiona /listo.",
    "Tu mente te está diciendo 'un minuto más', pero es una trampa. No hay nada más que negociar aquí. Muévete y dale al /listo.",
    "Mírate las manos en este instante: ¿estás haciendo la tarea o flotando en la distracción? Despierta del trance y presiona /listo.",
    "Este mensaje va a seguir llegando cada 60 segundos y va a romper tu concentración. Ahórrate la molestia, levántate y presiona /listo.",
    "Cada vez que vences esta inercia, estás entrenando el músculo que te da el control de tu vida. Haz el movimiento ahora y presiona /listo.",
]

MENSAJES_CIERRE = [
    "🧠 ¡GOLAZO NEURONAL! Acabas de cablear un nuevo camino en tu cerebro. Cada vez que haces esto, la resistencia se vuelve más débil y tú más fuerte. ¡Sigue construyendo!",
    "👑 ¡CONTROL ABSOLUTO! Le pasaste por encima al piloto automático. Hoy mandas tú, tus decisiones mandan. Siéntete orgulloso de este paso.",
    "⚡ ¡INERCIA ROTA! Lo más difícil en la física y en la mente es arrancar. Ya rompiste la fricción inicial, el resto del día es tuyo. ¡Impecable!",
    "🔥 ¡ADENTRO! Uno más al saco. Sin pensarla tanto, directo a la acción. ¡Así se hace!",
    "💪 ¡MECÁNICA TENSIONAL MENTAL! Le metiste carga al músculo de la disciplina y respondió. Otra victoria limpia para la colección.",
    "🌊 ¡LA CURVA BAJÓ! Metiste la pausa y esperaste. La señal subió, hizo pico y bajó sola, como siempre. ¡Notable!",
    "🎯 ¡EVIDENCIA REAL! Tu cabeza te dice una cosa, pero tus acciones demuestran otra. Eres el tipo de hombre que se levanta y lo hace. Punto.",
    "💎 ¡VICTORIA LIMPIA! Registro cerrado en paz y sin deudas pendientes con tu día. Disfruta este momento de orden.",
]

MARGEN_DE_GRACIA = (
    "Copiado. Ajustando el sistema y registrando el cambio. "
    "Tienes tu margen de gracia en marcha. Volvemos a chequear en breve."
)


def task_label(name: str, prefix: str = "**") -> str:
    raw = str(name or "").strip()
    if raw.startswith(prefix):
        raw = raw[len(prefix):].strip()
    if not raw:
        raw = "Sin nombre"
    return f"🔴 `[{raw}]`"


# ==========================================================================
# Guardian — eventos **
# ==========================================================================

def guardian_freno_primero(label: str) -> str:
    return (
        "Es momento de conectar con el presente. "
        f"Quedan 2 minutos para cerrar lo que estás haciendo e iniciar: {label}. "
        "Respira profundo y responde /ok para detener esta alarma."
    )


# --- nivel 1 -------------------------------------------------------------
# Dos mensajes: uno que orienta la mirada y, dos segundos después, la tarea.
# El primero no dice nada todavía; sirve para que el segundo llegue a una
# pantalla que ya estás mirando.

GUARDIAN_ORIENTACION = "⚓ Mástil"

BOTONES_AVISO = [("✅ /listo", "/listo"), ("⏸ /ok", "/ok")]


# --- niveles 2 y 3 -------------------------------------------------------
# La escalada sube en exigencia, no en cantidad. Repetir el mismo aviso cada
# 60 segundos enseñaba a ignorarlo: cada mensaje sin respuesta era un ensayo
# más de que ignorar funciona.
#
# Desde el nivel 2 la salida deja de ser un botón y pasa a ser un número que
# hay que mirar y tipear. Eso no se puede hacer en piloto automático.

GUARDIAN_ATENCION = "👀 Mástil necesita tu atención."

GUARDIAN_CODIGO = "Escribe los 4 dígitos de la imagen."

GUARDIAN_CODIGO_MAL = "Ese número no coincide. Míralo de nuevo."

GUARDIAN_CODIGO_PENDIENTE = "Primero escribe los 4 dígitos de la imagen."


def guardian_atencion_confirmada(label: str) -> str:
    """El código confirma que miraste. No que hiciste la tarea."""
    return f"✅ Atención confirmada.\n\n{label}"


BOTONES_LISTO = [("✅ LISTO", "/listo")]

# Nivel 3: cortos, sin culpa y sin drama. Rotan para que la ráfaga no sea
# siete veces el mismo texto, que el ojo descarta de un vistazo.
GUARDIAN_INSISTE = [
    "⚠️ Mástil sigue esperando.",
    "👀 Mira esto un segundo.",
    "🛑 Sal del piloto automático.",
    "⚓ La tarea continúa pendiente.",
    "👀 Guardian necesita tu atención.",
    "⚠️ Esto sigue pendiente.",
    "🛑 Vuelve a la tarea.",
]


def guardian_insiste_tarea(label: str) -> str:
    """El segundo mensaje de la ráfaga sí nombra la tarea.

    Los otros seis son genéricos a propósito. Este va en el lugar donde la
    pantalla ya está mirada —el primero la orientó— y responde la pregunta
    que el resto de la ráfaga deja abierta: pendiente, sí, pero ¿qué cosa.
    """
    return f"⚓ Sigue pendiente: {label}"


# --- tregua deliberada y baja frecuencia ---------------------------------
# Dos mecanismos distintos y sin relación entre sí. La tregua la pides tú y
# cuesta; la baja frecuencia llega sola a los 70 minutos y no la pide nadie.

BOTONES_LISTO_TREGUA = [
    ("✅ LISTO", "/listo"),
    ("🧩 NECESITO MÁS TIEMPO", "/guardian_tregua"),
]


def guardian_tregua_codigo(minutos: int, ventana: int) -> str:
    """La secuencia va dibujada, y por eso no está en este texto.

    En texto se copia y se pega, y pegar no cuesta atención: es justo el
    piloto automático del que la tregua tiene que sacarte. Leída de una
    imagen y tipeada, sí — y ésa es la pausa que se está comprando.
    """
    return (
        f"🧩 Tregua de {minutos} minutos.\n\n"
        f"Escribe la secuencia de la imagen, tal cual. "
        f"Tienes {ventana} minutos."
    )


GUARDIAN_TREGUA_MAL = "Esa secuencia no coincide. Mírala de nuevo."

GUARDIAN_TREGUA_EXPIRADA = (
    "Esa secuencia ya venció.\n\nLa tarea sigue pendiente."
)

GUARDIAN_TREGUA_VIEJA = "Ese botón ya no aplica."


# La secuencia no se guarda en claro, sólo su hash: no hay forma de volver a
# mostrarla, y tampoco conviene — regenerarla a pedido sería un bucle gratis.
GUARDIAN_TREGUA_PENDIENTE = (
    "Ya te di una secuencia. Escríbela tal cual, o espera a que venza."
)


def guardian_tregua_ok(minutos: int) -> str:
    return f"✅ Secuencia correcta.\n\n⏱️ Tregua de {minutos} minutos."


def guardian_baja_frecuencia(label: str) -> str:
    """Deja de insistir, no deja de estar.

    Sin "te rendiste" y sin "fallaste": lo único que cambia es el volumen. El
    evento sigue abierto y se dice, porque un silencio sin aviso se lee como
    que Guardian se olvidó — y eso es justo lo que no pasó.
    """
    return (
        f"⚓ Dejo de insistir por ahora.\n\n"
        f"{label}\n\n"
        "Sigue pendiente. Te lo recuerdo una vez por hora."
    )


def guardian_sigue_pendiente(label: str) -> str:
    return f"⚓ Sigue pendiente: {label}"


def guardian_chequeo(label: str) -> str:
    return (
        "Pasaron los 5 minutos de tregua. "
        "Mírate con honestidad en este instante: "
        f"¿Lograste dar el primer paso con {label}?\n\n"
        "🔹 Presiona /listo si ya arrancaste y estás en movimiento.\n"
        "🔸 Presiona /reinicio si te quedaste pegado y necesitas que te vuelva a empujar."
    )


BOTONES_CHEQUEO = [("✅ /listo", "/listo"), ("🔁 /reinicio", "/reinicio")]

GUARDIAN_CANCELADO = "Flujo Mástil Calendario cancelado manualmente."
GUARDIAN_SIN_FLUJO = "No había flujo Mástil Calendario activo."


# ==========================================================================
# Pomodoro
# ==========================================================================

POMODORO_CORTE = (
    "🚨 ¡BLOQUE TERMINADO! "
    "Suelta el teclado y el mouse inmediatamente. "
    "La captura atencional se acabó por ahora. "
    "Ejecuta el comando /descanso para iniciar tus minutos de desconexión analógica obligatoria."
)


def pomodoro_sugerencia(minutos: int) -> str:
    """Una sugerencia, no una orden. Ver la tabla en `modules/pomodoro.py`."""
    return f"🧘 Descanso recomendado: {minutos} min"


def pomodoro_iniciado(label: str, cycle: int, ciclos: int, minutos: int,
                      descanso: int | None = None) -> str:
    base = (
        f"Pomodoro iniciado: {label}\n"
        f"Bloque {cycle} de {ciclos}. Trabajo silencioso por {minutos} minutos."
    )
    if descanso is None:
        return base
    return f"{base}\n\n{pomodoro_sugerencia(descanso)}"


def pomodoro_descanso(label: str, kind: str) -> str:
    return (
        f"Descanso iniciado para {label}.\n\n"
        "¡Bloque completado! Iniciando descanso físico obligatorio.\n\n"
        "⚠️ REGLA DE ORO: Está rotundamente PROHIBIDO prender la tele, mirar el celular "
        "o quedarte sentado en la pantalla. Tu cerebro necesita un descanso analógico.\n\n"
        "Ponte de pie, camina por el pasillo, toma agua o estira el cuerpo ahora mismo. "
        "El tiempo ya está corriendo...\n\n"
        f"Tipo: {kind}."
    )


POMODORO_RETORNO = (
    "Terminó el descanso. Mírate con honestidad en este instante: "
    "¿Lograste regresar y estás listo para retomar tu tarea?\n\n"
    "🔹 Presiona /listo si ya arrancaste y estás en movimiento.\n"
    "🔸 Presiona /reinicio si te quedaste pegado y necesitas el rescate."
)

POMODORO_DETENIDO = (
    "🛑 Módulo Pomodoro detenido por completo. El sistema limpia sus registros "
    "y queda en pausa hasta que decidas iniciar un nuevo bloque."
)

POMODORO_DESCANSO_FUERA_DE_TURNO = (
    "Aún no corresponde iniciar descanso. "
    "El comando /descanso se activa cuando termina el bloque de trabajo."
)

POMODORO_DURACION_INVALIDA = (
    "La duración del Pomodoro debe ser un número entre 1 y 240 minutos."
)

POMODORO_SIN_SESION = "No hay Pomodoro activo para iniciar descanso."
POMODORO_ESTADO_VACIO = "Pomodoro: sin sesión activa."


# ==========================================================================
# Timer
# ==========================================================================

TIMER_USO = (
    "⏱ Uso:\n"
    "/timer 30\n"
    "/timer 20 ir a comer\n"
    "/timer 60 15 30 terminar informe\n\n"
    "El primer número es la duración total.\n"
    "Luego puedes poner hasta 3 avisos numéricos.\n"
    "Desde la primera palabra, todo se guarda como razón."
)

TIMER_FALTA_DURACION = "Falta la duración. Ejemplo: /timer 20 ir a comer"
TIMER_DURACION_INVALIDA = "Duración inválida. Usa minutos entre 1 y 1440."
TIMER_RAZON_LARGA = "La razón es demasiado larga. Usa máximo 240 caracteres."
TIMER_MUCHOS_AVISOS = (
    "Máximo 3 avisos intermedios. Ejemplo: /timer 60 15 30 45 terminar informe"
)
TIMER_AVISOS_INVALIDOS = (
    "Los avisos deben ser mayores que 0 y menores que la duración total."
)
TIMER_SIN_ACTIVO = "No hay timer activo.\nInicia uno con /timer 30."

# --- las tres modalidades ------------------------------------------------
# Un solo motor. Lo unico que cambia es como se calcula la hora del aviso:
# desde ahora, a una hora fija, o cada tanto. La exclusividad la garantiza
# el esquema (una sola fila), no una regla de codigo.

TIMER_MODOS = {
    "countdown": "⏳ Cuenta atrás",
    "fixed": "🕐 Avisar a",
    "repeating": "🔁 Repetitivo",
}

TIMER_USO_A = (
    "🕐 <b>Avisar a una hora</b>\n\n"
    "Ejemplo: /timer_a 21:40\n\n"
    "Si la hora ya pasó hoy, queda para mañana."
)

TIMER_USO_CADA = (
    "🔁 <b>Aviso repetitivo</b>\n\n"
    "Ejemplo: /timer_cada 50\n\n"
    "Avisa cada 50 minutos hasta que lo detengas."
)

TIMER_HORA_INVALIDA = (
    "Esa hora no se entiende. Usa HH:MM, por ejemplo 21:40."
)

TIMER_INTERVALO_INVALIDO = (
    "Intervalo inválido. Usa minutos entre 1 y 1440."
)

# Reemplazar en silencio hacia lo que ya estaba corriendo es la clase de
# sorpresa que hace desconfiar de un temporizador. Se pregunta.
TIMER_YA_HAY = "⚠️ Ya hay un timer activo."

TIMER_BOTONES_REEMPLAZO = [
    ("🔄 REEMPLAZAR", "/timer_reemplazar"),
    ("✋ CONSERVAR", "/timer_conservar"),
]

# Los avisos del repetitivo llevan lo único que se puede hacer con ellos.
# Antes traían PAUSAR, que para este modo sólo servía para contestar que no
# aplica: un botón cuyo único efecto es decirte que no sirve.
TIMER_BOTONES_REPETITIVO = [("⏹️ DETENER", "/timer_cancelar")]


def timer_repetido_fin(cada: int, duracion: int) -> str:
    """Terminar se avisa. Un repetitivo que se apaga en silencio deja la
    duda de si sigue vivo, y esa duda cuesta más que el aviso."""
    horas = duracion / 60
    tramo = f"{horas:.0f} h" if horas == int(horas) else f"{duracion} min"
    return (
        f"🔁 <b>Dejé de avisar.</b>\n\n"
        f"Eran cada {cada} min, por {tramo}."
    )


def timer_botones_otra_vez(cada: int, duracion: int) -> list:
    """Relanzar igual, en un toque.

    Es lo que permite que el tope sea corto sin costo: la única objeción
    real a un vencimiento es "¿y si terminó cuando todavía lo necesitaba?",
    y se responde haciendo barátisimo volver a empezar.
    """
    return [("🔁 OTRA VEZ", f"/timer_cada {cada} {duracion}"), PANEL_HOME]


TIMER_CONSERVADO = "✋ Se conserva el timer que ya estaba."

TIMER_NADA_QUE_REEMPLAZAR = "No hay ninguna creación esperando respuesta."

TIMER_PAUSA_SOLO_CUENTA = (
    "Pausar sólo aplica a la cuenta atrás.\n\n"
    "Para los otros modos, detén con /timer_cancelar."
)


def timer_creado(modo: str, detalle: str, reemplazo: bool = False) -> str:
    cabeza = "⏱ Timer reemplazado" if reemplazo else "⏱ Timer iniciado"
    return f"{cabeza}\n\nModo: {TIMER_MODOS.get(modo, modo)}\n{detalle}"


def timer_aviso_fijo(hora: str) -> str:
    return f"🔔 <b>Son las {hora}.</b>\n\nEra la hora que pediste."


def timer_aviso_repetido(minutos: int, proximo: str) -> str:
    return (
        f"🔔 <b>Pasaron {minutos} minutos.</b>\n\n"
        f"Siguiente aviso: {proximo}"
    )

TIMER_SIN_CANCELAR = "No hay timer activo para cancelar."
TIMER_CANCELADO = "✖️ Timer cancelado."
TIMER_SIN_SONAR = "No hay timer sonando."
TIMER_AUN_NO_SUENA = (
    "El timer aún no está sonando.\n"
    "Si quieres detenerlo antes de tiempo usa /timer_cancelar."
)
TIMER_APAGADO = "🔕 Timer apagado."
TIMER_AUTOAPAGADO = "⏹ Timer apagado automáticamente tras 6 minutos de alarma."
TIMER_YA_PAUSADO = "El timer ya está pausado."
TIMER_NO_PAUSADO = "El timer no está pausado."
TIMER_SIN_PAUSAR = "No hay timer activo para pausar."
TIMER_SIN_REANUDAR = "No hay timer pausado para reanudar."
TIMER_YA_SONANDO = (
    "El timer ya terminó y está sonando. Usa /apagar para detener la alarma."
)


def timer_razon(reason: str) -> str:
    reason = str(reason or "").strip()
    return f"📝 Razón: {reason}" if reason else ""


# ==========================================================================
# Sistema / panel
# ==========================================================================

PANEL_ADMIN = (
    "⛵ Panel de Mástil\n\n"
    "/reporte — resumen de los últimos 7 días.\n\n"
    "📊 INTERVALOS\n"
    "/marca — registra una marca y muestra la tabla del día.\n"
    "/tiempo — cuánto pasó desde la última marca. No registra nada.\n"
    "/reset — cierra el ciclo actual. La próxima marca empieza de cero.\n"
    "Cada marca abre una espera a ciegas de 1h 16m. Al cumplirse, Mástil\n"
    "envía una secuencia finita de avisos y termina sola.\n\n"
    "⏱ TIMER\n"
    "/timer [minutos] [avisos] [razón]\n"
    "Ejemplos:\n"
    "/timer 30\n"
    "/timer 20 ir a comer\n"
    "/timer 60 15 30 terminar informe\n"
    "/tm — muestra tiempo restante, razón y estado.\n"
    "/timer_pausar — congela el timer y sus avisos.\n"
    "/timer_reanudar — continúa desde donde quedó.\n"
    "/apagar — apaga la alarma cuando el timer está sonando.\n"
    "/timer_cancelar — cancela el timer definitivamente.\n\n"
    "🧭 ESTADO GENERAL\n"
    "/admin — muestra este panel ordenado.\n"
    "/estado — muestra el estado general de Mástil, Calendario y Pomodoro.\n\n"
    "⚡ ACCIÓN RÁPIDA\n"
    "/ok — acepta el freno inicial y activa la tregua.\n"
    "/listo — cierra con éxito el flujo activo. En rescate es la salida principal.\n"
    "/reinicio — reconoce que quedaste pegado y activa rescate o margen de gracia.\n"
    "/descanso — inicia el descanso Pomodoro cuando Mástil exige cortar.\n"
    "/stop — detiene el módulo Pomodoro actual.\n\n"
    "🍅 POMODORO\n"
    "/pomodoro — inicia bloques de 20 minutos.\n"
    "/pomodoro 15 — usa 15 minutos en todos los bloques de esta sesión.\n"
    "/pomodoro [foco] — usa 20 minutos y asigna un nombre al foco.\n"
    "/pomo_estado — consulta el estado del Pomodoro sin alterar timers.\n"
    "/descanso — después del corte, inicia el descanso físico obligatorio.\n"
    "/stop — detiene Pomodoro y limpia su sesión.\n\n"
    "🗓 MÁSTIL CALENDARIO\n"
    "Eventos con ** — activan freno, tregua, chequeo y rescate.\n"
    "/cancelar — cancela el flujo activo de calendario.\n"
    "/reset_estado — limpia el estado interno completo.\n\n"
    "👁 VIGÍA\n"
    "Eventos con ++ — piden foto inicial, duración, presencia y foto de cierre.\n"
    "/vigia_cancelar — suspende la sesión activa de Vigía.\n\n"
    "📬 GMAIL\n"
    "/gmail_hay — cuántos hilos no leídos hay.\n"
    "/gmail_remitentes — lista numerada de remitentes.\n"
    "/gmail_contenido N natural — muestra el correo N.\n"
    "/gmail_contenido N base64 — lo entrega codificado.\n\n"
    "🛠 CONTROL GLOBAL\n"
    "/suspender — suspende todo Mástil sin apagar el servicio.\n"
    "/reanudar — reactiva vigilancia de Calendario, Pomodoro y alertas.\n\n"
    "🧪 PRUEBAS\n"
    "/test_freno — prueba la fase de freno.\n"
    "/test_chequeo — prueba el chequeo con botones.\n"
    "/test_rescate — prueba rescate normal.\n"
    "/test_rescate30 — prueba rescate acelerado.\n"
    "/test_cierre — prueba un mensaje de cierre.\n\n"
    "Idea base: Mástil no castiga. Te da un punto firme para volver cuando el "
    "piloto automático toma el timón."
)

SUSPENDIDO = (
    "⏸ ⛵ Mástil suspendido por completo. No procesaré eventos, Pomodoro ni "
    "rescates hasta que envíes /reanudar."
)

REANUDADO = "▶️ ⛵ Mástil reanudado. Vuelvo a vigilar Calendar, Pomodoro y alertas."

ESTADO_SUSPENDIDO = (
    "Estado de ⛵ Mástil: SUSPENDIDO. Usa /reanudar para volver a activar vigilancia."
)

# --- suspension exclusiva de Guardian ------------------------------------
#
# Apaga sólo Guardian. Los eventos NO se tocan: no se borran, no se resuelven,
# no cambian de hora. Silenciar no es resolver.
#
# Los textos describen sólo el comportamiento del sistema. Nada sobre por qué
# lo suspendiste.

BOTON_SUSPENDER_GUARDIAN = [("⏸️ SUSPENDER GUARDIAN", "/suspender_guardian")]
BOTON_REANUDAR_GUARDIAN = [("▶️ REANUDAR GUARDIAN", "/reanudar_guardian")]

GUARDIAN_SUSPENDIDO_AVISO = (
    "⏸️ Guardian suspendido.\n\n"
    "La agenda sigue funcionando normalmente.\n"
    "Guardian no enviará intervenciones mientras esté suspendido."
)

GUARDIAN_REANUDADO_AVISO = (
    "▶️ Guardian reanudado.\n\n"
    "Vuelve a procesar los eventos según sus reglas normales."
)

GUARDIAN_ESTADO_ACTIVO = "🔴 Guardian activo."
GUARDIAN_ESTADO_SUSPENDIDO = "⏸️ Guardian suspendido."


ESTADO_RESETEADO = "Estado interno reseteado. ⛵ Mástil queda limpio."

# --- sorpresa ------------------------------------------------------------
# Un mensaje puntual que el propietario le manda a la usuaria asistida por Telegram.
# No hay plantillas, ni programación, ni respuesta esperada: escribe y llega.

SORPRESA_USO = "Uso: /sorpresa &lt;mensaje&gt;"

def sorpresa_enviada(nombre: str) -> str:
    """El nombre sale de MASTIL_LITE_USERS, no del código.

    Para cambiar la forma de tratamiento, se edita ahí y listo.
    """
    return f"✅ Sorpresa enviada a {nombre}"

SORPRESA_ERROR = "No pude enviar la sorpresa. Intenta de nuevo."

SORPRESA_SIN_DESTINO = (
    "No hay ninguna usuaria configurada para recibirla."
)


def sorpresa(texto: str) -> str:
    return f"⚓✨ Sorpresa de Mástil\n\n{texto}"


def guardian_cerrado(tarea: str) -> str:
    """Lo primero que se lee al cerrar: QUE se cerro.

    La medalla viene despues. Sin esta linea, diez minutos mas tarde el
    chat no dice que quedo resuelto.
    """
    return f"✅ Cerrado: {esc(tarea)}"


ARRANQUE = (
    "⛵ Mástil iniciado. Calendario + Pomodoro + Timer activos. "
    "Usa /admin para ver comandos."
)


# ==========================================================================
# Mástil Lite — para la usuaria asistida. Todo en HTML, letra grande, sin jerga técnica.
# ==========================================================================

def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=False)


LITE_AYUDA = (
    "<b>No entendí eso.</b>\n\n"
    "Escribe <b>recordar</b> y yo te voy preguntando lo demás.\n\n"
    "También puedes escribirlo todo de una vez, así:\n"
    "<code>recordar hoy 21:30 bañarme</code>"
)

LITE_BIENVENIDA = (
    "<b>Hola.</b>\n\n"
    "Para crear un recordatorio escribe <b>recordar</b>.\n"
    "Yo te voy preguntando lo demás, de a una cosa por vez.\n\n"
    "Para ver los que ya tienes, escribe <b>recuérdame</b>."
)

LITE_SIN_PENDIENTES = "<b>No tienes recordatorios pendientes.</b>"
LITE_CODIGO_NO_ENCONTRADO = "<b>No encontré una alarma activa con ese número.</b>"
LITE_APAGADO = "<b>Listo, apagué este recordatorio.</b>"
LITE_DETENIDO = "Detengo este recordatorio por ahora."
LITE_PAUSADO = "Tus recordatorios fueron pausados temporalmente."
LITE_REANUDADO = "Tus recordatorios vuelven a estar activos."


def lite_creado(display_date: str, display_time: str, activity: str) -> str:
    return (
        "<b>Listo. Creé tu recordatorio.</b>\n\n"
        f"📅 <b>Fecha:</b> <b>{esc(display_date)}</b>\n"
        f"🕘 <b>Hora:</b> <b>{esc(display_time)}</b>\n\n"
        "🔔 <b>Recordatorio:</b>\n"
        f"<b>{esc(activity)}</b>"
    )


def lite_alerta(activity: str) -> str:
    return (
        "<b>🔔 RECORDATORIO</b>\n\n"
        f"<b>{esc(activity)}</b>\n\n"
        "Escribe el número grande de la imagen para apagar la alarma."
    )


def lite_listado(items: list[tuple[str, str, str]]) -> str:
    lines = ["<b>Tus recordatorios:</b>\n"]
    for index, (fecha, hora, activity) in enumerate(items, 1):
        lines.append(
            f"<b>{index}.</b> 📅 <b>{esc(fecha)}</b> 🕘 <b>{esc(hora)}</b>\n"
            f"🔔 <b>{esc(activity)}</b>"
        )
    return "\n\n".join(lines)


# --- flujo guiado: una pregunta por mensaje -------------------------------
#
# La puerta de entrada y la de salida son siempre la misma palabra: «recordar».
# Nunca hay que memorizar un formato: el sistema pregunta, ella contesta.
#
# Sigue sin haber botones ni menús, igual que antes.

LITE_GUIA_ACTIVIDAD = (
    "<b>¿Qué quieres que te recuerde?</b>\n\n"
    "Escríbelo con tus palabras.\n\n"
    "<i>Si no quieres seguir, escribe: nada</i>"
)

LITE_GUIA_DIA = (
    "<b>¿Qué día?</b>\n\n"
    "Escribe <b>hoy</b>, <b>mañana</b>, o la fecha: <b>9 de agosto</b>."
)

LITE_GUIA_DIA_OTRA_VEZ = (
    "<b>No entendí el día.</b>\n\n"
    "Escribe <b>hoy</b>, <b>mañana</b>, o la fecha: <b>9 de agosto</b>."
)

LITE_GUIA_HORA = "<b>¿A qué hora?</b>\n\nPor ejemplo: <b>9:30</b>."

LITE_GUIA_HORA_OTRA_VEZ = (
    "<b>No entendí la hora.</b>\n\n"
    "Escríbela con números. Por ejemplo: <b>9:30</b>."
)

LITE_GUIA_HORA_PASADA = (
    "<b>Esa hora de hoy ya pasó.</b>\n\n"
    "Dime otra hora, o escribe <b>mañana</b> y lo dejamos para mañana."
)

LITE_GUIA_FRANJA = "<b>¿De la mañana o de la tarde?</b>"

LITE_GUIA_MANANA = "<b>Bueno, mañana.</b>\n\n¿A qué hora?"

LITE_GUIA_CANCELADO = (
    "<b>Listo, no guardé nada.</b>\n\n"
    "Cuando quieras, escribe <b>recordar</b>."
)

LITE_GUIA_CONFIRMA_OTRA_VEZ = "Responde <b>sí</b> o <b>no</b>."

# Cierre del flujo guiado: termina ofreciendo la misma puerta por la que entró.
LITE_INVITACION = "\n\n———\nPara crear otro, escribe <b>recordar</b>."


def lite_guia_confirmar(display_date: str, display_time: str, activity: str) -> str:
    return (
        "<b>¿Está bien así?</b>\n\n"
        f"📅 <b>Fecha:</b> <b>{esc(display_date)}</b>\n"
        f"🕘 <b>Hora:</b> <b>{esc(display_time)}</b>\n\n"
        "🔔 <b>Recordatorio:</b>\n"
        f"<b>{esc(activity)}</b>\n\n"
        "Responde <b>sí</b> o <b>no</b>."
    )


# --- avisos al propietario: sólo el hecho, nunca el contenido -------------

def lite_aviso_creado(nombre: str) -> str:
    return f"{nombre} creó exitosamente un recordatorio."


def lite_aviso_invalido(nombre: str) -> str:
    return f"{nombre} intentó crear un recordatorio, pero el formato no fue válido."


def lite_aviso_sin_confirmar(nombre: str) -> str:
    return f"{nombre} no confirmó un recordatorio."


# ==========================================================================
# Vigía — eventos ++
# ==========================================================================

VIGIA_PRESENCIA = [
    "Aquí estoy. Suelta los hombros, respira y vuelve al siguiente micro-movimiento.",
    "Pausa somática: nota tus pies en el suelo, toca un elemento de tu tarea y continúa a tu ritmo.",
    "El andamio te sostiene. No tienes que terminarlo todo hoy, solo quédate un ratito más en este espacio.",
    "Siente tu respiración. Ubica tu cuerpo físicamente frente a la tarea y da el siguiente paso visible, por pequeño que sea.",
    "Mástil te acompaña. No buscamos perfección, buscamos presencia y un movimiento a la vez.",
    "Haz que tu cuerpo lidere. Un movimiento simple antes de que tu mente empiece a poner peros.",
]

VIGIA_FOTO_INICIAL = [
    "Anclamos el presente. Mándame una foto rápida de tu espacio tal como está ahora para marcar el punto de partida.",
    "Comenzamos sin prisa. Registra tu punto de inicio con una foto sencilla de tu entorno actual.",
    "El primer paso es solo mirar. Toma una foto del escenario tal como está hoy para empezar a construir el andamio.",
]

VIGIA_FOTO_EXTRA = [
    "Un anclaje más: envíame una foto rápida del entorno para cerrar la sesión con total claridad.",
    "Mástil te pide un registro de contexto extra esta vez. Una toma rápida más de tu alrededor y sellamos el bloque.",
    "Sincronización final: toma una última foto rápida de tu espacio actual para redondear el registro.",
]

VIGIA_RESCATE = [
    "El andamio sigue abierto esperando tu registro. Regresa al presente un segundo y mándame la foto.",
    "Mantenemos la pausa activa porque falta la imagen. Saca la foto rápida y liberamos el bloque.",
    "Rompe la inercia con un micro-movimiento: toma la foto ahora para cerrar este ciclo de forma consciente.",
]

VIGIA_EXITO = [
    "Ciclo cerrado. Estuviste presente, te moviste y completaste el andamio. Buen trabajo.",
    "Bloque asegurado. Tu esfuerzo y presencia quedaron registrados de forma limpia.",
    "Perfecto. Mástil archiva este bloque como completado. Puedes soltar la tarea con tranquilidad.",
]


def fmt_event(title: str) -> str:
    return f"⚓ [{title}]"


def vigia_instruccion_inicio(activity_type: str) -> str:
    if activity_type == "cocina":
        return (
            "Foto de inicio: registra tus herramientas o ingredientes en la mesa. "
            "Un ritual simple antes de encender el fuego."
        )
    if activity_type == "acumulacion":
        return (
            "Foto de inicio: registra la acumulación actual. No la juzgues, solo mírala y "
            "sácale una foto para ver desde dónde partimos."
        )
    if activity_type == "cambio_visible":
        return (
            "Foto de inicio: encuadra el espacio actual. "
            "Esto es solo un registro del punto de origen."
        )
    return "Foto de inicio: captura el estado actual de la tarea. Empezamos desde donde estás."


def vigia_instruccion_cierre(activity_type: str) -> str:
    if activity_type == "cocina":
        return (
            "Llegamos al final del tiempo. Envíame una foto de cierre para registrar lo avanzado: "
            "plato listo, mesa servida o el avance que hayas logrado."
        )
    if activity_type == "acumulacion":
        return (
            "Bloque completado. Envíame una foto de cierre que muestre el espacio más despejado. "
            "Cualquier reducción es una victoria."
        )
    if activity_type == "cambio_visible":
        return (
            "Hora de cerrar. Captura el escenario actual para registrar la diferencia visible "
            "frente al punto de inicio."
        )
    return (
        "Tiempo cumplido. Envíame una foto sencilla que registre tu avance. "
        "Marcamos el límite consciente del bloque aquí."
    )


def vigia_rechazo_final(activity_type: str) -> str:
    if activity_type == "cocina":
        return (
            "Hagamos zoom en el resultado. La cámara no captó bien el plato o el avance. "
            "Saca una foto más de cerca para registrar tu logro."
        )
    if activity_type == "acumulacion":
        return (
            "Registremos mejor ese despeje. Muestra una toma más clara de la zona trabajada. "
            "Queremos dejar constancia de tu esfuerzo."
        )
    if activity_type == "cambio_visible":
        return (
            "Aseguremos la comparación visual. "
            "Intenta con otra toma que capture el cambio real frente al inicio."
        )
    return (
        "Démosle un cierre más nítido. Toma una última foto donde se note el avance "
        "del bloque para poder archivar este evento."
    )


VIGIA_RECHAZO_INICIO = (
    "Vamos a reajustar el enfoque. La cámara no alcanzó a registrar bien el espacio. "
    "Intenta con una toma más nítida o con mejor luz."
)

VIGIA_RECHAZO_EXTRA = (
    "La imagen salió un poco borrosa. Regálame una última toma clara para poder "
    "cerrar el andamio por hoy."
)

VIGIA_PEDIR_DURACION = (
    "Y ahora, regálale un marco de tiempo a este bloque. "
    "Escribe la duración estimada en minutos (ej: 20)."
)

VIGIA_INICIO_REGISTRADO = (
    "Punto de partida registrado con éxito. ¿Cuánto tiempo le asignamos a este bloque? "
    "Escribe los minutos (ej: 20)."
)

VIGIA_CODIGO_PRIMERO = (
    "Validación completada con éxito. "
    "Escribe el número que ves en pantalla dos veces para sellar el registro."
)

VIGIA_CODIGO_SEGUNDO = (
    "Primer paso del sello listo. Escríbelo una vez más para terminar de cerrar el bloque."
)

VIGIA_CODIGO_MAL = (
    "Hubo un pequeño error al leer el número. Míralo con calma e ingrésalo de forma manual."
)

VIGIA_CODIGO_SEGUNDO_MAL = (
    "El segundo código no coincidió. Escribe el mismo número una vez más para completar el sello."
)

# Acuse inmediato. Bajar la foto y consultarle a Vision toma varios segundos,
# y el silencio se lee como que la foto no llegó.
VIGIA_FOTO_RECIBIDA = "📷 Recibida. Revisando…"

VIGIA_SIN_ESPACIO = "En este momento no hay un espacio abierto para recibir fotos."
VIGIA_FUERA_DE_FASE = "En este momento no estamos en fase de registro visual."
VIGIA_SIN_SESION = "No tenemos ninguna sesión activa de Vigía en este momento."
VIGIA_SUSPENDIDA = "Sesión de Vigía suspendida."


def vigia_bloque_iniciado(minutos: int, hora_fin: str, pings: int) -> str:
    return (
        f"Bloque iniciado. Tenemos {minutos} minutos de juego.\n"
        f"Estaremos cerrando cerca de las {hora_fin}.\n\n"
        f"Iré apareciendo en el camino con {pings} pings de presencia "
        "para ayudarte a volver aquí si te dispersas."
    )


def vigia_tiempo_reservado(minutos: int) -> str:
    return (
        f"Tiempo reservado: {minutos} minutos. "
        "Ahora, aseguremos el presente con tu foto de inicio."
    )


VIGIA_CODIGO_CAPTION = "Código de cierre"
VIGIA_CODIGO_PIE = "Escríbelo dos veces en Telegram."


# ==========================================================================
# Gmail
# ==========================================================================

GMAIL_AYUDA = (
    "📬 Gmail en Mástil\n\n"
    "/gmail_hay\n"
    "/gmail_remitentes\n"
    "/gmail_contenido N natural\n"
    "/gmail_contenido N base64\n\n"
    "Nota: /gmail_asuntos fue retirado para evitar exposición innecesaria."
)

GMAIL_ASUNTOS_RETIRADO = (
    "📬 /gmail_asuntos fue retirado para evitar exposición innecesaria.\n\n"
    "Usa /gmail_remitentes y luego:\n"
    "/gmail_contenido N base64\n"
    "/gmail_contenido N natural"
)

# Acuse inmediato: la consulta al Apps Script puede tardar varios segundos.
GMAIL_CONSULTANDO = "📬 Consultando…"

GMAIL_SIN_NO_LEIDOS = "📬 Gmail\nNo hay correos no leídos recientes."
GMAIL_NUMERO_NO_ENCONTRADO = (
    "No encontré ese número. Primero usa /gmail_remitentes."
)
GMAIL_DESHABILITADO = (
    "📬 Gmail no está configurado en esta instalación."
)


# ==========================================================================
# Intervalos — cronómetro de vueltas
# ==========================================================================
# Registra horas y calcula cuánto pasó entre una y otra. Nada más.
#
# Este módulo no tiene tono. No felicita, no advierte, no compara con días
# anteriores ni menciona rachas. Cualquier frase de aliento acá convertiría
# un instrumento en un juez.

INTERVALOS_TITULO = "📊 MARCAS DEL CICLO"
INTERVALOS_INICIO = "Inicio"
INTERVALOS_SIN_MARCAS = "No hay marcas en el ciclo actual."


def intervalos_marca_borrada(resumen: str) -> str:
    return f"🗑️ Borré la marca {resumen}."


INTERVALOS_BORRAR_SIN_MARCAS = (
    "No hay ninguna marca que borrar en el ciclo actual."
)


def intervalos_ocultas(cantidad: int) -> str:
    return f"(Se ocultaron {cantidad} marcas anteriores)"


def intervalos_registrada(numero: int, tramo: str | None = None) -> str:
    """La negrita va acá, fuera del cuadro.

    Telegram ignora cualquier formato dentro de un bloque monoespaciado: o el
    cuadro queda alineado, o se puede destacar una fila, nunca las dos cosas.
    Así que el dato que importa —el último tramo— se repite abajo, donde sí
    puede resaltarse.
    """
    if tramo:
        return f"📍 Marca #{numero} · último tramo <b>{tramo}</b>"
    return f"📍 Marca #{numero} registrada."


def intervalos_desde_ultima(duracion: str, numero: int) -> str:
    return f"⏱ <b>{duracion}</b> desde la marca #{numero}."


INTERVALOS_SIN_CICLO = "No hay ningún ciclo abierto."

# Para no tener que escribir el comando cada vez. /reset queda fuera a
# propósito: cerrar el ciclo es deliberado, no algo que deba pasar por un
# dedo mal apoyado.
INTERVALOS_BOTONES = [("📍 Marca", "/marca"), ("⏱ Tiempo", "/tiempo")]

INTERVALOS_CONTEXTO_PREGUNTA = "🧩 ¿Qué estaba pasando?"
INTERVALOS_CONTEXTO_OTRO = "✏️ Escribe el contexto brevemente."
INTERVALOS_CONTEXTO_GUARDADO = "✅ Contexto guardado."
INTERVALOS_CONTEXTO_EXPIRADO = "Este contexto ya no está disponible. La marca quedó guardada."


def intervalos_contexto_botones(mark_id: int):
    """Los callbacks llevan el id para que un botón viejo jamás toque otra marca."""
    return [
        [("😣 ESTRÉS / EMOCIÓN", f"/contexto estres {mark_id}")],
        [("⚡ URGENCIA ALTA", f"/contexto urgencia {mark_id}")],
        [("💤 SUEÑO / CANSANCIO", f"/contexto sueno_cansancio {mark_id}")],
        [("🕳️ ABURRIMIENTO / TIEMPO MUERTO", f"/contexto aburrimiento {mark_id}")],
        [("📍 CONTEXTO / SEÑAL", f"/contexto senal {mark_id}")],
        [
            ("✏️ OTRO", f"/contexto otro {mark_id}"),
            ("↩️ SIN CONTEXTO", f"/contexto sin {mark_id}"),
        ],
    ]


INTERVALOS_AVISO = "⏱ Intervalo cumplido."

def intervalos_ciclo_cerrado(marcas: int, total: str) -> str:
    """Sólo el hecho de lo que se cerró. Sin balance ni comentario."""
    return (
        "🔄 Ciclo cerrado.\n\n"
        f"{marcas} marcas · total <b>{total}</b>\n\n"
        "La próxima /marca empieza de cero."
    )


# ==========================================================================
# Panel — botonera inline
# ==========================================================================
# Es una segunda forma de invocar lo que ya existe, no una capa nueva de
# comportamiento. Por eso los botones de acción llevan como `callback_data` el
# comando literal: el router ya sabe despacharlo y la lógica sigue viviendo en
# un solo lugar. El prefijo `panel:` queda reservado para lo único que los
# comandos no saben hacer: navegar editando el mismo mensaje y pedir un dato.

PANEL_HOME = ("🏠 PANEL", "panel:home")

# Lo que queda en la pantalla vieja cuando el panel se mueve al final de
# la conversacion. Sin botones: un menu viejo que todavia responde contesta
# lejos de donde estas mirando, y eso es la mitad del desorden.
PANEL_APAGADO = "⚓ MÁSTIL · el panel siguió abajo ↓"

PANEL_TITULO = "⚓ MÁSTIL"

PANEL_BOTONES = [
    [("⏱️ INTERVALOS", "panel:intervalos"), ("📅 CALENDARIO", "panel:calendar")],
    [("⏲️ TIMER", "panel:timer"), ("🍅 POMODORO", "panel:pomodoro")],
    [("📬 GMAIL", "panel:gmail"), ("⚙️ SISTEMA", "panel:system")],
    [("👁️ VIGÍA", "panel:vigia")],
]

# --- Vigía ---------------------------------------------------------------
# Tres accesos y nada más. La foto sigue siendo el punto de reentrada: acá
# sólo está lo que no se puede hacer mandando una imagen.

PANEL_VIGIA_TITULO = "👁️ VIGÍA"

PANEL_VIGIA_BOTONES = [
    [("🎯 NUEVA TAREA", "panel:vig:objetivo")],
    [("▶️ REANUDAR BLOQUE", "/vigia_bloque")],
    [("📋 CONTEXTO", "panel:vig:ctx"), ("🆘 ME TRABÉ", "/vigia_trabado")],
    [("✖️ CANCELAR OBJETIVO", "panel:vig:cancelar")],
    [PANEL_HOME],
]

PANEL_VIGIA_OBJETIVO = "🎯 ¿Qué quieres hacer?"

# --- contexto mínimo -----------------------------------------------------
# Los cuatro campos son opcionales y se ven en su propio botón cuando están
# llenos. No es un cuestionario: si el objetivo y la foto alcanzan, se pasa
# directo a la foto sin tocar ninguno.

PANEL_VIG_CTX_CAMPOS = (
    ("alcance", "📍 ALCANCE", "panel:vig:ctx:alcance", "📍 ¿Hasta dónde llega? (alcance)"),
    ("prioridad", "⭐ PRIORIDAD", "panel:vig:ctx:prioridad", "⭐ ¿Qué es lo más importante?"),
    ("elementos", "📦 ELEMENTOS", "panel:vig:ctx:elementos", "📦 ¿Qué elementos hay en juego?"),
    ("restricciones", "🚫 RESTRICCIONES", "panel:vig:ctx:restricciones", "🚫 ¿Qué NO se puede hacer?"),
)

PANEL_VIG_SIN_TAREA = "No hay ninguna tarea en curso. Empieza con 🎯 NUEVA TAREA."


def panel_vigia_contexto(objetivo: str, contexto: dict) -> str:
    # Texto plano, sin <b> ni escapes: las pantallas del Panel se envían sin
    # parse_mode, así que cualquier etiqueta se vería literal.
    return (
        "📋 CONTEXTO\n\n"
        f"🎯 {objetivo}\n\n"
        "Rellena sólo lo que pueda cambiar el plan. Cuando estés listo, manda la foto."
    )


def panel_vigia_contexto_botones(contexto: dict):
    """Cada campo lleno se muestra en su botón, como el rango del reporte."""
    filas = []
    pares = []
    for clave, etiqueta, callback, _ in PANEL_VIG_CTX_CAMPOS:
        valor = (contexto or {}).get(clave) or ""
        corto = valor if len(valor) <= 18 else valor[:17] + "…"
        pares.append((f"{etiqueta}{f': {corto}' if corto else ''}", callback))
        if len(pares) == 2:
            filas.append(pares)
            pares = []
    if pares:
        filas.append(pares)
    filas.append([("📸 MANDAR FOTO", "panel:vig:foto")])
    filas.append([PANEL_HOME])
    return filas


PANEL_VIG_FOTO = (
    "📸 Manda la foto ahora.\n\n"
    "Es el estado actual del entorno, no una prueba de nada."
)

PANEL_VIG_FOTO_BOTONES = [
    [("↩️ VOLVER AL CONTEXTO", "panel:vig:ctx")],
    [PANEL_HOME],
]

# --- cuántas fotos ------------------------------------------------------
#
# El análisis se dispara al llegar la foto, así que hay que saber ANTES si
# viene una sola o si conviene esperar la segunda. La pregunta es operativa
# —cuántas vas a mandar—, no una evaluación de qué tan difícil está: eso
# último sería pedir criterio justo frente al desorden que lo impide.

PANEL_VIG_CUANTAS = (
    "📸 ¿Cuántas fotos vas a mandar?\n\n"
    "Con dos ángulos del mismo lugar se entiende mejor un escenario cargado. "
    "Cuestan lo mismo: van juntas en una sola consulta."
)

PANEL_VIG_CUANTAS_BOTONES = [
    [("1️⃣ UNA FOTO", "panel:vig:foto:1")],
    [("2️⃣ DOS FOTOS", "panel:vig:foto:2")],
    [("↩️ VOLVER AL CONTEXTO", "panel:vig:ctx")],
    [PANEL_HOME],
]

PANEL_VIG_FOTO_PRIMERA = (
    "📸 Manda la primera de las dos.\n\n"
    "Cuando llegue te pido la segunda. Recién ahí se analizan, juntas."
)

VIGIA_PRIMERA_RECIBIDA = (
    "📸 Primera recibida. Manda la segunda, desde otro ángulo.\n\n"
    "Todavía no analizo nada: espero las dos."
)

# Cancelar borra objetivo, estrategia y bloque. Un toque accidental no debería
# poder hacerlo, igual que con el /reset de Intervalos.
PANEL_VIGIA_CANCELAR = "✖️ ¿Cerrar el objetivo en curso?"

PANEL_VIGIA_CANCELAR_BOTONES = [
    [("✅ CERRAR OBJETIVO", "panel:vig:cancelar:ok")],
    [("↩️ VOLVER", "panel:vigia")],
]

# --- Intervalos ----------------------------------------------------------

PANEL_INTERVALOS_TITULO = "⏱️ INTERVALOS"

PANEL_INTERVALOS_BOTONES = [
    [("📍 MARCA", "/marca")],
    [("🧩 MARCAR + CONTEXTO", "/marca_contexto")],
    [("⌛ TIEMPO", "/tiempo")],
    [("🔄 RESET", "panel:int:reset"), ("📊 REPORTE", "panel:int:reporte")],
    [PANEL_HOME],
]

# --- Reporte de Intervalos ----------------------------------------------
# Exporta a Excel lo que Intervalos ya muestra. No agrega ninguna métrica: si
# no está en la tabla de Telegram, no está en el archivo.

REPORTE_TITULO = "📊 REPORTE DE INTERVALOS"

REPORTE_XLSX_TITULO = "📊 MARCAS DE INTERVALOS"

REPORTE_SIN_DATOS_DIA = "Sin datos"

REPORTE_PIDE_DESDE = "📅 ¿Desde qué fecha? (DD/MM/AAAA)"
REPORTE_PIDE_HASTA = "📅 ¿Hasta qué fecha? (DD/MM/AAAA)"

REPORTE_FECHA_INVALIDA = "No entendí la fecha. Escríbela así: 01/08/2026"
REPORTE_FALTA_RANGO = "Elige primero DESDE y HASTA."
REPORTE_RANGO_INVERTIDO = "La fecha DESDE tiene que ser anterior o igual a HASTA."
REPORTE_SIN_DATOS = "📊 No hay datos de Intervalos en ese período."
REPORTE_ERROR = "No pude generar el reporte. Intenta de nuevo."


def reporte_botones(desde: str | None, hasta: str | None):
    """Las fechas ya elegidas se ven en el propio botón: una pantalla, sin
    mensajes extra que digan lo que el teclado ya está diciendo."""
    return [
        [(f"📅 DESDE{f': {desde}' if desde else ''}", "panel:rep:desde")],
        [(f"📅 HASTA{f': {hasta}' if hasta else ''}", "panel:rep:hasta")],
        [("📥 EXPORTAR EXCEL", "panel:rep:exportar")],
        [PANEL_HOME],
    ]


def reporte_listo(desde: str, hasta: str, archivo: str) -> str:
    return (
        "✅ Reporte de Intervalos generado.\n\n"
        f"📅 {esc(desde)} → {esc(hasta)}\n"
        f"📄 {esc(archivo)}"
    )

# /reset cierra el ciclo en curso. Un toque accidental no debería poder
# hacerlo, así que acá —y sólo acá— el panel agrega una confirmación.
# Borrar la ultima marca. Se nombra por numero y tramo porque asi es como
# se la mira en la tabla: horas de reloj no aparecen en ningun lado.

def panel_borrar_marca(resumen: str) -> str:
    return f"🗑️ ¿Borrar la marca {resumen}?"


PANEL_BORRAR_MARCA_BOTONES = [
    [("✅ BORRAR", "panel:sys:borrar:ok")],
    [("↩️ VOLVER", "panel:system")],
]

PANEL_BORRAR_SIN_MARCAS = "🗑️ No hay ninguna marca en el ciclo actual."

PANEL_INTERVALOS_RESET = "🔄 ¿Cerrar el ciclo actual?"

PANEL_INTERVALOS_RESET_BOTONES = [
    [("✅ CERRAR CICLO", "panel:int:reset:ok")],
    [("↩️ VOLVER", "panel:intervalos")],
]

# --- Calendario ----------------------------------------------------------

PANEL_CALENDAR_TITULO = "📅 CALENDARIO"

PANEL_CALENDAR_BOTONES = [
    [("☀️ HOY", "panel:cal:hoy"), ("🌅 MAÑANA", "panel:cal:manana")],
    [("📆 OTRO DÍA", "panel:cal:otro")],
    [PANEL_HOME],
]

# La razón se pide y se guarda literal: `**` y `++` los escribe la persona y
# el panel no los toca. Lo único que resuelve el botón es el día.
PANEL_CAL_RAZON = "📝 ¿Razón?"
PANEL_CAL_FECHA = "📆 ¿Fecha? (DD/MM)"
PANEL_CAL_HORA = (
    "🕘 ¿Hora?\n\n"
    "Ejemplos: 9:30 · 1:30 p · 21:30\n"
    "Si no aclaras a (am) o p (pm), te pregunto."
)

PANEL_CAL_AMPM = "🕘 ¿AM o PM?"

PANEL_CAL_AMPM_BOTONES = [
    [("🌅 AM", "panel:cal:am"), ("🌆 PM", "panel:cal:pm")],
    [PANEL_HOME],
]

PANEL_CAL_SIN_CERO = (
    "🕘 Las 00 no se usan.\n\n"
    "La medianoche se escribe 12 a. ¿Hora?"
)

PANEL_CAL_HORA_INVALIDA = (
    "🕘 No entendí esa hora.\n\n"
    "Ejemplos: 9:30 · 1:30 p · 21:30"
)

# --- Timer ---------------------------------------------------------------

PANEL_TIMER_TITULO = "⏲️ TIMER"

# La pantalla del timer se arma sola segun lo que haya corriendo: no tiene
# sentido ofrecer PAUSAR cuando no hay nada, ni tres modalidades cuando ya hay
# un timer andando y lo unico honesto es detenerlo o dejarlo.
PANEL_TIMER_MODOS = [
    [("⏳ CUENTA ATRÁS", "panel:tm:cuenta")],
    [("🕐 AVISAR A", "panel:tm:hora")],
    [("🔁 REPETITIVO", "panel:tm:cada")],
    [PANEL_HOME],
]


def panel_timer_botones(timer=None) -> list:
    """Sin timer, las tres modalidades. Con timer, primero cómo salir de él."""
    if not timer or not timer["active"]:
        return PANEL_TIMER_MODOS

    estado = timer["status"]
    if estado == "ringing":
        salida = [[("🔕 APAGAR", "/apagar")]]
    elif estado == "paused":
        salida = [[("▶️ REANUDAR", "/timer_reanudar"),
                   ("⏹️ DETENER", "/timer_cancelar")]]
    elif (timer["modo"] or "countdown") == "countdown":
        salida = [[("⏸️ PAUSAR", "/timer_pausar"),
                   ("⏹️ DETENER", "/timer_cancelar")]]
    else:
        # Pausar una hora fija no significa nada, y pausar un repetitivo es
        # detenerlo. Se ofrece lo unico que se puede hacer.
        salida = [[("⏹️ DETENER", "/timer_cancelar")]]

    return salida + [[("↻ CAMBIAR POR OTRO", "panel:tm:modos")], [PANEL_HOME]]


PANEL_TIMER_SIN_ACTIVO = "⏲️ TIMER\n\n🟢 No hay timer activo."


def panel_timer_activo(resumen: str) -> str:
    return f"⏲️ TIMER\n\n🟡 {resumen}"


# --- cuenta atras ---------------------------------------------------------
PANEL_TIMER_CUENTA = "⏳ CUENTA ATRÁS\n\n¿Dentro de cuánto?"

PANEL_TIMER_CUENTA_BOTONES = [
    [("5 MIN", "/timer 5"), ("10 MIN", "/timer 10"), ("15 MIN", "/timer 15")],
    [("20 MIN", "/timer 20"), ("30 MIN", "/timer 30"), ("45 MIN", "/timer 45")],
    [("60 MIN", "/timer 60"), ("90 MIN", "/timer 90")],
    [("✏️ OTRO", "panel:tm:otro")],
    [("⚙️ CON AVISOS Y RAZÓN", "panel:tm:config")],
    [("⬅️ VOLVER", "panel:timer")],
]

# --- avisar a -------------------------------------------------------------
# Sin atajos de hora a proposito: una hora util es cualquiera, y seis botones
# con horas redondas serian seis botones que casi nunca sirven.
#
# Pide la hora directo, con la misma lectura que el Calendario: reloj de 12
# con `a`/`p`, y si no se aclara, pregunta AM o PM. Un aviso temprano puede
# caer a la misma hora de la mañana o de la noche: adivinar ahí es avisar doce
# horas corrido.
PANEL_TIMER_PIDE_HORA = (
    "🕐 Pon la hora del aviso.\n\n"
    "Ejemplos: 7 · 7:30 a · 1 p · 21:40\n"
    "Si no aclaras a (am) o p (pm), te pregunto.\n"
    "Si esa hora ya pasó hoy, queda para mañana."
)

# --- repetitivo -----------------------------------------------------------
PANEL_TIMER_CADA = "🔁 REPETITIVO\n\n¿Cada cuánto?"

PANEL_TIMER_CADA_BOTONES = [
    [("CADA 15", "panel:tm:cada:15"), ("CADA 25", "panel:tm:cada:25")],
    [("CADA 30", "panel:tm:cada:30"), ("CADA 45", "panel:tm:cada:45")],
    [("CADA 50", "panel:tm:cada:50"), ("CADA 60", "panel:tm:cada:60")],
    [("CADA 90", "panel:tm:cada:90"), ("✏️ OTRO", "panel:tm:cada:otro")],
    [("⬅️ VOLVER", "panel:timer")],
]

# Segundo paso: por cuánto rato. Se decide acá, al crearlo, porque acá es
# donde sabes qué vas a hacer. Tres horas después, cuando llegara una
# pregunta, ya no te acordas ni por qué lo pusiste.
#
# No hay opción "para siempre": lo que no puede terminar solo termina siendo
# ruido, y el ruido enseña a ignorar el sistema entero.
TIMER_JORNADA_MINUTOS = 1440


def panel_timer_duracion(cada: int) -> str:
    return f"🔁 REPETITIVO · cada {cada} min\n\n¿Por cuánto rato?"


def panel_timer_duracion_botones(cada: int) -> list:
    return [
        [("1 HORA", f"/timer_cada {cada} 60"),
         ("2 HORAS", f"/timer_cada {cada} 120")],
        [("4 HORAS", f"/timer_cada {cada} 240"),
         ("LA JORNADA", f"/timer_cada {cada} {TIMER_JORNADA_MINUTOS}")],
        [("⬅️ VOLVER", "panel:tm:cada")],
    ]

PANEL_TIMER_PIDE_CADA = "🔁 ¿Cada cuántos minutos?"

PANEL_TIMER_OTRO = (
    "✏️ ¿Cuánto?\n\n"
    "Minutos: 7\n"
    "Minutos y segundos: 7:10"
)


def _duracion_nombre(segundos: int) -> str:
    """Como se nombra la duracion pedida: `10 minutos`, `1 minuto`, `4:20 minutos`.

    Redondo se dice en minutos; con segundos se dice como se escribio,
    para que lo que ves sea lo que pediste. La comparten el anuncio de
    inicio y el de fin, para que los dos la digan igual.
    """
    if segundos % 60 == 0:
        minutos = segundos // 60
        return f"{minutos} minuto{'s' if minutos != 1 else ''}"
    return f"{segundos // 60}:{segundos % 60:02d} minutos"


def timer_duracion(segundos: int) -> str:
    """La duracion en el anuncio de inicio."""
    return f"{_duracion_nombre(segundos)}."


def timer_terminado(segundos: int) -> str:
    """El aviso de fin de la cuenta atras, con la duracion que tenia.

    "Timer terminado" a secas no decia cual: con varios en el dia, o uno
    largo, no se sabia que era lo que habia terminado. Sin una duracion
    confiable se dice como antes, en vez de inventar una.
    """
    if not segundos or segundos <= 0:
        return "⏰ Timer terminado."
    return f"⏰ Timer de {_duracion_nombre(segundos)} terminado."
PANEL_TIMER_CONFIG_MINUTOS = "⏲️ ¿Cuántos minutos?"

PANEL_TIMER_AVISOS = "🔔 ¿Avisos?"
PANEL_TIMER_AVISOS_BOTONES = [
    [("🔕 SIN AVISOS", "panel:tm:avisos:no")],
    [("✏️ ESCRIBIR AVISOS", "panel:tm:avisos:si")],
    [PANEL_HOME],
]
# El formato es el que /timer ya acepta; el panel no inventa uno nuevo.
PANEL_TIMER_AVISOS_PIDE = "🔔 Escribe los avisos (hasta 3 números, separados por espacio):"

PANEL_TIMER_RAZON = "📝 ¿Razón?"
PANEL_TIMER_RAZON_BOTONES = [
    [("🚫 SIN RAZÓN", "panel:tm:razon:no")],
    [("✏️ ESCRIBIR RAZÓN", "panel:tm:razon:si")],
    [PANEL_HOME],
]
PANEL_TIMER_RAZON_PIDE = "📝 Escribe la razón:"

# --- Pomodoro ------------------------------------------------------------

PANEL_POMODORO_TITULO = "🍅 POMODORO"


def panel_pomodoro_titulo(trabajo: int, descanso: int) -> str:
    """La pantalla dice la duracion vigente y lo que sugiere para el corte.

    Sin HTML: el Panel encola sin `parse_mode`.
    """
    return (
        f"{PANEL_POMODORO_TITULO}\n\n"
        f"⏱️ Trabajo: {trabajo} min\n"
        f"🧘 Descanso recomendado: {descanso} min"
    )

PANEL_POMODORO_BOTONES = [
    [("▶️ INICIAR", "/pomodoro")],
    [("⏱️ 15 MIN", "/pomodoro 15"), ("✏️ OTRO TIEMPO", "panel:pomo:otro")],
    [("🎯 CON FOCO", "panel:pomo:foco")],
    [("📊 ESTADO", "/pomo_estado"), ("☕ DESCANSO", "/descanso")],
    [("⏹️ DETENER", "/stop")],
    [PANEL_HOME],
]

PANEL_POMO_MINUTOS = "⏱️ ¿Cuántos minutos?"
PANEL_POMO_FOCO = "🎯 ¿Cuál es el foco?"

# --- Gmail ---------------------------------------------------------------

PANEL_GMAIL_TITULO = "📬 GMAIL"

PANEL_GMAIL_BOTONES = [
    [("📥 ¿HAY CORREOS?", "/gmail_hay")],
    [("👥 REMITENTES", "/gmail_remitentes")],
    [("📄 CONTENIDO", "panel:gm:contenido")],
    [("❓ AYUDA", "/gmail_ayuda")],
    [PANEL_HOME],
]

PANEL_GMAIL_NUMERO = "📨 ¿Número del correo?"
PANEL_GMAIL_FORMATO = "📄 Formato"


def panel_gmail_formato_botones(numero: str):
    """Los dos botones llevan el comando ya armado.

    Guardar el número en el callback en vez de en memoria hace que el formato
    se pueda elegir aunque el proceso se haya reiniciado en el medio.
    """
    return [
        [("👁️ NATURAL", f"/gmail_contenido {numero} natural")],
        [("🧩 BASE64", f"/gmail_contenido {numero} base64")],
        [("↩️ GMAIL", "panel:gmail")],
    ]


# --- Sistema -------------------------------------------------------------

PANEL_SYSTEM_TITULO = "⚙️ SISTEMA"

PANEL_SYSTEM_BOTONES = [
    [("🛠️ ADMIN", "/admin"), ("📊 ESTADO", "/estado")],
    [("⏸️ SUSPENDER", "/suspender"), ("▶️ REANUDAR", "/reanudar")],
    [("🚫 CANCELAR", "/cancelar"), ("🧹 RESET ESTADO", "/reset_estado")],
    [("🗑️ BORRAR INTERVALO", "panel:sys:borrar")],
    [("🎁 MENSAJE ASISTIDO", "panel:sys:sorpresa")],
    [("👩‍🦳 RECORDATORIOS ASISTIDOS", "/recordatorios_lite")],
    [PANEL_HOME],
]

# --- crear una sorpresa --------------------------------------------------
# Se pregunta primero si lleva foto, porque de eso depende todo lo que sigue.
# El texto va SIEMPRE antes que la foto: es lo que se está mandando; la imagen
# acompaña. Y nada sale hasta ver una vista previa idéntica a lo que va a
# recibir ella.

PANEL_SORPRESA_MENU = (
    "⚓️✨ CREAR SORPRESA\n\n"
    "¿Cómo quieres enviarla?"
)

PANEL_SORPRESA_MENU_BOTONES = [
    [("📸 CON FOTO", "panel:sor:foto")],
    [("💬 SIN FOTO", "panel:sor:texto")],
    [("❓ PREGUNTA ASISTIDA", "panel:sor:pregunta")],
    [("❌ CANCELAR", "panel:sor:cancelar")],
]

SORPRESA_PIDE_TEXTO_CON_FOTO = (
    "⚓️✨ SORPRESA CON FOTO\n\n"
    "Escribe el texto que quieres enviar:\n\n"
    "✍️ Esperando mensaje..."
)

SORPRESA_PIDE_TEXTO_SIN_FOTO = (
    "⚓️✨ SORPRESA SIN FOTO\n\n"
    "Escribe el texto:\n\n"
    "✍️ Esperando mensaje..."
)

SORPRESA_PIDE_FOTO = "✅ Texto recibido.\n\nAhora envía la foto 📸"

# Llegó lo que no tocaba. Ninguno de los dos pierde lo que ya había.
SORPRESA_FALTA_FOTO = "📸 Ahora necesito la foto."
SORPRESA_FALTA_TEXTO = "✍️ Primero necesito el texto."

SORPRESA_BOTONES_SIN_FOTO = [
    [("🚀 ENVIAR", "panel:sor:enviar")],
    [("✏️ EDITAR", "panel:sor:edtexto")],
    [("❌ CANCELAR", "panel:sor:cancelar")],
]

SORPRESA_BOTONES_CON_FOTO = [
    [("🚀 ENVIAR", "panel:sor:enviar")],
    [("✏️ EDITAR TEXTO", "panel:sor:edtexto")],
    [("🔄 CAMBIAR FOTO", "panel:sor:edfoto")],
    [("❌ CANCELAR", "panel:sor:cancelar")],
]

SORPRESA_CANCELADA = "❌ Sorpresa cancelada."

SORPRESA_SIN_FLUJO = "No hay ninguna sorpresa a medio crear."

SORPRESA_PIDE_FOTO_DE_NUEVO = "🔄 Manda la foto nueva 📸"


# --- pregunta cerrada para la usuaria asistida -----------------------------------------

ASISTQ_PIDE_PREGUNTA = "❓ ¿Qué quieres preguntarle?"
ASISTQ_PIDE_OPCION_A = "🔘 Escribe la PRIMERA respuesta."
ASISTQ_PIDE_OPCION_B = "🔘 Escribe la SEGUNDA respuesta."
ASISTQ_TEXTO_VACIO = "⚠️ Necesito que escribas un texto."
ASISTQ_OPCION_LARGA = (
    "⚠️ Esa respuesta es demasiado larga para un botón.\n"
    "Escríbela más corta."
)
ASISTQ_PREGUNTA_LARGA = "⚠️ La pregunta es demasiado larga. Escríbela más corta."
ASISTQ_OPCIONES_IGUALES = "⚠️ Las dos respuestas deben ser distintas."
ASISTQ_ENVIADA = "✅ Pregunta enviada."
ASISTQ_CANCELADA = "❌ Pregunta cancelada."
ASISTQ_SIN_BORRADOR = "No hay ninguna pregunta a medio crear."
ASISTQ_SIN_DESTINO = "No hay ninguna usuaria configurada para recibirla."
ASISTQ_ERROR_ENVIO = "No pude enviar la pregunta. Intenta de nuevo."
ASISTQ_YA_RESPONDIDA = "✅ Ya respondiste esta pregunta."
ASISTQ_NO_DISPONIBLE = "Esta pregunta ya no está disponible."
ASISTQ_RESPUESTA_REGISTRADA = "✅ Respuesta registrada."

ASISTQ_ACCIONES = [
    [("✅ ENVIAR", "panel:asistq:enviar")],
    [("✏️ EDITAR", "panel:asistq:editar")],
    [("❌ CANCELAR", "panel:asistq:cancelar")],
]


def pregunta_asistida(texto: str) -> str:
    return sorpresa(texto)


def pregunta_asistida_preview_botones(opcion_a: str, opcion_b: str):
    return [
        [(opcion_a, "panel:asistq:preview:a")],
        [(opcion_b, "panel:asistq:preview:b")],
        *ASISTQ_ACCIONES,
    ]


def pregunta_asistida_botones(question_id: int, opcion_a: str, opcion_b: str):
    return [
        [(opcion_a, f"asistq:{question_id}:a")],
        [(opcion_b, f"asistq:{question_id}:b")],
    ]


def pregunta_asistida_respondida(pregunta: str, respuesta: str) -> str:
    return (
        f"{sorpresa(pregunta)}\n\n"
        f"✅ Respondiste:\n{respuesta}"
    )


def pregunta_asistida_notificacion(pregunta: str, respuesta: str) -> str:
    return (
        "👩‍🦳 RESPUESTA ASISTIDA\n\n"
        f"❓ {pregunta}\n\n"
        f"✅ {respuesta}"
    )


PANEL_SORPRESA_PIDE = "🎁 Escribe el mensaje para la usuaria asistida:"

# Único teclado de los pasos que esperan texto: la salida del flujo.
PANEL_PIDE_BOTONES = [[PANEL_HOME]]


# ==========================================================================
# Cola de eventos — lo que vence mientras el canal está ocupado
# ==========================================================================
# No es Guardian y no debe sonar como Guardian. Guardian interrumpe para que
# arranques algo ahora; esto sólo sostiene un evento que quedó esperando y
# pide una decisión. Sin ráfagas, sin código, sin escalada.
#
# La regla que ordena todos estos textos: el tiempo puede volver viejo un
# evento, nunca resolverlo. Ninguno de estos mensajes anuncia un vencimiento.

COLA_LIBRE = "😌 Sistema libre."

COLA_DECISION_TITULO = "📥 SIGUIENTE PENDIENTE"

COLA_BOTON_EXPIRADO = "Ese botón ya no corresponde al evento pendiente."


def cola_encolado(titulo: str, pendientes: int) -> str:
    """Aviso único al entrar. No se repite: para eso está el agregado."""
    return (
        f"📥 «{esc(titulo)}» quedó pendiente.\n"
        f"Hay {pendientes} evento{'s' if pendientes != 1 else ''} esperando."
    )


def cola_pendientes(pendientes: int) -> str:
    """Presencia suave mientras hay un activo. Uno solo, nunca uno por evento."""
    return (
        f"📥 Hay {pendientes} evento{'s' if pendientes != 1 else ''} pendiente"
        f"{'s' if pendientes != 1 else ''}."
    )


def cola_ancla(titulos: list) -> str:
    """La unica tarjeta persistente mientras otra tarea esta activa.

    Lista todo lo que espera, en el orden en que se va a ofrecer, con la
    siguiente en negrita. Un número ("+2 en cola") obligaba a acordarse de qué
    había detrás.
    """
    lineas = [f"- <b>{esc(titulos[0])}</b>"] if titulos else []
    lineas += [f"- {esc(t)}" for t in titulos[1:]]
    return "📥 <b>SIGUIENTE PENDIENTE</b>\n\n" + "\n".join(lineas)


def cola_decision(titulo: str, programado: str, en_cola=None) -> str:
    """La hora que se muestra es la original. Presentarlo tarde no la cambia.

    Debajo lista lo que sigue esperando, uno por línea.
    """
    en_cola = list(en_cola or [])
    espera = (
        "\n\nEn cola:\n" + "\n".join(f"- {esc(t)}" for t in en_cola)
        if en_cola else ""
    )
    return (
        f"{COLA_DECISION_TITULO}\n\n"
        f"<b>{esc(titulo)}</b>\n"
        f"Programado: {esc(programado)}{espera}"
    )


def cola_descartado(titulo: str) -> str:
    return f"🗑️ «{esc(titulo)}» descartado."


def cola_despues(titulo: str) -> str:
    return f"⏳ «{esc(titulo)}» vuelve al final de la cola."


def cola_botones(rid: int):
    """Tres salidas y ninguna más.

    Reagendar es una acción manual en Google Calendar. Mástil sólo se ocupa de
    que el evento no se pierda mientras no haya decisión.
    """
    return [
        [("▶️ HACER AHORA", f"cola:ahora:{rid}")],
        [("⏳ DESPUÉS", f"cola:despues:{rid}"), ("🗑️ DESCARTAR", f"cola:descartar:{rid}")],
    ]


# ==========================================================================
# Buzón dedicado — dos revisiones al día
# ==========================================================================
# La cuenta de Gmail conectada a Mástil recibe correo de una sola persona, así
# que el buzón entero es ese buzón. El límite no es un bloqueo: es fricción. La
# regla es del usuario y él puede romperla; lo que no puede es romperla sin
# darse cuenta de que la está rompiendo.
#
# Abrir el contenido de un correo no cuenta ni se limita: el precio se paga al
# decidir mirar, no al leer lo que ya se decidió mirar.

GMAIL_LIMITE_DIARIO = 2

# Cada opción tiene su propio par: "¿hay correos?" y "¿de quién son?" son
# preguntas distintas, y gastar una no debería dejarte sin la otra.
GMAIL_NOMBRES = {
    "/gmail_hay": "¿hay correos?",
    "/gmail_remitentes": "remitentes",
}


def gmail_limite_alcanzado(comando: str) -> str:
    nombre = GMAIL_NOMBRES.get(comando, "esta revisión")
    return (
        f"📧 Ya usaste tus {GMAIL_LIMITE_DIARIO} revisiones de hoy de «{nombre}».\n\n"
        "La próxima estará disponible mañana."
    )

GMAIL_BOTONES_LIMITE = [
    [("🔓 REVISAR IGUAL", "/gmail_igual")],
    [("⏳ DEJARLO", "/gmail_dejarlo")],
]


def gmail_confirma_disponible(comando: str, quedan: int) -> str:
    """La pregunta antes de gastar una revisión que todavía hay.

    Un toque sin querer no debería costar una revisión, y decir cuántas
    quedan muestra el precio antes de pagarlo. Agotadas, no pasa por acá:
    sigue la fricción de siempre.
    """
    nombre = GMAIL_NOMBRES.get(comando, "esta revisión")
    cupo = ("Te queda 1 revisión" if quedan == 1
            else f"Te quedan {quedan} revisiones")
    return f"📬 ¿Revisar «{nombre}»?\n\n{cupo} hoy."

GMAIL_PIDE_MOTIVO = (
    "🧠 ANTES DE REVISAR\n\n"
    "¿Qué necesitas comprobar exactamente?"
)

GMAIL_BOTONES_MOTIVO = [
    [("✍️ ESCRIBIR MOTIVO", "panel:gm:motivo")],
    [("⏳ DEJARLO", "/gmail_dejarlo")],
]

GMAIL_MOTIVO_ESCRIBIR = "✍️ Escribe brevemente qué necesitas comprobar:"

GMAIL_EVAL_FALLO = "👁️ No pude completar la evaluación ahora."

GMAIL_BOTONES_FALLO = [
    [("🔄 INTENTAR DE NUEVO", "/gmail_reintentar")],
    [("⏳ DEJARLO", "/gmail_dejarlo")],
]

GMAIL_BOTONES_CONFIRMAR = [
    [("✅ SÍ, REVISAR", "/gmail_si")],
    [("⏳ DEJARLO", "/gmail_dejarlo")],
]

GMAIL_DEJADO = "⏳ Lo dejamos por ahora."

# --- modo simple (temporal) ---------------------------------------------
#
# Una sola pregunta y nada mas. Ver `FRICCION_COMPLETA` en modules/gmail.py.

GMAIL_CONFIRMA_SIMPLE = "📬 ¿Seguro deseas revisar?"

GMAIL_BOTONES_SIMPLE = [
    [("✅ SÍ, REVISAR", "/gmail_igual")],
    [("⏳ DEJARLO", "/gmail_dejarlo")],
]

GMAIL_SIN_FRICCION = "No hay ninguna revisión pendiente de confirmar."


def gmail_ultima_confirmacion(recomendacion: str) -> str:
    return (
        "⚠️ ÚLTIMA CONFIRMACIÓN\n\n"
        f"Vigía te recomienda:\n{recomendacion}\n\n"
        "Aun así, puedes revisar ahora.\n\n"
        "¿Confirmas?"
    )


# El prompt es lo único que acota a Gemini. Las prohibiciones van explícitas
# porque un modelo, sin ellas, deriva solo hacia el diagnóstico y el sermón.
GMAIL_PROMPT = """
Eres Vigía de Mástil. Evalúa ÚNICAMENTE la calidad de la razón declarada para
romper una regla que el propio usuario se puso.

BUZÓN: cuenta de correo dedicada exclusivamente a su ex pareja.
CONSULTA QUE QUIERE HACER: {consulta}
REGLA: máximo {limite} revisiones diarias de esa consulta, elegida por él mismo.
USO DE HOY: {usadas} de {limite}. Ya la agotó.

MOMENTO:
- Ahora: {ahora}
- Última revisión de este buzón: {ultima}
- Tiempo transcurrido desde entonces: {transcurrido}

MOTIVO DECLARADO (texto exacto del usuario):
"{motivo}"

MOTIVOS QUE YA HABÍA ESCRITO ANTES (del más reciente al más antiguo):
{historial}

CONTEXTO OPERATIVO CONOCIDO POR MÁSTIL:
{contexto}
Mástil no tiene forma de saber si esos elementos se relacionan con este buzón.
No supongas que se relacionan.

QUÉ HACER:
- Distingue entre una necesidad concreta (un dato puntual, un plazo, un
  compromiso ya acordado) y una comprobación general ("ver si hay algo nuevo").
- Si hay una razón concreta y temporal, dilo y respáldala.
- Si no la hay, dilo con claridad y sugiere dejarlo para mañana.
- Compara el motivo de hoy con los anteriores. Si repite una razón ya usada,
  dilo y cita el parecido concreto. Es un hecho observable en el texto, no un
  reproche ni una interpretación de por qué lo escribió.
- La decisión final es suya. Recomienda, no ordenes.

QUÉ NO HACER, EN NINGÚN CASO:
- No diagnostiques ni nombres estados mentales que no puedas observar.
- No atribuyas estados internos que no puedas observar.
- No hables como autoridad ni emitas juicios sobre la persona.
- No moralices, no avergüences, no felicites.
- No inventes urgencias, plazos ni intenciones que no aparezcan arriba.
- No hagas preguntas.

FORMATO: dos o tres frases, en español, en segunda persona. Sólo el texto de
la recomendación, sin encabezados ni viñetas.
"""


def gmail_contexto_operativo(evento: str | None, pendientes: int) -> str:
    lineas = []
    lineas.append(
        f"- Evento de Calendar en curso: {evento}" if evento
        else "- Evento de Calendar en curso: ninguno."
    )
    lineas.append(f"- Eventos pendientes de decisión en la cola: {pendientes}.")
    lineas.append("- Plazos o compromisos explícitos registrados: ninguno.")
    return "\n".join(lineas)


def vigia_nota_fotos(cuantas: int) -> str:
    """Qué son las imágenes adjuntas al análisis.

    Con dos hay que decir explícitamente que son el mismo lugar. Sin eso el
    modelo puede leerlas como dos ambientes distintos y planificar el doble
    del trabajo que hay.
    """
    if int(cuantas or 1) >= 2:
        return (
            "Las DOS fotos adjuntas son dos vistas del MISMO lugar, tomadas en "
            "el mismo\nmomento desde ángulos distintos. No son dos ambientes ni "
            "dos momentos:\núsalas juntas para entender una sola escena.\n\n"
            "Son el ESTADO ACTUAL del entorno, no la especificación del "
            "problema:\ncombínalas con el objetivo, el contexto y el plan."
        )
    return (
        "La foto adjunta es el ESTADO ACTUAL del entorno. No es la "
        "especificación del\nproblema: combínala con el objetivo, el contexto "
        "y el plan."
    )


def gmail_historial_motivos(motivos: list) -> str:
    """Los motivos anteriores, tal como se escribieron.

    Sin esto cada revisión se juzga sola, y una fórmula repetida treinta veces
    pasa treinta veces: la fricción se gasta sin que nadie lo note. El texto va
    entero y sin resumir, porque lo que delata una excusa hecha costumbre es
    justamente que se repite palabra por palabra.
    """
    if not motivos:
        return "- (ninguno registrado todavía)"
    lineas = []
    for entrada in reversed(motivos):
        cuando = str(entrada.get("cuando") or "")[:16].replace("T", " ")
        texto = str(entrada.get("motivo") or "").strip() or "(en blanco)"
        lineas.append(f'- {cuando}: "{texto}"')
    return "\n".join(lineas)


# ==========================================================================
# Vigía 2.0 — andamio de planificación secuencial
# ==========================================================================
# El problema que ataca no es la falta de esfuerzo: es que una tarea difusa
# produce una secuencia ineficiente. Sacar basura, ordenar ropa, volver a la
# basura. Cada salto cuesta un desplazamiento y una decisión.
#
# Por eso la unidad de estado NO es el tiempo continuo sino
# objetivo + contexto + estrategia + bloque actual + estado observado.
# La continuidad es semántica: la tarea sobrevive una pausa, un día, un
# reinicio. La foto es el punto de reentrada, no un control de asistencia.

VIGIA_USO = (
    "Uso: <code>/vigia ordenar la cocina</code>\n\n"
    "Escribe qué quieres lograr y te doy el primer bloque."
)

VIGIA_YA_ACTIVA = "Ya hay un objetivo en curso. Ciérralo con /vigia_cancelar."

VIGIA_PIDE_FOTO = (
    "📸 Manda una foto del estado actual.\n\n"
    "Si hay algo que deba saber antes —una prioridad, una restricción, algo "
    "que no se ve en la foto— escríbelo primero."
)

VIGIA_CONTEXTO_OK = "📋 Anotado. Cuando quieras, manda la foto."

VIGIA_TRABADO_PIDE_FOTO = (
    "📸 Manda una foto de cómo está ahora y te doy otra entrada."
)

# Un fallo del modelo no es uno solo, y confundirlos empuja a reintentar
# justo cuando reintentar es lo peor que se puede hacer: con la cuota agotada,
# cada intento gasta otra consulta y alarga el encierro.
VIGIA_SIN_ANALISIS = (
    "👁️ No pude analizar ahora.\n\n"
    "El objetivo sigue donde estaba."
)


def vigia_cuota(limite: int, usadas: int = 0) -> str:
    """429: cuota DIARIA del plan gratuito.

    El `Please retry in Ns` que manda Google engaña: sugiere segundos cuando
    la ventana es de un día. Decirlo mal empuja a reintentar, y cada reintento
    no arregla nada.
    """
    return (
        "🚦 <b>Se acabó la cuota diaria de Gemini</b> en la cuenta gratuita "
        f"({limite} consultas por día).\n\n"
        "No se arregla esperando un rato: se reinicia mañana. Para subir el "
        "límite hay que activar facturación en la cuenta de Gemini.\n\n"
        "El objetivo sigue donde estaba."
    )


def vigia_fallo(reason: str) -> str:
    """Traduce el error crudo del modelo a algo accionable."""
    crudo = str(reason or "")
    if "HTTP 503" in crudo:
        return (
            "👁️ El modelo está saturado ahora mismo.\n\n"
            "Suele durar poco y se pasa solo. El objetivo sigue donde estaba."
        )
    if "timed out" in crudo or "timeout" in crudo.lower():
        return (
            "👁️ El modelo tardó demasiado en responder.\n\n"
            "El objetivo sigue donde estaba: prueba de nuevo."
        )
    return VIGIA_SIN_ANALISIS

# Un 503 o un timeout son transitorios, y la foto no cambió. Volver a pedirla
# sería cobrar un viaje por un problema que no es de la persona.
VIGIA_BOTONES_REINTENTO = [
    [("🔄 REINTENTAR", "/vigia_reintentar")],
    [("➡️ SIGUIENTE", "/vigia_siguiente"), ("🆘 ME TRABÉ", "/vigia_trabado")],
    [PANEL_HOME],
]

# Acuse inmediato: la llamada a Gemini bloquea el ciclo hasta 90 segundos y sin
# esto la pantalla se queda muda, como si el botón no hubiera hecho nada.
VIGIA_PENSANDO = "👁️ Pensando…"

# El plan se recorre en local: avanzar no llama al modelo. Cuando se acaba la
# lista la foto sigue sirviendo —puede confirmar el objetivo o mostrar lo que
# falta— pero ya no es obligatoria: cerrar sin foto es un final legítimo.
VIGIA_PLAN_TERMINADO = (
    "✅ <b>Terminaste todos los bloques del plan.</b>\n\n"
    "Si quieres, manda una foto y confirmo el objetivo o te doy lo que falte. "
    "Si ya está, ciérralo."
)

VIGIA_BOTONES_PLAN_TERMINADO = [
    [("✅ CERRAR", "/vigia_cerrar")],
    [("🆘 ME TRABÉ", "/vigia_trabado")],
    [PANEL_HOME],
]

VIGIA_SIN_PLAN = (
    "No me queda plan guardado para avanzar.\n\n"
    "Manda una foto y armo uno nuevo sobre lo que hay."
)


def vigia_bloque_numerado(bloque: str, numero: int, total: int,
                          estimacion: str = "") -> str:
    """El bloque, y en qué punto del plan estás. Sin barra de progreso ni
    porcentajes: sólo dónde vas, que es lo que ubica al volver."""
    texto = f"🧭 <b>AHORA</b>  <i>({numero} de {total})</i>\n\n{esc(bloque)}"
    if estimacion:
        texto += f"\n\n⏱️ Estimación aproximada: {esc(estimacion)}"
    return texto


VIGIA_SIN_OBJETIVO = "No hay ningún objetivo en curso. Empieza con /vigia."

VIGIA_CANCELADO = "👁️ Objetivo cerrado."

# El único botón. La foto es el punto de reentrada; no hay nada más que tocar.
# Ningún mensaje de Vigía queda sin salida. La foto no se puede apretar, pero
# todo lo demás sí: terminar el bloque, trabarse o irse al panel.
# Avanzar es el botón principal y NO pide foto: recorrer la estrategia no
# necesita volver a mirar, porque el inventario ya lo dio la primera foto.
# La foto queda para re-sincronizar y para cerrar, que es lo único que exige ver.
VIGIA_BOTONES = [
    [("➡️ SIGUIENTE", "/vigia_siguiente")],
    [("📸 RECALIBRAR", "/vigia_bloque_ok"), ("🆘 ME TRABÉ", "/vigia_trabado")],
    [PANEL_HOME],
]

# Cuando ya está esperando una foto, "bloque terminado" sería redundante.
# Mandar dos fotos vive acá, junto al pedido, y no sólo dentro del Panel: la
# decisión se toma mirando el desorden, no navegando menús. Una es el modo por
# defecto, así que el único botón que hace falta es el que pide la otra.
VIGIA_BOTON_DOS_FOTOS = ("2️⃣ VOY A MANDAR DOS", "panel:vig:foto:2")

VIGIA_BOTONES_ESPERA = [
    [("➡️ SIGUIENTE", "/vigia_siguiente")],
    [VIGIA_BOTON_DOS_FOTOS],
    [("🆘 ME TRABÉ", "/vigia_trabado")],
    [PANEL_HOME],
]

# ME TRABÉ existe para recalibrar sobre el estado real, y eso exige mirar: no
# se puede avanzar declarando el bloque hasta que llegue la foto. La salida sin
# foto es volver al bloque, que también levanta el trabado.
VIGIA_BOTONES_TRABADO = [
    [("▶️ VOLVER AL BLOQUE", "/vigia_bloque")],
    [PANEL_HOME],
]

VIGIA_BOTONES_CIERRE = [[PANEL_HOME]]

# El objetivo ya está cumplido. La foto final es registro, no fiscalización: no
# reabre el plan, no agrega bloques y no hace falta para cerrar.
VIGIA_BOTONES_FINAL = [
    [("📸 REGISTRAR RESULTADO", "/vigia_registrar")],
    [("✅ CERRAR", "/vigia_cerrar")],
    [PANEL_HOME],
]

VIGIA_BOTONES_REGISTRO = [
    [("✅ CERRAR", "/vigia_cerrar")],
    [PANEL_HOME],
]

VIGIA_REGISTRO_PIDE_FOTO = (
    "📸 <b>Manda una foto del resultado final.</b>\n\n"
    "Es sólo registro: no cambia el plan ni agrega nada."
)

VIGIA_REGISTRO_OK = "📸 Resultado registrado.\n\n✅ Vigía cerrado."

VIGIA_CERRADO = "✅ Vigía cerrado."

# Avanzar declarando el bloque mientras estás trabado sería justo lo que ME
# TRABÉ vino a evitar: el plan se recalibra sobre lo que se ve, no sobre lo
# que se supone.
VIGIA_TRABADO_EXIGE_FOTO = (
    "🆘 Para recalibrar necesito ver cómo está ahora.\n\n"
    "Manda una foto. Si prefieres seguir con el bloque que tenías, vuelve a él."
)

# Recién creada la tarea: todavía no hay bloque, así que lo único que ofrece
# es completar el contexto o irse.
VIGIA_BOTONES_INICIO = [
    [("📋 CONTEXTO", "panel:vig:ctx")],
    [VIGIA_BOTON_DOS_FOTOS],
    [PANEL_HOME],
]

VIGIA_BLOQUE_OK = (
    "📸 <b>Manda una foto del estado actual.</b>\n\n"
    "Con eso recalibro el plan sobre lo que hay de verdad."
)

# El modelo puede decir que no le alcanza con la foto y el contexto.
VIGIA_FALTA_TITULO = "⚠️ <b>DATOS INSUFICIENTES</b>"

VIGIA_BOTONES_FALTA = [
    [("✍️ RESPONDER", "panel:vig:aclarar")],
    [("📸 OTRA FOTO", "/vigia_otra_foto")],
    [PANEL_HOME],
]

VIGIA_OTRA_FOTO = "📸 Manda otra foto, con más contexto visual si se puede."

VIGIA_MOTIVO_ESCRIBIR = "✍️ Responde en una línea:"

# Volver a leer el bloque no cuesta una foto ni una llamada al modelo: el
# estado ya está guardado. Es la respuesta a "¿en qué iba?" después de dos días.
VIGIA_SIN_BLOQUE = (
    "Todavía no hay bloque en curso.\n\n"
    "Manda una foto del estado actual y te doy el primero."
)


def vigia_reanudar(objetivo: str, bloque: str) -> str:
    return (
        f"{vigia_objetivo(objetivo)}\n\n"
        f"🧭 <b>AHORA</b>\n\n{esc(bloque)}"
    )


def vigia_falta_contexto(pregunta: str) -> str:
    return f"{VIGIA_FALTA_TITULO}\n\n{esc(pregunta)}"


def vigia_objetivo(objetivo: str) -> str:
    return f"🎯 <b>{esc(objetivo)}</b>"


def vigia_deriva(nota: str, bloque: str) -> str:
    """Describe la secuencia, no a la persona. Sin moral y sin diagnóstico."""
    partes = ["⚠️ <b>TE ESTÁS DESVIANDO</b>"]
    if nota:
        partes.append(esc(nota))
    partes.append(f"🧭 Vuelve a:\n{esc(bloque)}")
    return "\n\n".join(partes)


def vigia_completado(objetivo: str) -> str:
    return (
        f"🏁 <b>OBJETIVO COMPLETADO</b>\n\n{esc(objetivo)}: listo.\n\n"
        "¿Quieres registrar el resultado final?"
    )


# El prompt es lo único que acota al modelo. Las prohibiciones van explícitas
# porque sin ellas deriva solo hacia la lista de veinte pasos y el sermón.
VIGIA_PROMPT_PLAN = """
Eres Vigía de Mástil. Ayudas a que una tarea física larga mantenga una
secuencia de ejecución eficiente. No eres un cronómetro ni un supervisor.

OBJETIVO DECLARADO: {objetivo}

CONTEXTO DADO POR LA PERSONA: {contexto}

CONTEXTO NUEVO DESDE LA ÚLTIMA FOTO: {contexto_nuevo}

PLAN VIGENTE (bloques que quedaban por hacer): {estrategia}

BLOQUE QUE ESTABA EN CURSO: {bloque}

BLOQUES DADOS POR HECHOS SIN COMPROBAR: {declarados}

LA PERSONA DICE QUE SE TRABÓ: {trabado}

{fotos}

LA FOTO SIEMPRE GANA. Si contradice lo que se dio por hecho, corrige el plan
según lo que ves. No lo señales ni lo reproches: sólo reencuadra.

QUÉ DEBES HACER:

1. Devuelve el PLAN COMPLETO de lo que queda, como una lista de 2 a 6
   bloques. La persona los va a ir haciendo en orden SIN volver a
   consultarte, así que cada uno tiene que estar escrito para ejecutarse tal
   cual, sin que haga falta interpretarlo.

2. Cada bloque: concreto, acotado a una categoría o una zona, y diciendo
   también qué NO tocar todavía. Ejemplo de un bloque:
   "Recoge toda la ropa visible y déjala en un solo punto. No ordenes
   todavía el escritorio."

3. Agrúpalos para reducir desplazamientos y cambios de contexto: primero
   todo lo de una categoría, después lo de la siguiente. Ése es el punto de
   que exista un plan.

4. El PRIMER bloque de la lista es lo que hay que hacer AHORA, según lo que
   muestra la foto.

5. Si ya había un plan vigente, MANTENLO. Cámbialo cuando haya cambiado de
   forma relevante el objetivo, el contexto, las restricciones o el estado que
   muestra la foto. Si CONTEXTO NUEVO DESDE LA ÚLTIMA FOTO trae algo, es un
   motivo válido por sí solo, aunque la foto no lo muestre.
   No lo reordenes por preferencia ni por estilo.

6. Si LA PERSONA DICE QUE SE TRABÓ es "sí", no repitas un plan del mismo
   tamaño ni pases al bloque siguiente: divide el BLOQUE QUE ESTABA EN CURSO
   en 2 o 3 pasos más chicos y concretos, sólo para completar ese bloque.
   Usa la foto para decidir por dónde. No toques los bloques que venían
   después del actual ni el objetivo: el problema es local, la solución
   también.

7. Decide el estado:
   - "EN_RUTA": el avance es coherente con el plan.
   - "DERIVA": se está trabajando en algo real, pero de una fase posterior,
     con la actual todavía sin terminar. El primer bloque debe ser volver a
     lo que falta.
   - "COMPLETADO": el objetivo está suficientemente cumplido según su
     alcance y prioridad declarados. No exijas perfección. Con "COMPLETADO"
     la lista puede ir vacía.
   - "FALTA_CONTEXTO": la foto y el contexto no alcanzan para planificar sin
     inventar. Úsalo sólo si de verdad no puedes; deja la lista vacía y
     escribe en "pregunta" UNA sola cosa concreta que necesitas saber.

PROHIBIDO:
- Bloques difusos como "ordena la habitación".
- Meter varias categorías en un mismo bloque.
- Hablar de tiempo transcurrido, de pausas, de retrasos o de constancia.
- Moralizar, avergonzar, felicitar o motivar.
- Nombrar estados internos o rasgos de la persona.
- Inventar objetos, zonas o restricciones que no estén en la foto ni arriba.
- Hacer preguntas fuera de "pregunta".

RESPONDE SÓLO JSON VÁLIDO:
{{
  "estado": "EN_RUTA" | "DERIVA" | "COMPLETADO" | "FALTA_CONTEXTO",
  "estrategia": ["bloque de ahora", "el siguiente", "el siguiente"],
  "nota": "si es DERIVA, una frase que describa la secuencia, no a la persona",
  "pregunta": "sólo si es FALTA_CONTEXTO: la única cosa que necesitas saber",
  "estimacion": "trabajo activo aproximado de todo el plan, o cadena vacía"
}}
"""


def vigia_pendientes(bloques: list) -> str:
    """Los bloques que siguen abiertos, del que está en curso hacia adelante.

    Separada de `vigia_declarados` por el caso vacío: ahí “ninguno” significa
    lo contrario en cada una, y mezclarlas era parte del enredo.
    """
    if not bloques:
        return "(ninguno: se hicieron todos los del plan)"
    return "\n".join(f"- {b}" for b in bloques)


def vigia_declarados(declarados: list) -> str:
    if not declarados:
        return "(ninguno: todo lo hecho se comprobó con una foto)"
    return "\n".join(f"- {d}" for d in declarados)


def vigia_contexto_nuevo(campos: dict) -> str:
    """Sólo lo que cambió desde la última foto analizada.

    Separado de `vigia_contexto_prompt` a propósito: ese muestra TODO el
    contexto como si siempre hubiera sido así. Este es lo que el modelo
    todavía no vio, para que pese como motivo propio y no se disuelva
    adentro de lo que ya conocía.
    """
    etiquetas = {
        "alcance": "Alcance", "prioridad": "Prioridad",
        "elementos": "Elementos", "restricciones": "Restricciones",
        "extra": "Además",
    }
    if not campos:
        return "(sin cambios desde la última foto)"
    return "\n".join(f"- {etiquetas.get(c, c)}: {v}" for c, v in campos.items())


def vigia_contexto_prompt(contexto: dict) -> str:
    """El contexto estructurado, sólo con los campos que están llenos."""
    etiquetas = {
        "alcance": "Alcance", "prioridad": "Prioridad",
        "elementos": "Elementos", "restricciones": "Restricciones",
        "extra": "Además",
    }
    lineas = [
        f"- {etiquetas[clave]}: {valor}"
        for clave, valor in (contexto or {}).items()
        if clave in etiquetas and str(valor or "").strip()
    ]
    return "\n".join(lineas) if lineas else "(sin contexto adicional)"
