"""Pomodoro: bloques de trabajo con corte obligatorio.

Su objetivo real no es medir 20 minutos: es **obligar a cortar** cuando el
bloque termina. Por eso el descanso no empieza solo — hay que mandar /descanso.
Un descanso automático se ignora sin levantarse de la silla.

`/pomo_estado` es estrictamente de sólo lectura: no adelanta, no reinicia y no
detiene ninguna fase. Es el único comando con esa garantía explícita.
"""

from __future__ import annotations

import random
from datetime import timedelta

import messages
from core.scheduler import (
    from_iso, is_due, iso, now_local, rescue_interval, remaining_seconds, should_send,
)


# Descanso recomendado segun cuanto dura el bloque de trabajo.
#
# Es una TABLA, no una formula: se lee de un vistazo, se discute y se edita
# a mano. No hay ninguna pretension de que estos numeros sean los correctos
# para cualquiera — lo que esta respaldado es cortar los periodos largos, no
# una cifra exacta por persona. Son el punto de partida de Mastil, y son una
# sugerencia: nada obliga a tomarla.
#
# Cada par es (hasta_minutos_de_trabajo, minutos_de_descanso).
DESCANSO_RECOMENDADO = ((25, 5), (45, 7), (60, 10), (90, 15))
DESCANSO_TOPE = 15


def descanso_recomendado(work_minutes: int) -> int:
    """Minutos de descanso sugeridos para un bloque de `work_minutes`.

    Por tramos y hacia arriba: un bloque de 30 cae en el tramo de 45 y
    sugiere 7. De los dos errores posibles, descansar de mas es el barato.

    Determinista y sin dependencias: ninguna IA interviene acá, igual que en
    el resto de los tiempos del sistema.
    """
    for tope, descanso in DESCANSO_RECOMENDADO:
        if work_minutes <= tope:
            return descanso
    return DESCANSO_TOPE


