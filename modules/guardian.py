"""Guardian: eventos `**` de Calendar.

Una sola máquina de estados, de punta a punta:

    freno -> tregua -> chequeo -> rescate
              (/ok)   (/listo | /reinicio)

El freno **no** es un módulo aparte: es la primera fase de este flujo. Partirlo
en dos obligaría a cada mitad a tener su propia noción de cuál evento está
activo, y ahí vuelve el `current_event_id` global que causó que dos compromisos
cercanos se pisaran.

Cada evento conserva su fila y su fase. `is_active` marca cuál está en curso.
"""

from __future__ import annotations

import hashlib
import random
import re
from datetime import timedelta

import messages
from core.scheduler import clock, from_iso, is_due, iso, now_local, within_window
from integrations.calendar import is_activity_event
from integrations.telegram import make_code_image, make_text_image

# Espera entre escalones, en minutos: (mínimo, máximo).
#
# Al azar dentro del rango, a propósito. Si supieras que el próximo llega en
# 60 segundos exactos, lo podés esperar sin mirar. Si no lo podés predecir,
# hay que evaluar cada uno. Vigía ya usa esta idea con los pings de presencia.
ESPERA_NIVEL_1 = (3, 7)
ESPERA_NIVEL_2 = (8, 15)

# Nivel 3: techo de intensidad. Una ráfaga corta y después silencio real.
#
# La ráfaga NO crece nunca. Guardian persiste, pero no se vuelve cada vez más
# agresivo: eso es lo que terminaba enseñando a ignorarlo.
RAFAGA_MENSAJES = 7
RAFAGA_PASO = 3          # segundos entre mensajes de la ráfaga
SILENCIO_NIVEL_3 = 5     # minutos de silencio entre ráfagas

# Techo temporal del nivel 3. A los 70 minutos desde la PRIMERA ráfaga la
# intervención intensa deja de servir: si a esa altura no funcionó, seguir
# gritando sólo entrena a ignorar. El evento no se resuelve ni se olvida;
# baja a un mensaje por hora y se queda ahí.
INTERVENCION_MINUTOS = 70
BAJA_FRECUENCIA_MINUTOS = 60

# La tregua se ofrece recién en la segunda ráfaga: en la primera todavía no
# sabes si la necesitas, y ofrecerla ahí la vuelve la salida por defecto.
TREGUA_RAFAGA = 2
TREGUA_MINUTOS = 11
TREGUA_CODIGO_MINUTOS = 5
TREGUA_CODIGO_LARGO = 10

# Sin I, l, O, 0 ni 1: la secuencia se transcribe mirando una imagen, y
# confundir un carácter volvería la fricción buscada un castigo tonto.
# Sin minúsculas por lo mismo: dibujadas se confunden con las mayúsculas y
# no agregan nada — la fricción ya la pone tener que leerla y tipearla.
TREGUA_LETRAS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
TREGUA_NUMEROS = "23456789"
TREGUA_SIMBOLOS = "#!$%*+=?"

# Dos segundos entre el mensaje que orienta y el que dice qué pasa.
PAUSA_ORIENTACION = 2


# ==========================================================================
# Cola: lo que vence mientras el canal está ocupado
# ==========================================================================
# Guardian atiende un evento a la vez. Antes, el que vencía mientras había
# otro en curso simplemente no se seleccionaba y desaparecía con su ventana.
# Ahora espera en una fase de esta misma tabla hasta que la persona decida.
#
# La regla que gobierna todo lo de abajo, y que ninguna función puede romper:
# el reloj puede volver viejo un evento, nunca resolverlo. No hay ningún
# camino del tiempo hacia 'done' ni hacia 'discarded'.

# Fases en las que el evento ya tiene destino o ya está esperando uno. El ICS
# vuelve a traer el mismo evento en cada tick; sin esto, un evento encolado se
# re-activaría solo.
FASES_CON_DESTINO = ("done", "discarded", "queued", "decision")

# Recordatorios de la decisión, en minutos desde que se presentó. Después del
# último, cada 15. No escala en intensidad: sólo no deja que se enfríe.
DECISION_CADENCIA = (3, 8, 15, 30, 45, 60)
DECISION_LUEGO = 15

# Un solo aviso agregado mientras hay un evento activo, sin importar cuántos
# haya en cola. Uno por evento sería exactamente el ruido que esto evita.
COLA_AVISO_MINUTOS = 15

# Cuánto espera un evento al que se le dijo DESPUÉS antes de volver a ofrecerse.
DESPUES_MINUTOS = 15

COLA_AVISO_KEY = "cola_aviso_next"
COLA_HUBO_KEY = "cola_hubo"


