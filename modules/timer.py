"""Temporizador. Sin interpretación conductual: cuenta y avisa.

Es el módulo más simple y el único sin opinión sobre lo que hace la persona.
Soporta razón textual (`/timer 20 ir a comer`), hasta 3 avisos intermedios y
pausa/reanudación.

Tres modalidades sobre **un solo motor**, no tres motores:

    ⏳ countdown   /timer 35          avisa dentro de 35 minutos
    🕐 fixed       /timer_a 21:40     avisa una vez, a esa hora
    🔁 repeating   /timer_cada 50     avisa cada 50 minutos

Lo único que cambia entre las tres es **cómo se calcula `ends_at`**. De ahí
en adelante el ciclo es el mismo: comparar contra el reloj y avisar. Por eso
no hay tres implementaciones que mantener sincronizadas.

La exclusividad —un solo timer activo— no la impone ninguna regla de código:
la impone el esquema, con una tabla de fila única. No hay forma de tener dos.

Al reanudar se desplazan inicio y fin por la duración de la pausa, así que los
avisos pendientes conservan su posición relativa. Una alarma ya disparada no se
pausa: para eso está /apagar.
"""

from __future__ import annotations

import json
import re

import messages
from core.scheduler import (
    clock, format_duration, from_iso, iso, now_local, remaining_seconds,
)


# Tope del repetitivo. No existe "para siempre": un aviso que no puede
# terminar solo termina siendo ruido, y el ruido enseña a ignorar el
# sistema entero — que es justo lo que ningún módulo puede permitirse.
TOPE_POR_DEFECTO = 240      # 4 horas
TOPE_MAXIMO = 1440          # una jornada

COUNTDOWN = "countdown"
FIXED = "fixed"
REPEATING = "repeating"