class PomodoroModule:
    def __init__(self, config, db):
        self.config = config
        self.db = db

    # ---------------------------------------------------------------- datos

    def _get(self):
        return self.db.one("SELECT * FROM pomodoro_session WHERE id = 1")

    def _update(self, **fields) -> None:
        if not fields:
            return
        columns = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(
            f"UPDATE pomodoro_session SET {columns}, updated_at = ? WHERE id = 1",
            (*fields.values(), iso(now_local())),
        )

    def _say(self, text: str, buttons=None) -> None:
        self.db.enqueue(self.config.owner_chat_id, text, buttons=buttons)

    def _label(self, focus) -> str:
        return messages.task_label(focus or "Foco Pomodoro", self.config.prefix)

    # ------------------------------------------------------------ comandos

    def handle_command(self, command: str, raw_text: str) -> bool:
        if raw_text.startswith("/pomodoro"):
            return self._start(raw_text)
        if command == "/stop":
            self.reset(announce=True)
            return True
        if command == "/descanso":
            return self._break_command()
        if command == "/pomo_estado":
            self._say(self.status_text())
            return True

        session = self._get()
        if not session["active"]:
            return False

        if command == "/listo" and session["phase"] in ("return_check", "rescue"):
            self._next_block()
            return True

        if command == "/reinicio" and session["phase"] == "return_check":
            with self.db.transaction():
                self._say(messages.MARGEN_DE_GRACIA)
            self._enter_rescue()
            return True

        return False

    def _start(self, raw_text: str) -> bool:
        argument = raw_text.replace("/pomodoro", "", 1).strip()

        focus = "Foco Pomodoro"
        work_minutes = self.config.pomodoro_trabajo_minutes

        if argument:
            if argument.isdigit():
                work_minutes = int(argument)

                if not 1 <= work_minutes <= 240:
                    with self.db.transaction():
                        self._say(messages.POMODORO_DURACION_INVALIDA)
                    return True
            else:
                focus = argument

        with self.db.transaction():
            self._update(
                next_cycle=1,
                work_minutes=work_minutes,
            )
            self._start_work(focus=focus, cycle=1)

        return True

    def _start_work(self, focus: str, cycle: int) -> None:
        session = self._get()
        work_minutes = int(
            session["work_minutes"]
            or self.config.pomodoro_trabajo_minutes
        )

        self._update(
            active=1,
            phase="work",
            focus=focus,
            cycle=cycle,
            phase_until=iso(
                now_local() + timedelta(minutes=work_minutes)
            ),
            return_until=None,
            rescue_started_at=None,
            last_sent=None,
            minutos_en_rescate=0,
        )

        self._say(
            messages.pomodoro_iniciado(
                self._label(focus),
                cycle,
                self.config.pomodoro_ciclos,
                work_minutes,
                descanso_recomendado(work_minutes),
            )
        )

        self.db.audit(
            "pomodoro",
            "start_work",
            f"ciclo {cycle}, {work_minutes} minutos",
        )
    def _break_command(self) -> bool:
        session = self._get()
        with self.db.transaction():
            if session["active"] and session["phase"] == "cut_alert":
                self._start_break()
            elif session["active"]:
                self._say(messages.POMODORO_DESCANSO_FUERA_DE_TURNO)
            else:
                self._say(messages.POMODORO_SIN_SESION)
        return True

    def _start_break(self) -> None:
        session = self._get()
        cycle = int(session["cycle"] or 1)

        if cycle < self.config.pomodoro_ciclos:
            duration = timedelta(seconds=self.config.pomodoro_descanso_corto_seconds)
            next_cycle, kind = cycle + 1, "descanso corto"
        else:
            duration = timedelta(minutes=self.config.pomodoro_descanso_largo_minutes)
            next_cycle, kind = 1, "descanso largo"

        self._update(phase="break", next_cycle=next_cycle,
                     phase_until=iso(now_local() + duration), last_sent=None)
        self._say(messages.pomodoro_descanso(self._label(session["focus"]), kind))

    def _next_block(self) -> None:
        session = self._get()
        with self.db.transaction():
            self._update(minutos_en_rescate=0, rescue_started_at=None, last_sent=None)
            self._say(random.choice(messages.MENSAJES_CIERRE))
            self._start_work(
                focus=session["focus"] or "Foco Pomodoro",
                cycle=int(session["next_cycle"] or 1),
            )

    def _enter_rescue(self) -> None:
        with self.db.transaction():
            self._update(phase="rescue", last_sent=None,
                         rescue_started_at=iso(now_local()), minutos_en_rescate=0)
        self._send_rescue()

    def _send_rescue(self) -> None:
        session = self._get()
        interval, minutos = rescue_interval(
            session["rescue_started_at"],
            self.config.intervalo_rescate_inicial_seconds,
            self.config.intervalo_rescate_acelerado_seconds,
            self.config.rescate_acelera_despues_minutes,
        )
        if not should_send(session["last_sent"], interval):
            if minutos != session["minutos_en_rescate"]:
                with self.db.transaction():
                    self._update(minutos_en_rescate=minutos)
            return
        with self.db.transaction():
            self._update(last_sent=iso(now_local()), minutos_en_rescate=minutos)
            self._say(random.choice(messages.FRASES_RESCATE))

    def _send_cut_alert(self) -> None:
        session = self._get()
        if session["phase"] != "cut_alert":
            with self.db.transaction():
                self._update(phase="cut_alert", last_sent=None)
            session = self._get()
        if not should_send(session["last_sent"], 60):
            return
        trabajo = int(session["work_minutes"]
                      or self.config.pomodoro_trabajo_minutes)
        with self.db.transaction():
            self._update(last_sent=iso(now_local()))
            self._say(
                messages.POMODORO_CORTE + "\n\n"
                + messages.pomodoro_sugerencia(descanso_recomendado(trabajo))
            )

    def _send_return_check(self) -> None:
        with self.db.transaction():
            self._update(
                phase="return_check",
                return_until=iso(now_local() + timedelta(
                    minutes=self.config.pomodoro_tolerancia_retorno_minutes)),
            )
            self._say(messages.POMODORO_RETORNO, buttons=messages.BOTONES_CHEQUEO)

    # ------------------------------------------------------------------ tick

    def tick(self) -> None:
        session = self._get()
        if not session["active"]:
            return

        phase = session["phase"]

        if phase == "work":
            if is_due(session["phase_until"]):
                self._send_cut_alert()
        elif phase == "cut_alert":
            self._send_cut_alert()
        elif phase == "break":
            if is_due(session["phase_until"]):
                self._send_return_check()
        elif phase == "return_check":
            if is_due(session["return_until"]):
                self._enter_rescue()
        elif phase == "rescue":
            self._send_rescue()

    # ------------------------------------------------------------ auxiliares

    def reset(self, announce: bool = True) -> None:
        with self.db.transaction():
            self._update(
                active=0, phase=None, focus=None, cycle=1, next_cycle=1,
                work_minutes=self.config.pomodoro_trabajo_minutes,
                phase_until=None, return_until=None, rescue_started_at=None,
                last_sent=None, minutos_en_rescate=0,
            )
            if announce:
                self._say(messages.POMODORO_DETENIDO)

    def status_text(self) -> str:
        """SÓLO LECTURA. No cambia fases, no reinicia timers, no dispara nada."""
        session = self._get()
        if not session["active"]:
            return messages.POMODORO_ESTADO_VACIO

        phase = session["phase"]
        etiqueta = phase
        tiempo = ""

        if phase == "work":
            etiqueta = "Trabajo profundo"
            restante = int(max(0, remaining_seconds(session["phase_until"])))
            trabajo = int(session["work_minutes"]
                          or self.config.pomodoro_trabajo_minutes)
            tiempo = (
                f"Tiempo restante del bloque: {restante // 60:02d}:{restante % 60:02d}"
                "\n" + messages.pomodoro_sugerencia(
                    descanso_recomendado(trabajo))
            )
        elif phase == "cut_alert":
            etiqueta = "Alerta de Corte (Esperando inicio de descanso)"
            if int(session["cycle"] or 1) < self.config.pomodoro_ciclos:
                corto = self.config.pomodoro_descanso_corto_seconds
                tiempo = (
                    "Tiempo para siguiente Pomodoro: descanso pendiente. "
                    f"Al presionar /descanso quedarán {corto // 60:02d}:{corto % 60:02d} "
                    "antes del próximo bloque."
                )
            else:
                largo = self.config.pomodoro_descanso_largo_minutes
                tiempo = (
                    "Tiempo para siguiente Pomodoro: descanso largo pendiente. "
                    f"Al presionar /descanso quedarán {largo:02d}:00 antes del próximo bloque."
                )
        elif phase == "break":
            etiqueta = "Descanso físico obligatorio"
            restante = int(max(0, remaining_seconds(session["phase_until"])))
            tiempo = f"Tiempo para siguiente Pomodoro: {restante // 60:02d}:{restante % 60:02d}"
        elif phase == "return_check":
            etiqueta = "Chequeo de Retorno"
            restante = int(max(0, remaining_seconds(session["return_until"])))
            tiempo = f"Ventana para responder: {restante // 60:02d}:{restante % 60:02d}"
        elif phase == "rescue":
            etiqueta = "Rescate activo"
            tiempo = "El rescate sigue activo hasta que presiones /listo."

        lineas = [
            "Estado Pomodoro:",
            f"Foco: {self._label(session['focus'])}",
            f"Fase: {etiqueta}",
            f"Ciclo: {session['cycle']} de {self.config.pomodoro_ciclos}",
            f"Duración de cada bloque: {session['work_minutes']} minutos",
        ]
        if phase == "rescue":
            lineas.append(f"Minutos en rescate: {session['minutos_en_rescate']}")
        if tiempo:
            lineas.append(tiempo)
        return "\n".join(lineas)