def _offset_decision(numero: int) -> int:
    """Minutos desde la presentación hasta el recordatorio número `numero`."""
    if numero <= len(DECISION_CADENCIA):
        return DECISION_CADENCIA[numero - 1]
    return DECISION_CADENCIA[-1] + DECISION_LUEGO * (numero - len(DECISION_CADENCIA))


def proximo(minimo: float, maximo: float):
    return now_local() + timedelta(minutes=random.uniform(minimo, maximo))


def _hash_codigo(event_id: str, codigo: str) -> str:
    return hashlib.sha256(f"{event_id}:{codigo}".encode("utf-8")).hexdigest()


def _codigo_tregua() -> str:
    """Diez caracteres con letras, números y símbolos, garantizados los tres.

    No es seguridad: es fricción. Un botón se aprieta sin salir de la captura atencional
    y cuatro dígitos ya se tipean en automático. Esto obliga a mirar la
    pantalla y copiar con atención, que es la pausa que la tregua debe costar.
    """
    partes = [
        random.choice(TREGUA_LETRAS),
        random.choice(TREGUA_NUMEROS),
        random.choice(TREGUA_SIMBOLOS),
    ]
    todo = TREGUA_LETRAS + TREGUA_NUMEROS + TREGUA_SIMBOLOS
    partes += [random.choice(todo) for _ in range(TREGUA_CODIGO_LARGO - 3)]
    random.shuffle(partes)
    return "".join(partes)


def _sin_repetir(anterior: str | None) -> str:
    """Un texto del banco, nunca dos veces seguidas el mismo."""
    opciones = [t for t in messages.GUARDIAN_INSISTE if t != anterior]
    return random.choice(opciones or messages.GUARDIAN_INSISTE)