class TimerModule:
    def __init__(self, config, db):
        self.config = config
        self.db = db
        # Creación esperando REEMPLAZAR/CONSERVAR. Vive en memoria a
        # propósito: si el proceso se cae con la pregunta en pantalla, lo
        # correcto es que no haya quedado nada creado.
        self._pendiente = None

    # ---------------------------------------------------------------- datos

    def _get(self):
        return self.db.one("SELECT * FROM timer WHERE id = 1")

    def _update(self, **fields) -> None:
        if not fields:
            return
        columns = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(
            f"UPDATE timer SET {columns}, updated_at = ? WHERE id = 1",
            (*fields.values(), iso(now_local())),
        )

    def _clear(self) -> None:
        self._update(
            active=0, status="idle", duration_minutes=0, reason="",
            started_at=None, ends_at=None, paused_at=None,
            milestones="[]", fired_milestones="[]",
            ringing_started_at=None, last_alarm_sent=None,
            modo=COUNTDOWN, interval_minutes=0,
        )

    def _say(self, text: str, buttons=None, send_after=None,
             parse_mode: str | None = None) -> None:
        self.db.enqueue(
            self.config.owner_chat_id, text,
            buttons=buttons, send_after=send_after, parse_mode=parse_mode,
        )

    # -------------------------------------------------------------- botones

    def _buttons(self, ringing: bool = False, paused: bool = False):
        if ringing:
            return [("⏱ /tm", "/tm"), ("🔕 /apagar", "/apagar")]
        if paused:
            return [("⏱ /tm", "/tm"), ("▶️ reanudar", "/timer_reanudar"),
                    ("✖️ cancelar", "/timer_cancelar")]
        return [("⏱ /tm", "/tm"), ("⏸ pausar", "/timer_pausar"),
                ("✖️ cancelar", "/timer_cancelar")]

    def _milestones_text(self, timer) -> str:
        milestones = json.loads(timer["milestones"] or "[]")
        fired = set(json.loads(timer["fired_milestones"] or "[]"))
        if not milestones:
            return "Sin avisos intermedios."
        return ", ".join(
            f"{m}m {'✅' if m in fired else 'pendiente'}" for m in milestones
        )

    # ------------------------------------------------------------ comandos

    def handle_command(self, command: str, raw_text: str) -> bool:
        if command == "/timer":
            return self.start(raw_text)
        if command == "/tm":
            return self.status()
        if command == "/timer_pausar":
            return self.pause()
        if command == "/timer_reanudar":
            return self.resume()
        if command == "/apagar":
            return self.turn_off()
        if command == "/timer_cancelar":
            return self.cancel()
        if command == "/timer_a":
            return self.start_fixed(raw_text)
        if command == "/timer_cada":
            return self.start_repeating(raw_text)
        if command == "/timer_reemplazar":
            return self._resolver_reemplazo(True)
        if command == "/timer_conservar":
            return self._resolver_reemplazo(False)
        return False

    # --------------------------------------- un solo timer a la vez

    def _confirmar_reemplazo(self, plan: dict) -> bool:
        """Hay uno corriendo: se pregunta antes de pisarlo.

        Antes reemplazaba en silencio. Perder sin aviso el timer que estabas
        esperando es la clase de sorpresa que hace desconfiar de la
        herramienta entera.
        """
        self._pendiente = plan
        actual = self._get()
        with self.db.transaction():
            self._say(
                f"{messages.TIMER_YA_HAY}{chr(10)}{chr(10)}"
                f"Ahora: {self._resumen(actual)}{chr(10)}"
                f"Nuevo: {plan['detalle']}",
                buttons=messages.TIMER_BOTONES_REEMPLAZO,
            )
        return True

    def _resolver_reemplazo(self, reemplazar: bool) -> bool:
        plan, self._pendiente = self._pendiente, None
        if not plan:
            with self.db.transaction():
                self._say(messages.TIMER_NADA_QUE_REEMPLAZAR)
            return True
        if not reemplazar:
            with self.db.transaction():
                self._say(messages.TIMER_CONSERVADO, buttons=self._buttons())
            return True
        self._crear(plan, reemplazo=True)
        return True

    def _resumen(self, timer) -> str:
        """Una línea que describe el timer actual, sea del modo que sea."""
        modo = timer["modo"] or COUNTDOWN
        ends = from_iso(timer["ends_at"])
        if modo == REPEATING:
            fin = self._fin_repetido(timer)
            return (f"{messages.TIMER_MODOS[REPEATING]}, cada "
                    f"{timer['interval_minutes']} min "
                    f"(próximo {clock(ends)}, hasta {clock(fin)})")
        if modo == FIXED:
            return f"{messages.TIMER_MODOS[FIXED]} las {clock(ends)}"
        return (f"{messages.TIMER_MODOS[COUNTDOWN]}, restan "
                f"{format_duration(remaining_seconds(ends))}")

    def _fin_repetido(self, timer):
        """Cuándo deja de avisar. Sale de `started_at` + `duration_minutes`,
        que en este modo es el largo de la ventana entera, no de un tramo."""
        from datetime import timedelta

        inicio = from_iso(timer["started_at"])
        if not inicio:
            return None
        return inicio + timedelta(
            minutes=int(timer["duration_minutes"] or TOPE_POR_DEFECTO)
        )

    def resumen_actual(self) -> str:
        """La línea que el Panel muestra arriba. Vacía si no hay nada."""
        timer = self._get()
        return self._resumen(timer) if timer and timer["active"] else ""

    def _crear(self, plan: dict, reemplazo: bool = False) -> None:
        """El único lugar que escribe un timer nuevo.

        Los tres modos pasan por acá, y por eso no pueden divergir: lo que
        cada uno decide es sólo el `ends` que trae en su plan.
        """
        with self.db.transaction():
            self._update(
                active=1, status="running", modo=plan["modo"],
                duration_minutes=plan.get("duration", 0),
                interval_minutes=plan.get("interval", 0),
                reason=plan.get("reason", ""),
                started_at=iso(plan["ahora"]), ends_at=iso(plan["ends"]),
                paused_at=None,
                milestones=json.dumps(plan.get("milestones", [])),
                fired_milestones="[]",
                ringing_started_at=None, last_alarm_sent=None,
            )
            self._say(
                messages.timer_creado(plan["modo"], plan["detalle"], reemplazo),
                buttons=self._buttons(),
            )
            self.db.audit("timer", "start", plan["modo"])

    # ------------------------------------------------- modos nuevos

    def start_fixed(self, raw_text: str) -> bool:
        """`/timer_a 21:40`. Una vez, a esa hora, y se acabó.

        Deliberadamente mínimo: hora y nada más. Un título, una duración o
        una recurrencia lo convertirían en Calendar, que responde otra
        pregunta: "avísame a las 21:40" no es "tengo algo a las 21:40".
        """
        from datetime import timedelta

        partes = raw_text.strip().split()
        crudo = partes[1] if len(partes) > 1 else ""
        match = re.fullmatch(r"([01]?\d|2[0-3])[:.]([0-5]\d)", crudo)
        if not match:
            with self.db.transaction():
                if crudo:
                    self._say(messages.TIMER_HORA_INVALIDA)
                else:
                    self._say(messages.TIMER_USO_A, parse_mode="HTML")
            return True

        ahora = now_local().replace(microsecond=0)
        objetivo = ahora.replace(hour=int(match.group(1)),
                                 minute=int(match.group(2)), second=0)
        # Si esa hora ya pasó hoy, es la de mañana. No se pregunta: es la
        # única lectura razonable de "avísame a las 7".
        if objetivo <= ahora:
            objetivo = objetivo + timedelta(days=1)

        plan = {"modo": FIXED, "ahora": ahora, "ends": objetivo,
                "detalle": f"Aviso a las {clock(objetivo)}."}
        if self._get()["active"]:
            return self._confirmar_reemplazo(plan)
        self._crear(plan)
        return True

    def start_repeating(self, raw_text: str) -> bool:
        """`/timer_cada 50`. Un solo registro que se reprograma solo.

        No es una cadena de timers: es el mismo estado moviendo su `ends_at`
        hacia adelante cada vez que suena.
        """
        from datetime import timedelta

        partes = raw_text.strip().split()
        crudo = partes[1] if len(partes) > 1 else ""
        if not crudo:
            with self.db.transaction():
                self._say(messages.TIMER_USO_CADA, parse_mode="HTML")
            return True
        if not re.fullmatch(r"\d+", crudo) or not 1 <= int(crudo) <= 1440:
            with self.db.transaction():
                self._say(messages.TIMER_INTERVALO_INVALIDO)
            return True

        cada = int(crudo)
        # Segundo número: por cuánto rato. Si no viene —un botón viejo, un
        # comando a mano— se usa un tope conservador igual: nada que avise
        # puede quedar corriendo para siempre por descuido.
        crudo_tope = partes[2] if len(partes) > 2 else ""
        tope = int(crudo_tope) if re.fullmatch(r"\d+", crudo_tope) else TOPE_POR_DEFECTO
        tope = max(cada, min(tope, TOPE_MAXIMO))

        ahora = now_local().replace(microsecond=0)
        proximo = ahora + timedelta(minutes=cada)
        hasta = ahora + timedelta(minutes=tope)
        plan = {"modo": REPEATING, "ahora": ahora, "ends": proximo,
                "interval": cada, "duration": tope,
                "detalle": (f"Cada {cada} min hasta las {clock(hasta)}.\n"
                            f"Primer aviso a las {clock(proximo)}.")}
        if self._get()["active"]:
            return self._confirmar_reemplazo(plan)
        self._crear(plan)
        return True

    def start(self, raw_text: str) -> bool:
        parts = raw_text.strip().split()
        if len(parts) < 2:
            with self.db.transaction():
                self._say(messages.TIMER_USO, buttons=[("⏱ /tm", "/tm")])
            return True

        # Números primero, y desde la primera palabra todo es razón.
        numbers: list[int] = []
        reason_parts: list[str] = []
        for token in parts[1:]:
            if not reason_parts and re.fullmatch(r"-?\d+", token):
                numbers.append(int(token))
            else:
                reason_parts.append(token)

        if not numbers:
            with self.db.transaction():
                self._say(messages.TIMER_FALTA_DURACION)
            return True

        total = numbers[0]
        raw_milestones = numbers[1:]
        reason = " ".join(reason_parts).strip()

        if total <= 0 or total > 1440:
            with self.db.transaction():
                self._say(messages.TIMER_DURACION_INVALIDA)
            return True
        if len(reason) > 240:
            with self.db.transaction():
                self._say(messages.TIMER_RAZON_LARGA)
            return True
        if len(raw_milestones) > 3:
            with self.db.transaction():
                self._say(messages.TIMER_MUCHOS_AVISOS)
            return True

        milestones = sorted(set(raw_milestones))
        if any(m <= 0 or m >= total for m in milestones):
            with self.db.transaction():
                self._say(messages.TIMER_AVISOS_INVALIDOS)
            return True

        now = now_local().replace(microsecond=0)
        ends = now + __import__("datetime").timedelta(minutes=total)
        razon = messages.timer_razon(reason)
        detalle = (
            f"{total} minutos.\n"
            f"{razon + chr(10) if razon else ''}"
            f"Termina a las {clock(ends)}."
        )
        plan = {"modo": COUNTDOWN, "ahora": now, "ends": ends,
                "duration": total, "reason": reason,
                "milestones": milestones, "detalle": detalle}
        if self._get()["active"]:
            return self._confirmar_reemplazo(plan)
        self._crear(plan)
        return True

    def status(self) -> bool:
        timer = self._get()
        if not timer["active"]:
            with self.db.transaction():
                self._say(messages.TIMER_SIN_ACTIVO,
                          buttons=[("⏱ iniciar ejemplo", "/timer 30")])
            return True

        razon = messages.timer_razon(timer["reason"])
        bloque = f"{razon}\n" if razon else ""
        ends = from_iso(timer["ends_at"])

        with self.db.transaction():
            if timer["status"] == "paused":
                paused_at = from_iso(timer["paused_at"]) or now_local()
                restante = (ends - paused_at).total_seconds() if ends else 0
                self._say(
                    "⏸ Timer pausado.\n"
                    f"{bloque}"
                    f"Quedó congelado con: {format_duration(restante)}.\n"
                    f"Avisos: {self._milestones_text(timer)}\n\n"
                    "Usa /timer_reanudar para continuar.",
                    buttons=self._buttons(paused=True),
                )
            elif timer["status"] == "ringing":
                ringing_started = from_iso(timer["ringing_started_at"])
                excedido = -remaining_seconds(ends) if ends else 0
                auto = self.config.timer_autoapagado_seconds
                restante_auto = (
                    auto - (now_local() - ringing_started).total_seconds()
                    if ringing_started else auto
                )
                self._say(
                    "⏰ Timer sonando.\n"
                    f"{bloque}"
                    f"Tiempo excedido: {format_duration(excedido)}.\n"
                    f"Autoapagado en: {format_duration(restante_auto)}.\n\n"
                    "Usa /apagar para detener.",
                    buttons=self._buttons(ringing=True),
                )
            else:
                self._say(
                    "⏱ Timer activo.\n"
                    f"{bloque}"
                    f"{self._resumen(timer)}"
                    + (f"\nAvisos: {self._milestones_text(timer)}"
                       if (timer["modo"] or COUNTDOWN) == COUNTDOWN else ""),
                    buttons=self._buttons(),
                )
        return True

    def pause(self) -> bool:
        timer = self._get()
        with self.db.transaction():
            if not timer["active"]:
                self._say(messages.TIMER_SIN_PAUSAR)
                return True
            if timer["status"] == "paused":
                self._say(messages.TIMER_YA_PAUSADO, buttons=self._buttons(paused=True))
                return True
            if timer["status"] != "running":
                self._say(messages.TIMER_YA_SONANDO, buttons=self._buttons(ringing=True))
                return True
            if (timer["modo"] or COUNTDOWN) != COUNTDOWN:
                # Pausar una hora fija no significa nada, y pausar un
                # repetitivo es detenerlo: para eso ya está /timer_cancelar.
                self._say(messages.TIMER_PAUSA_SOLO_CUENTA,
                          buttons=self._buttons())
                return True

            now = now_local()
            restante = remaining_seconds(timer["ends_at"], now)
            self._update(status="paused", paused_at=iso(now))

            razon = messages.timer_razon(timer["reason"])
            self._say(
                "⏸ Timer pausado.\n"
                f"{razon + chr(10) if razon else ''}"
                f"Quedaron congelados: {format_duration(restante)}.\n\n"
                "Usa /timer_reanudar cuando quieras continuar.",
                buttons=self._buttons(paused=True),
            )
            self.db.audit("timer", "pause")
        return True

    def resume(self) -> bool:
        from datetime import timedelta

        timer = self._get()
        with self.db.transaction():
            if not timer["active"]:
                self._say(messages.TIMER_SIN_REANUDAR)
                return True
            if timer["status"] != "paused":
                self._say(messages.TIMER_NO_PAUSADO, buttons=self._buttons())
                return True

            now = now_local()
            paused_at = from_iso(timer["paused_at"]) or now
            pausa = max(0, (now - paused_at).total_seconds())
            started = from_iso(timer["started_at"]) or now
            ends = from_iso(timer["ends_at"]) or now

            # Desplazar inicio y fin: los avisos pendientes mantienen su lugar.
            nuevo_fin = ends + timedelta(seconds=pausa)
            self._update(
                started_at=iso(started + timedelta(seconds=pausa)),
                ends_at=iso(nuevo_fin),
                paused_at=None, status="running",
            )

            razon = messages.timer_razon(timer["reason"])
            self._say(
                "▶️ Timer reanudado.\n"
                f"{razon + chr(10) if razon else ''}"
                f"Ahora termina a las {clock(nuevo_fin)}.\n"
                "Los avisos pendientes siguen activos.",
                buttons=self._buttons(),
            )
            self.db.audit("timer", "resume")
        return True

    def cancel(self) -> bool:
        with self.db.transaction():
            if not self._get()["active"]:
                self._say(messages.TIMER_SIN_CANCELAR)
                return True
            self._clear()
            self._say(messages.TIMER_CANCELADO)
            self.db.audit("timer", "cancel")
        return True

    def turn_off(self) -> bool:
        timer = self._get()
        with self.db.transaction():
            if not timer["active"]:
                self._say(messages.TIMER_SIN_SONAR)
                return True
            if timer["status"] != "ringing":
                self._say(messages.TIMER_AUN_NO_SUENA, buttons=self._buttons())
                return True
            self._clear()
            self._say(messages.TIMER_APAGADO)
            self.db.audit("timer", "off")
        return True

    # ------------------------------------------------------------------ tick

    def tick(self) -> None:
        from datetime import timedelta

        timer = self._get()
        if not timer["active"]:
            return

        status = timer["status"]
        if status == "paused":
            return

        now = now_local()

        modo = timer["modo"] or COUNTDOWN

        # Los dos modos nuevos avisan UNA vez por vencimiento y no entran en
        # `ringing`: no hay alarma repetida ni autoapagado que apagar.
        if status == "running" and modo == REPEATING:
            fin = self._fin_repetido(timer)
            if fin and now >= fin:
                cada = int(timer["interval_minutes"] or 0) or 1
                tope = int(timer["duration_minutes"] or TOPE_POR_DEFECTO)
                with self.db.transaction():
                    self._clear()
                    self._say(
                        messages.timer_repetido_fin(cada, tope),
                        buttons=messages.timer_botones_otra_vez(cada, tope),
                        parse_mode="HTML",
                    )
                    self.db.audit("timer", "repeat_end")
                return

        if status == "running" and modo in (FIXED, REPEATING):
            ends = from_iso(timer["ends_at"])
            if not ends or now < ends:
                return
            if modo == FIXED:
                with self.db.transaction():
                    self._clear()
                    self._say(messages.timer_aviso_fijo(clock(ends)),
                              parse_mode="HTML")
                    self.db.audit("timer", "fixed_fire")
                return

            cada = int(timer["interval_minutes"] or 0) or 1
            # Tras un reinicio largo pueden haber vencido varios periodos.
            # Se avisa UNA vez y se salta al próximo futuro: recuperar los
            # atrasados sería una ráfaga que nadie pidió.
            proximo = ends
            while proximo <= now:
                proximo = proximo + timedelta(minutes=cada)
            with self.db.transaction():
                # `started_at` NO se toca: es el punto de referencia del vencimiento.
                self._update(ends_at=iso(proximo))
                self._say(
                    messages.timer_aviso_repetido(cada, clock(proximo)),
                    buttons=messages.TIMER_BOTONES_REPETITIVO,
                    parse_mode="HTML",
                )
                self.db.audit("timer", "repeat_fire")
            return

        if status == "running":
            started = from_iso(timer["started_at"])
            fired = set(json.loads(timer["fired_milestones"] or "[]"))

            for milestone in json.loads(timer["milestones"] or "[]"):
                if milestone in fired or not started:
                    continue
                if now >= started + timedelta(minutes=milestone):
                    self._burst(timer, milestone)
                    return

            if from_iso(timer["ends_at"]) and now >= from_iso(timer["ends_at"]):
                with self.db.transaction():
                    self._update(status="ringing", ringing_started_at=iso(now),
                                 last_alarm_sent=iso(now))
                    self._alarm(self._get())
            return

        if status == "ringing":
            ringing_started = from_iso(timer["ringing_started_at"])
            if ringing_started and (now - ringing_started).total_seconds() >= self.config.timer_autoapagado_seconds:
                with self.db.transaction():
                    self._clear()
                    self._say(messages.TIMER_AUTOAPAGADO)
                return

            last = from_iso(timer["last_alarm_sent"])
            if not last or (now - last).total_seconds() >= self.config.timer_alarma_cada_seconds:
                with self.db.transaction():
                    self._update(last_alarm_sent=iso(now))
                    self._alarm(timer)

    def _burst(self, timer, milestone: int) -> None:
        """Tres mensajes separados por unos segundos.

        El legacy los mandaba con `time.sleep(4)`, bloqueando el ciclo entero.
        Acá se encolan con `send_after`: el mismo efecto sin congelar a Mástil.
        """
        from datetime import timedelta

        total = timer["duration_minutes"]
        restante = total - milestone
        razon = messages.timer_razon(timer["reason"])
        bloque = f"{razon}\n" if razon else ""
        gap = self.config.timer_burst_gap_seconds
        now = now_local()

        textos = [
            f"🔔 Aviso de timer.\n{bloque}"
            f"Minuto {milestone} de {total}.\nRestan {restante} minutos.",
            f"⏱ Sigue corriendo el timer.\n{bloque}Consulta estado con /tm.",
            f"🔔 Aviso intermedio completado.\n{bloque}"
            f"El timer final sonará a las {clock(from_iso(timer['ends_at']))}.",
        ]

        with self.db.transaction():
            fired = json.loads(timer["fired_milestones"] or "[]")
            fired.append(milestone)
            self._update(fired_milestones=json.dumps(fired))
            for index, texto in enumerate(textos):
                self._say(
                    texto,
                    buttons=self._buttons(),
                    send_after=now + timedelta(seconds=index * gap),
                )

    def _alarm(self, timer) -> None:
        razon = messages.timer_razon(timer["reason"])
        self._say(
            "⏰ Timer terminado.\n"
            f"{razon + chr(10) if razon else ''}"
            "Usa /apagar para detener.\n"
            "Si no lo apagas, se apagará solo tras 6 minutos.",
            buttons=self._buttons(ringing=True),
        )