class GuardianModule:
    def __init__(self, config, db):
        self.config = config
        self.db = db

    # ---------------------------------------------------------------- datos

    def _active(self):
        row = self.db.one(
            "SELECT * FROM guardian_events WHERE is_active = 1 AND phase != 'done' LIMIT 1"
        )
        return row

    def _update(self, event_id: str, **fields) -> None:
        if not fields:
            return
        columns = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(
            f"UPDATE guardian_events SET {columns}, updated_at = ? WHERE event_id = ?",
            (*fields.values(), iso(now_local()), event_id),
        )

    def _say(self, text: str, buttons=None, send_after=None,
             parse_mode: str | None = None) -> None:
        self.db.enqueue(self.config.owner_chat_id, text, buttons=buttons,
                        send_after=send_after, parse_mode=parse_mode)

    def _label(self, title: str) -> str:
        return messages.task_label(title, self.config.prefix)

    # ------------------------------------------------------------- selección

    def _ensure_event(self, event) -> None:
        existing = self.db.one(
            "SELECT event_id FROM guardian_events WHERE event_id = ?", (event["id"],)
        )
        now = iso(now_local())
        if existing:
            self._update(event["id"], title=event["title"],
                         start_at=iso(event["start"]), is_active=1)
            return
        self.db.execute("UPDATE guardian_events SET is_active = 0")
        self.db.execute(
            """
            INSERT INTO guardian_events
                (event_id, title, start_at, phase, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 'brake', 1, ?, ?)
            """,
            (event["id"], event["title"], iso(event["start"]), now, now),
        )

    def _select(self, events) -> None:
        """¿Algún evento entra en su ventana?

        Ya no se corta cuando hay uno activo: en ese caso el evento se encola.
        Ésa es toda la diferencia con antes. Un evento que vence con el canal
        ocupado ya no se pierde junto con su ventana de un minuto.
        """
        anticipation = timedelta(minutes=self.config.anticipacion_alerta_minutes)
        grace = timedelta(minutes=1)

        for event in events:
            if is_activity_event(event["title"], self.config.activity_prefix):
                continue
            row = self.db.one(
                "SELECT phase, is_active FROM guardian_events WHERE event_id = ?",
                (event["id"],),
            )
            # El activo también se salta: el ICS lo sigue trayendo mientras
            # dura su ventana, y sin esto se encolaría a sí mismo.
            if row and (row["phase"] in FASES_CON_DESTINO or row["is_active"]):
                continue
            if not within_window(event["start"], anticipation, grace):
                continue

            if self._ocupado():
                self._encolar(event["id"], event["title"], iso(event["start"]))
            else:
                with self.db.transaction():
                    self._ensure_event(event)

    # -------------------------------------------------------------- la cola

    def _en_decision(self):
        return self.db.one(
            "SELECT rowid AS rid, * FROM guardian_events WHERE phase = 'decision' LIMIT 1"
        )

    def _ocupado(self) -> bool:
        """El canal de atención es uno solo.

        Una decisión sin responder lo ocupa igual que un evento activo: si no,
        el que vence encima se saltaría la fila del que ya estaba esperando.
        """
        return bool(self._active() or self._en_decision())

    def _pendientes(self) -> int:
        fila = self.db.one(
            "SELECT COUNT(*) AS c FROM guardian_events WHERE phase IN ('queued', 'decision')"
        )
        return int(fila["c"]) if fila else 0

    def _encolar(self, event_id: str, title: str, start_at: str) -> None:
        """Entra al final de la fila y se avisa una sola vez."""
        fila = self.db.one(
            "SELECT COALESCE(MAX(queue_seq), 0) AS m FROM guardian_events"
        )
        seq = int(fila["m"]) + 1
        ahora = iso(now_local())

        with self.db.transaction():
            existe = self.db.one(
                "SELECT event_id FROM guardian_events WHERE event_id = ?", (event_id,)
            )
            if existe:
                self._update(
                    event_id, phase="queued", is_active=0, queue_seq=seq,
                    title=title, start_at=start_at,
                    decision_at=None, decision_step=0, decision_next_at=None,
                )
            else:
                self.db.execute(
                    """
                    INSERT INTO guardian_events
                        (event_id, title, start_at, phase, is_active, queue_seq,
                         created_at, updated_at)
                    VALUES (?, ?, ?, 'queued', 0, ?, ?, ?)
                    """,
                    (event_id, title, start_at, seq, ahora, ahora),
                )
            self.db.set_state(COLA_HUBO_KEY, True)
            self._say(messages.cola_encolado(title, self._pendientes()),
                      parse_mode="HTML")
            self.db.audit("guardian", "cola_encolado", title)

    def _activar(self, fila) -> None:
        """Devuelve el evento al flujo de siempre, desde la primera fase."""
        with self.db.transaction():
            self.db.execute("UPDATE guardian_events SET is_active = 0")
            self._update(
                fila["event_id"], phase="brake", is_active=1,
                last_sent=None, next_at=None, code_hash=None,
                queue_seq=None, decision_at=None, decision_step=0,
                decision_next_at=None,
                # Su intervención todavía no empezó: los 70 minutos y las
                # ráfagas se cuentan por evento, nunca compartidos.
                intervencion_at=None, rafagas=0, modo=None,
                tregua_hasta=None, tregua_code_hash=None,
                tregua_code_hasta=None,
            )
            self.db.audit("guardian", "cola_activado", fila["title"])

    def _presentar(self, fila) -> None:
        """La decisión. La hora que muestra es la original, no la de ahora."""
        ahora = now_local()
        with self.db.transaction():
            self._update(
                fila["event_id"], phase="decision", is_active=0,
                queue_seq=None, decision_at=iso(ahora), decision_step=0,
                decision_next_at=iso(ahora + timedelta(minutes=_offset_decision(1))),
            )
            self.db.audit("guardian", "cola_decision", fila["title"])
        self._decir_decision(fila["event_id"])

    def _decir_decision(self, event_id: str, message_id: int | None = None) -> None:
        fila = self.db.one(
            "SELECT rowid AS rid, * FROM guardian_events WHERE event_id = ?",
            (event_id,),
        )
        if not fila:
            return
        with self.db.transaction():
            self.db.enqueue(
                self.config.owner_chat_id,
                messages.cola_decision(
                    fila["title"], clock(from_iso(fila["start_at"]))
                ),
                buttons=messages.cola_botones(fila["rid"]),
                parse_mode="HTML",
                message_id=message_id,
            )

    def _promover(self) -> None:
        """Canal libre: se ofrece el primero de la fila. Nunca se auto-activa."""
        if self._ocupado():
            return

        ahora = iso(now_local())
        fila = self.db.one(
            """
            SELECT * FROM guardian_events
            WHERE phase = 'queued'
              AND (decision_next_at IS NULL OR decision_next_at <= ?)
            ORDER BY queue_seq ASC, start_at ASC
            LIMIT 1
            """,
            (ahora,),
        )
        if fila:
            self._presentar(fila)
            return

        # Nada esperando y algo hubo: recién ahí el canal quedó libre.
        if not self._pendientes() and self.db.get_state(COLA_HUBO_KEY, False):
            with self.db.transaction():
                self.db.set_state(COLA_HUBO_KEY, False)
                self.db.set_state(COLA_AVISO_KEY, None)
                self._say(messages.COLA_LIBRE)

    def _recordatorios(self) -> None:
        """Dos ciclos, ninguno por evento: el agregado y el de la decisión."""
        activo = self._active()
        pendientes = self._pendientes()

        # a) Hay un activo y hay cola: presencia suave y agregada.
        if activo and pendientes:
            proximo = self.db.get_state(COLA_AVISO_KEY)
            if not proximo:
                with self.db.transaction():
                    self.db.set_state(
                        COLA_AVISO_KEY,
                        iso(now_local() + timedelta(minutes=COLA_AVISO_MINUTOS)),
                    )
            elif is_due(proximo):
                with self.db.transaction():
                    self.db.set_state(
                        COLA_AVISO_KEY,
                        iso(now_local() + timedelta(minutes=COLA_AVISO_MINUTOS)),
                    )
                    self._say(messages.cola_pendientes(pendientes), parse_mode="HTML")
        elif self.db.get_state(COLA_AVISO_KEY):
            with self.db.transaction():
                self.db.set_state(COLA_AVISO_KEY, None)

        # b) Una decisión sin responder se vuelve a mostrar, con sus botones.
        fila = self._en_decision()
        if fila and is_due(fila["decision_next_at"]):
            paso = int(fila["decision_step"] or 0) + 1
            base = from_iso(fila["decision_at"]) or now_local()
            with self.db.transaction():
                self._update(
                    fila["event_id"], decision_step=paso,
                    decision_next_at=iso(
                        base + timedelta(minutes=_offset_decision(paso + 1))
                    ),
                )
            self._decir_decision(fila["event_id"])

    # ------------------------------------------------------------------ tick

    def tick(self, events) -> None:
        self._select(events)
        # Antes de mirar el activo, la fila: así el evento que se acaba de
        # activar entra a su flujo en este mismo tick, no en el siguiente.
        self._promover()
        self._recordatorios()

        state = self._active()
        if not state:
            return

        phase = state["phase"]

        if phase == "brake":
            self._send_brake(state)
        elif phase == "truce":
            if is_due(state["truce_until"]):
                self._send_check(state)
        elif phase == "check":
            if is_due(state["check_until"]):
                self._enter_codigo(state)
        elif phase == "restart_truce":
            if is_due(state["restart_until"]):
                self._enter_codigo(state)
        elif phase in ("codigo", "confirmado"):
            # Confirmar la atención no completa la tarea: si tampoco llega
            # /listo, el flujo sigue escalando igual.
            if is_due(state["next_at"]):
                self._insistir(state, primera=True)
        elif phase == "insiste":
            self._nivel_3(state)

    # ----------------------------------------------------------- las fases

    def _send_brake(self, state) -> None:
        """Nivel 1: dos mensajes, una sola vez.

        Antes se repetía cada 60 segundos hasta recibir /ok. Cada repetición
        sin respuesta era un ensayo más de que ignorar funciona.
        """
        if state["last_sent"]:
            if is_due(state["next_at"]):
                self._enter_codigo(state)
            return

        ahora = now_local()
        with self.db.transaction():
            self._update(
                state["event_id"],
                last_sent=iso(ahora),
                next_at=iso(proximo(*ESPERA_NIVEL_1)),
            )
            self._say(messages.GUARDIAN_ORIENTACION)
            self._say(
                self._label(state["title"]),
                buttons=messages.BOTONES_AVISO,
                send_after=ahora + timedelta(seconds=PAUSA_ORIENTACION),
            )

    def _send_check(self, state) -> None:
        with self.db.transaction():
            self._update(
                state["event_id"], phase="check",
                check_until=iso(now_local() + timedelta(
                    minutes=self.config.tolerancia_chequeo_minutes)),
            )
            self._say(
                messages.guardian_chequeo(self._label(state["title"])),
                buttons=messages.BOTONES_CHEQUEO,
            )

    # ------------------------------------------------- nivel 2: el código

    def _enter_codigo(self, state) -> None:
        """Nivel 2: un número que hay que mirar y tipear.

        Un botón se aprieta sin salir de la captura atencional. Cuatro dígitos en una
        imagen, no: obligan a mirar, leer y escribir. Es el mismo mecanismo
        que usa Mástil Lite con la usuaria asistida, que funciona hace meses.
        """
        codigo = f"{random.randint(0, 9999):04d}"
        ahora = now_local()
        destino = self.config.evidence_dir.parent / "guardian"
        imagen = destino / f"codigo-{int(ahora.timestamp())}-{codigo}.png"

        with self.db.transaction():
            self._update(
                state["event_id"], phase="codigo",
                code_hash=_hash_codigo(state["event_id"], codigo),
                last_sent=iso(ahora),
                next_at=iso(proximo(*ESPERA_NIVEL_2)),
            )
            self._say(messages.GUARDIAN_ATENCION)
            try:
                make_code_image(codigo, imagen)
                self.db.enqueue(
                    self.config.owner_chat_id, messages.GUARDIAN_CODIGO,
                    photo_path=str(imagen), delete_photo=True,
                    send_after=ahora + timedelta(seconds=PAUSA_ORIENTACION),
                )
            except Exception as exc:
                print(f"[guardian] no pude generar la imagen: {exc}", flush=True)
                self._say(f"{messages.GUARDIAN_CODIGO}\n\nNúmero: {codigo}",
                          send_after=ahora + timedelta(seconds=PAUSA_ORIENTACION))
            self.db.audit("guardian", "nivel_2")

    # --------------------------------------------------------- nivel 3

    def _nivel_3(self, state) -> None:
        """Qué corresponde ahora: silencio de tregua, ráfaga o goteo.

        El orden importa. La tregua se mira primero, así que si los 70
        minutos se cumplen en medio de una tregua, el cambio de modo espera
        a que termine: la tregua promete silencio y ese silencio no se rompe
        ni para avisar. El reloj de los 70, eso sí, sigue corriendo igual.
        """
        if state["tregua_hasta"] and not is_due(state["tregua_hasta"]):
            return

        if self._paso_a_bajo(state):
            return

        if state["modo"] == "bajo":
            if is_due(state["next_at"]):
                self._mensaje_bajo(state)
            return

        if is_due(state["next_at"]):
            self._insistir(state)

    def _paso_a_bajo(self, state) -> bool:
        """¿Se cumplieron los 70 minutos? Baja el volumen, no cierra nada."""
        if state["modo"] == "bajo":
            return False
        inicio = from_iso(state["intervencion_at"])
        ahora = now_local()
        if not inicio or ahora < inicio + timedelta(minutes=INTERVENCION_MINUTOS):
            return False

        with self.db.transaction():
            self._update(
                state["event_id"], modo="bajo",
                next_at=iso(ahora + timedelta(minutes=BAJA_FRECUENCIA_MINUTOS)),
                tregua_code_hash=None, tregua_code_hasta=None,
            )
            self._cortar_rafaga()
            self._say(
                messages.guardian_baja_frecuencia(self._label(state["title"])),
                buttons=messages.BOTONES_LISTO,
            )
            self.db.audit("guardian", "baja_frecuencia")
        return True

    def _mensaje_bajo(self, state) -> None:
        """Un mensaje por hora. Ni ráfaga, ni escalada de vuelta."""
        ahora = now_local()
        with self.db.transaction():
            self._update(
                state["event_id"], last_sent=iso(ahora),
                next_at=iso(ahora + timedelta(minutes=BAJA_FRECUENCIA_MINUTOS)),
            )
            self._say(
                messages.guardian_sigue_pendiente(self._label(state["title"])),
                buttons=messages.BOTONES_LISTO,
            )

    def _cortar_rafaga(self) -> None:
        """Borra los mensajes de ráfaga programados que aún no salieron.

        Sin esto, empezar una tregua dejaría cayendo los que ya estaban en la
        cola con `send_after`, y el silencio prometido no sería silencio.
        """
        marcas = ",".join("?" * len(messages.GUARDIAN_INSISTE))
        self.db.execute(
            f"DELETE FROM outbox WHERE sent_at IS NULL AND text IN ({marcas})",
            messages.GUARDIAN_INSISTE,
        )

    # ----------------------------------------------------- tregua de 11 min

    def _pedir_tregua(self, state) -> bool:
        """Muestra la secuencia. Todavía no concede nada."""
        if (state["phase"] != "insiste" or state["modo"] == "bajo"
                or int(state["rafagas"] or 0) < TREGUA_RAFAGA
                or (state["tregua_hasta"] and not is_due(state["tregua_hasta"]))):
            with self.db.transaction():
                self._say(messages.GUARDIAN_TREGUA_VIEJA)
            return True

        if state["tregua_code_hash"] and not is_due(state["tregua_code_hasta"]):
            with self.db.transaction():
                self._say(messages.GUARDIAN_TREGUA_PENDIENTE)
            return True

        codigo = _codigo_tregua()
        ahora = now_local()
        destino = self.config.evidence_dir.parent / "guardian"
        # El nombre del archivo NO lleva la secuencia. Se borra al enviarse,
        # pero mientras existe no tiene por qué decir lo que muestra.
        imagen = destino / f"tregua-{int(ahora.timestamp())}.png"

        with self.db.transaction():
            self._update(
                state["event_id"],
                tregua_code_hash=_hash_codigo(state["event_id"], codigo),
                tregua_code_hasta=iso(
                    ahora + timedelta(minutes=TREGUA_CODIGO_MINUTOS)
                ),
            )
            texto = messages.guardian_tregua_codigo(
                TREGUA_MINUTOS, TREGUA_CODIGO_MINUTOS)
            try:
                make_text_image(codigo, imagen)
                self.db.enqueue(
                    self.config.owner_chat_id, texto,
                    photo_path=str(imagen), delete_photo=True,
                )
            except Exception as exc:
                # Si el dibujo falla, la tregua se ofrece igual: dejarte sin
                # salida en el peor momento es peor que perder la fricción.
                print(f"[guardian] no pude dibujar la tregua: {exc}", flush=True)
                self._say(f"{texto}\n\n{codigo}")
            self.db.audit("guardian", "tregua_pedida")
        return True

    def _conceder_tregua(self, state) -> None:
        """Once minutos de silencio real. El reloj de los 70 sigue corriendo."""
        ahora = now_local()
        with self.db.transaction():
            self._update(
                state["event_id"],
                tregua_hasta=iso(ahora + timedelta(minutes=TREGUA_MINUTOS)),
                tregua_code_hash=None, tregua_code_hasta=None,
                # La tregua cierra el ciclo de ráfagas y abre uno nuevo: el
                # contador vuelve a cero, así la opción se vuelve a ofrecer
                # en la segunda ráfaga del ciclo que viene. No hay límite de
                # una tregua por evento; el límite son los 70 minutos, y
                # `intervencion_at` no se toca acá justamente por eso.
                rafagas=0,
                # Al terminar la tregua se retoma lo que toque en ese
                # momento, sin recuperar los escalones que se perdieron.
                next_at=iso(ahora + timedelta(minutes=TREGUA_MINUTOS)),
            )
            self._cortar_rafaga()
            self._say(messages.guardian_tregua_ok(TREGUA_MINUTOS))
            self.db.audit("guardian", "tregua")

    def _insistir(self, state, primera: bool = False) -> None:
        """Una ráfaga corta y después cinco minutos de silencio real.

        La ráfaga siempre dura lo mismo. No se acelera ni se alarga con las
        repeticiones: este es el techo, y no hay nivel 4.
        """
        ahora = now_local()
        fin_rafaga = ahora + timedelta(
            seconds=(RAFAGA_MENSAJES - 1) * RAFAGA_PASO
        )
        rafagas = int(state["rafagas"] or 0) + 1

        with self.db.transaction():
            campos = dict(
                phase="insiste", rafagas=rafagas,
                code_hash=None, last_sent=iso(ahora),
                next_at=iso(fin_rafaga + timedelta(minutes=SILENCIO_NIVEL_3)),
            )
            if not state["intervencion_at"]:
                # El reloj de los 70 minutos arranca acá y no se reinicia
                # nunca: ni por otra ráfaga, ni por una respuesta, ni por
                # una tregua. Pertenece al evento, no al mensaje.
                campos["intervencion_at"] = iso(ahora)
            self._update(state["event_id"], **campos)
            # Recuerda el último texto del banco, no el del nombre: si no, el
            # mensaje con la tarea corta el hilo y el genérico que le sigue
            # puede repetir el que vino justo antes.
            previo = None
            for indice in range(RAFAGA_MENSAJES):
                # El segundo lleva el nombre del evento: para entonces la
                # pantalla ya está mirada y la pregunta es cuál era la tarea.
                if indice == 1:
                    texto = messages.guardian_insiste_tarea(
                        self._label(state["title"])
                    )
                else:
                    texto = previo = _sin_repetir(previo)
                # La tregua se ofrece una sola vez, en el último mensaje de
                # la segunda ráfaga. En la primera todavía no sabes si la
                # necesitas; en todas sería la salida por defecto.
                ultimo = indice == RAFAGA_MENSAJES - 1
                self._say(
                    texto,
                    buttons=(messages.BOTONES_LISTO_TREGUA
                             if ultimo and rafagas == TREGUA_RAFAGA
                             else messages.BOTONES_LISTO),
                    send_after=ahora + timedelta(seconds=indice * RAFAGA_PASO),
                )
            if primera:
                self.db.audit("guardian", "nivel_3")

    # ------------------------------------------------- entrada del código

    def _tregua_texto(self, state, limpio: str) -> bool:
        """Compara exacto: ni parcial, ni ignorando mayúsculas."""
        if is_due(state["tregua_code_hasta"]):
            with self.db.transaction():
                self._update(state["event_id"], tregua_code_hash=None,
                             tregua_code_hasta=None)
                self._say(messages.GUARDIAN_TREGUA_EXPIRADA)
            return True

        if state["tregua_code_hash"] != _hash_codigo(state["event_id"], limpio):
            # Reintentar mientras la ventana siga abierta. No es un sistema
            # de bloqueo por intentos: el límite es el reloj, no los errores.
            with self.db.transaction():
                self._say(messages.GUARDIAN_TREGUA_MAL)
            return True

        self._conceder_tregua(state)
        return True

    def handle_text(self, text: str) -> bool:
        """Sólo se queda con el texto si es un código que está esperando."""
        state = self._active()
        if not state:
            return False

        limpio = (text or "").strip()

        # La secuencia de la tregua se reconoce por su largo exacto, así un
        # texto cualquiera no se come una respuesta que no le tocaba.
        if (state["phase"] == "insiste" and state["tregua_code_hash"]
                and len(limpio) == TREGUA_CODIGO_LARGO):
            return self._tregua_texto(state, limpio)

        if state["phase"] != "codigo":
            return False

        if not re.fullmatch(r"\d{4}", limpio):
            return False

        if state["code_hash"] != _hash_codigo(state["event_id"], limpio):
            with self.db.transaction():
                self._say(messages.GUARDIAN_CODIGO_MAL)
            return True

        # El código confirma que miraste, no que hiciste la tarea. Por eso
        # vuelve a mostrarla: cerrar sigue siendo cosa de /listo.
        with self.db.transaction():
            self._update(state["event_id"], phase="confirmado",
                         code_hash=None, last_sent=iso(now_local()))
            self._say(
                messages.guardian_atencion_confirmada(self._label(state["title"])),
                buttons=messages.BOTONES_LISTO,
            )
            self.db.audit("guardian", "atencion_confirmada")
        return True

    def _done(self, state) -> None:
        with self.db.transaction():
            self._update(
                state["event_id"], phase="done", is_active=0,
                minutos_en_rescate=0, rescue_started_at=None,
                next_at=None, code_hash=None,
                intervencion_at=None, rafagas=0, modo=None,
                tregua_hasta=None, tregua_code_hash=None,
                tregua_code_hasta=None,
            )
            # Corta la ráfaga en curso: los mensajes que quedaban programados
            # ya no tienen sentido y llegarían después del /listo.
            self._cortar_rafaga()
            self._say(random.choice(messages.MENSAJES_CIERRE))
            self.db.audit("guardian", "done")

    # ------------------------------------------------------------ comandos

    def handle_command(self, command: str, raw_text: str) -> bool:
        state = self._active()
        if not state:
            return False

        phase = state["phase"]

        if command == "/listo":
            # Mientras espera el código, /listo no puede saltárselo: si
            # cerrara, la imagen sería un adorno. En el resto sí cierra.
            if phase == "codigo":
                with self.db.transaction():
                    self._say(messages.GUARDIAN_CODIGO_PENDIENTE)
                return True
            self._done(state)
            return True

        if command == "/guardian_tregua":
            return self._pedir_tregua(state)

        # Desde el nivel 2, /ok y /reinicio se aceptan y se ignoran a
        # propósito: no hay más que negociar.
        if phase in ("codigo", "confirmado", "insiste"):
            return command in ("/ok", "/reinicio")

        if command == "/ok" and phase == "brake":
            with self.db.transaction():
                self._update(
                    state["event_id"], phase="truce",
                    truce_until=iso(now_local() + timedelta(
                        minutes=self.config.duracion_tregua_minutes)),
                )
            return True

        if command == "/reinicio" and phase == "check":
            with self.db.transaction():
                self._update(
                    state["event_id"], phase="restart_truce",
                    restart_until=iso(now_local() + timedelta(
                        minutes=self.config.tolerancia_chequeo_minutes)),
                )
                self._say(messages.MARGEN_DE_GRACIA)
            return True

        return False

    # --------------------------------------------- las cuatro decisiones

    def handle_cola_callback(self, callback: dict) -> bool:
        data = str(callback.get("data") or "")
        partes = data.split(":")
        if len(partes) < 3:
            return False
        accion = partes[1]
        try:
            rid = int(partes[2])
        except ValueError:
            return False

        mensaje = callback.get("message") or {}
        message_id = mensaje.get("message_id")

        # Los recordatorios dejan varios mensajes con botones en el chat. Si el
        # que se tocó ya no es el que está esperando decisión, no se actúa
        # sobre otro evento: se dice que ese botón quedó viejo.
        actual = self._en_decision()
        fila = self.db.one(
            "SELECT rowid AS rid, * FROM guardian_events WHERE rowid = ?", (rid,)
        )
        if not fila or not actual or actual["event_id"] != fila["event_id"]:
            with self.db.transaction():
                self._say(messages.COLA_BOTON_EXPIRADO)
            return True

        if accion == "ahora":
            self._activar(fila)
            return True

        if accion == "despues":
            self._despues(fila)
            return True

        if accion == "descartar":
            self._descartar(fila)
            return True

        return False

    def _despues(self, fila) -> None:
        """Al final de la fila, y en espera para no volver a saltar enseguida."""
        maximo = self.db.one(
            "SELECT COALESCE(MAX(queue_seq), 0) AS m FROM guardian_events"
        )
        with self.db.transaction():
            self._update(
                fila["event_id"], phase="queued", is_active=0,
                queue_seq=int(maximo["m"]) + 1,
                decision_at=None, decision_step=0,
                decision_next_at=iso(
                    now_local() + timedelta(minutes=DESPUES_MINUTOS)
                ),
            )
            self._say(messages.cola_despues(fila["title"]), parse_mode="HTML")
            self.db.audit("guardian", "cola_despues", fila["title"])

    def _descartar(self, fila) -> None:
        """Cierre explícito. La fila queda: es historial, no basura."""
        with self.db.transaction():
            self._update(
                fila["event_id"], phase="discarded", is_active=0,
                queue_seq=None, decision_at=None, decision_step=0,
                decision_next_at=None, next_at=None, code_hash=None,
            )
            self._say(messages.cola_descartado(fila["title"]), parse_mode="HTML")
            self.db.audit("guardian", "cola_descartado", fila["title"])

    # ------------------------------------------------------------ auxiliares

    def cancel_active(self) -> bool:
        state = self._active()
        if not state:
            return False
        with self.db.transaction():
            self._update(state["event_id"], phase="done", is_active=0,
                         minutos_en_rescate=0, rescue_started_at=None)
        return True

    def reset(self) -> None:
        self.db.execute("DELETE FROM guardian_events")
        # Sin eventos no hay cola: sus dos marcas quedarían mintiendo.
        self.db.set_state(COLA_AVISO_KEY, None)
        self.db.set_state(COLA_HUBO_KEY, False)

    def cleanup_old_events(self) -> None:
        cutoff = iso(now_local() - timedelta(days=2))
        self.db.execute(
            "DELETE FROM guardian_events WHERE phase = 'done' AND start_at < ?",
            (cutoff,),
        )

    def status_text(self) -> str:
        # Sólo aparece cuando hay algo esperando: sin cola, /estado dice
        # exactamente lo que decía antes.
        pendientes = self._pendientes()
        cola = f"\n📥 Pendientes: {pendientes}" if pendientes else ""

        state = self._active()
        if not state:
            return f"Mástil Calendario: sin evento activo.{cola}"
        etiqueta = {
            "brake": "Nivel 1 — aviso",
            "truce": "Tregua",
            "check": "Chequeo",
            "restart_truce": "Margen de gracia",
            "codigo": "Nivel 2 — esperando el código",
            "confirmado": "Atención confirmada — falta /listo",
            "insiste": "Nivel 3 — ráfaga y silencio",
        }.get(state["phase"], state["phase"])

        lineas = [
            "Mástil Calendario:",
            f"Evento: {self._label(state['title'])}",
            f"Fase: {etiqueta}",
        ]
        if state["next_at"]:
            lineas.append(f"Próximo paso: {clock(from_iso(state['next_at']))}")
        return "\n".join(lineas) + cola

    def admin_test(self, kind: str) -> None:
        """Crea un evento sintético para probar una fase sin esperar a Calendar."""
        titulo = {
            "brake": f"{self.config.prefix} TEST FRENO",
            "check": f"{self.config.prefix} TEST CHEQUEO",
            "rescue": f"{self.config.prefix} TEST NIVEL 2",
            "rescue_fast": f"{self.config.prefix} TEST NIVEL 3",
        }[kind]

        now = now_local()
        event_id = f"__admin__|{now.isoformat()}|{titulo}"

        with self.db.transaction():
            self.db.execute("UPDATE guardian_events SET is_active = 0")
            self.db.execute(
                """
                INSERT OR REPLACE INTO guardian_events
                    (event_id, title, start_at, phase, is_active, created_at, updated_at)
                VALUES (?, ?, ?, 'brake', 1, ?, ?)
                """,
                (event_id, titulo, iso(now), iso(now), iso(now)),
            )

        state = self._active()
        if kind == "brake":
            self._send_brake(state)
        elif kind == "check":
            self._send_check(state)
        elif kind == "rescue":
            self._enter_codigo(state)
        elif kind == "rescue_fast":
            self._insistir(state, primera=True)
