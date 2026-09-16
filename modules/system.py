"""Control global: /admin, /estado, /suspender, /reanudar y las pruebas.

`/suspender_guardian` apaga SÓLO Guardian y deja el resto intacto: Calendar,
Vigía, Cola, Timer, Intervalos y Gmail siguen igual. Los eventos de Guardian
no se borran ni se resuelven — dejan de ser intervenidos, nada más.

`/suspender` detiene el procesamiento conductual sin apagar el servicio: el bot
sigue escuchando comandos, pero no vigila Calendar, ni corre Pomodoro, ni
insiste. Es la salida de emergencia cuando Mástil estorba en vez de ayudar.
"""

from __future__ import annotations

import os
import re
from datetime import datetime

import messages
from core.scheduler import now_local

SUSPENDED_KEY = "suspended"
GUARDIAN_SUSPENDED_KEY = "guardian_suspended"


# Registro diario del intervalo configurado.
#
# Qué anota: qué decía `ESPERA_MINUTOS` cada día. No mide conducta — mide
# el compromiso declarado, que es otra cosa y no se puede reconstruir después.
#
# Por qué existe: bajar la vara nunca se siente como bajar la vara, se siente
# como ser realista. Cada ajuste tiene un buen argumento, la referencia se
# reinicia, y como nadie "incumplió" nada, no queda marca. Un ajuste es
# calibración; cuatro en la misma dirección es otra cosa, y sólo se ve con las
# cuatro fechas delante.
#
# Cómo NO se escribe: nunca como racha. "Día 35 en este valor" es un hecho;
# "racha de 35 días" es algo que se rompe, y lo que se rompe se protege —
# incluso cuando bajar el valor sería lo correcto. Ahí el registro dejaría de
# medir el compromiso y pasaría a medir la resistencia a admitir algo.
#
# El archivo vive en `data/`, que es 700 y de root, y está en el .gitignore.
# No se muestra por Telegram a propósito: mirarlo cuesta abrir una consola, y
# esa fricción es la función, no un descuido.
REGISTRO_ARCHIVO = "intervalo_diario.log"
REGISTRO_DIA_KEY = "registro_intervalo_dia"
REGISTRO_MUESTRAS_KEY = "registro_intervalo_muestras"

# Cuatro al día: no para promediar, sino para acotar a un tramo de seis horas
# el momento en que un valor cambió.
REGISTRO_MUESTRAS_POR_DIA = 4


class SystemModule:
    def __init__(self, config, db, privacy, telegram=None):
        self.config = config
        self.db = db
        self.privacy = privacy
        # Sólo para /sorpresa: hay que saber si Telegram aceptó el envío antes
        # de confirmarlo, y la outbox envía después de que el handler terminó.
        self.telegram = telegram
        self.guardian = None
        self.pomodoro = None

    def attach(self, guardian, pomodoro) -> None:
        """/estado necesita mirar a los otros módulos sin acoplarse a ellos."""
        self.guardian = guardian
        self.pomodoro = pomodoro

    # ------------------------------------------------------------ calendar

    def restore_calendar(self, reason: str = "") -> None:
        if not self.privacy.enabled:
            return
        try:
            self.privacy.restore_last(reason)
        except Exception as exc:
            print(f"Calendar privacy restore error: {exc}", flush=True)

    # ------------------------------------------------------------ comandos

    def handle_command(self, command: str, raw_text: str) -> bool:
        if command == "/suspender":
            return self._suspend()
        if command == "/reanudar":
            return self._resume()
        if command == "/suspender_guardian":
            return self._suspend_guardian()
        if command == "/reanudar_guardian":
            return self._resume_guardian()
        if command == "/admin":
            self._say(messages.PANEL_ADMIN)
            return True
        if command == "/estado":
            return self._status()
        if command == "/reset_estado":
            return self._reset()
        if command == "/cancelar":
            return self._cancel()
        if command == "/sorpresa":
            return self._sorpresa(raw_text)
        if command == "/recordatorios_lite":
            return self._lite_count()
        if command.startswith("/test_"):
            return self._test(command)
        return False

    # ------------------------------------------------------------ internos

    # ------------------------------------------- registro del intervalo

    def _registro_ruta(self):
        return self.config.db_path.parent / REGISTRO_ARCHIVO

    def _intervalo_configurado(self) -> int:
        """Lee la constante, no el comportamiento. Import local para que un
        cambio en Intervalos no obligue a nada acá."""
        from modules.intervalos import ESPERA_MINUTOS
        return int(ESPERA_MINUTOS)

    def _dias_en_valor(self, valor: int) -> int:
        """Cuántos días seguidos, contando hoy, el archivo dice este valor."""
        ruta = self._registro_ruta()
        if not ruta.exists():
            return 1
        dias = 0
        for linea in reversed(ruta.read_text(encoding="utf-8").splitlines()):
            # Un día en que el valor cambió no es un día sostenido en él: corta
            # la cuenta en vez de sumarse. Si no, el primer día entero con el
            # valor nuevo diría "día 2" y el registro empezaría mintiendo.
            if "cambió durante el día" in linea:
                break
            encontrado = re.search(r"= (\d+) min", linea)
            if not encontrado:
                continue
            if int(encontrado.group(1)) != valor:
                break
            dias += 1
        return dias + 1

    def _anotar(self, dia: str, valores: list) -> None:
        """Una línea por día. Si el valor cambió, se dice — no se promedia.

        Tomar la moda escondría justo el único día interesante del año: el que
        cambió. Por eso van todos los valores distintos que se vieron.
        """
        ruta = self._registro_ruta()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        # `valores` son pares [franja, valor]; se ordenan por franja para que
        # "el valor con que terminó el día" sea el de la franja más tardía.
        pares = sorted(v for v in valores if isinstance(v, list) and len(v) == 2)
        solo = [v for _, v in pares] or [v for v in valores if isinstance(v, int)]
        if not solo:
            return
        distintos = sorted(set(solo))
        actual = solo[-1]

        if len(distintos) == 1:
            dias = self._dias_en_valor(actual)
            linea = f"{dia} = intervalo = {actual} min   (día {dias} en este valor)"
        else:
            antes = ", ".join(f"{v} min" for v in distintos if v != actual)
            linea = (f"{dia} = intervalo = {actual} min   "
                     f"(cambió durante el día; antes: {antes})")

        # Es sólo un total voluntario del mismo día local. No se anotan las
        # etiquetas ni el texto: el archivo sigue siendo una referencia breve.
        local_day = datetime.strptime(dia, "%d/%m/%Y").strftime("%Y-%m-%d")
        row = self.db.one(
            """
            SELECT COUNT(*) AS total FROM interval_marks
            WHERE user_id = ? AND local_day = ? AND context_category IS NOT NULL
            """,
            (str(self.config.owner_chat_id), local_day),
        )
        contextos = int(row["total"]) if row else 0

        with open(ruta, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
            f.write("--------------------------------\n")
            f.write(f"contextos voluntarios: {contextos}\n")
        try:
            os.chmod(ruta, 0o600)
        except OSError:
            pass

    def tick(self) -> None:
        """Cuatro muestras al día; al cambiar de día, se cierra el anterior.

        No manda nada por Telegram ni toca ningún otro módulo: escribe una
        línea en un archivo y nada más.
        """
        ahora = now_local()
        hoy = ahora.strftime("%d/%m/%Y")
        dia_guardado = self.db.get_state(REGISTRO_DIA_KEY)
        muestras = self.db.get_state(REGISTRO_MUESTRAS_KEY) or []
        if not isinstance(muestras, list):
            muestras = []

        # Cambió el día: se cierra el anterior con lo que se juntó.
        if dia_guardado and dia_guardado != hoy:
            if muestras:
                try:
                    self._anotar(dia_guardado, muestras)
                except OSError as exc:
                    print(f"[system] no pude anotar el intervalo: {exc}", flush=True)
            muestras = []

        # Una muestra por franja de seis horas, y sólo la primera vez que se
        # entra a esa franja. Guardar el número de franja y no un contador es
        # lo que hace que las muestras estén de verdad repartidas: si sólo se
        # contaran, un arranque a media tarde las tomaría todas en el mismo
        # segundo y no acotarían ninguna ventana.
        #
        # Un proceso apagado media jornada simplemente deja menos muestras. No
        # se inventa lo que no se observó: el valor de esta mañana no se puede
        # mirar desde la tarde.
        franja = ahora.hour // (24 // REGISTRO_MUESTRAS_POR_DIA)
        vistas = {m[0] for m in muestras if isinstance(m, list) and m}
        if franja in vistas:
            if dia_guardado != hoy:
                with self.db.transaction():
                    self.db.set_state(REGISTRO_DIA_KEY, hoy)
            return

        muestras.append([franja, self._intervalo_configurado()])
        with self.db.transaction():
            self.db.set_state(REGISTRO_DIA_KEY, hoy)
            self.db.set_state(REGISTRO_MUESTRAS_KEY, muestras)

    def _say(self, text: str, buttons=None) -> None:
        with self.db.transaction():
            self.db.enqueue(self.config.owner_chat_id, text, buttons=buttons)

    def _suspend(self) -> bool:
        with self.db.transaction():
            self.db.set_state(SUSPENDED_KEY, True)
            if self.guardian:
                self.guardian.reset()
            if self.pomodoro:
                self.pomodoro.reset(announce=False)
            self.db.enqueue(self.config.owner_chat_id, messages.SUSPENDIDO)
            self.db.audit("system", "suspend")
        return True

    def _resume(self) -> bool:
        with self.db.transaction():
            self.db.set_state(SUSPENDED_KEY, False)
            self.db.enqueue(self.config.owner_chat_id, messages.REANUDADO)
            self.db.audit("system", "resume")
        return True

    def _suspend_guardian(self) -> bool:
        with self.db.transaction():
            self.db.set_state(GUARDIAN_SUSPENDED_KEY, True)
            # Los 7 mensajes de una ráfaga se escriben juntos, con
            # `send_after` escalonado. Sin esto, los que todavía no
            # salieron seguirían cayendo y el silencio no sería silencio.
            # Es la misma función que ya usa la tregua, no una nueva.
            if self.guardian:
                self.guardian._cortar_rafaga()
            self.db.enqueue(self.config.owner_chat_id,
                            messages.GUARDIAN_SUSPENDIDO_AVISO,
                            buttons=messages.BOTON_REANUDAR_GUARDIAN)
            self.db.audit("system", "guardian_suspend")
        return True

    def _resume_guardian(self) -> bool:
        """Vuelve a estar disponible DESDE AHORA.

        No hay replay: nada se reenvía por lo que no salió mientras estuvo
        suspendido. El tick siguiente mira los eventos como los mira siempre.
        """
        with self.db.transaction():
            self.db.set_state(GUARDIAN_SUSPENDED_KEY, False)
            self.db.enqueue(self.config.owner_chat_id,
                            messages.GUARDIAN_REANUDADO_AVISO,
                            buttons=messages.BOTON_SUSPENDER_GUARDIAN)
            self.db.audit("system", "guardian_resume")
        return True

    def _status(self) -> bool:
        if self.db.get_state(SUSPENDED_KEY, False):
            self._say(messages.ESTADO_SUSPENDIDO)
            return True

        dormido = bool(self.db.get_state(GUARDIAN_SUSPENDED_KEY, False))
        partes = [messages.GUARDIAN_ESTADO_SUSPENDIDO if dormido
                  else messages.GUARDIAN_ESTADO_ACTIVO]
        if self.guardian:
            partes.append(self.guardian.status_text())
        if self.pomodoro:
            partes.append(self.pomodoro.status_text())

        if self.privacy.enabled:
            pendientes = self.privacy.pending_count()
            if pendientes:
                partes.append(
                    f"Calendar: {pendientes} títulos ofuscados pendientes de reponer."
                )

        # Un Guardian apagado en silencio sería un fallo silencioso: un mal
        # martes se leería como "no me avisó". Acá siempre se ve, y el botón
        # que se ofrece es el único que corresponde al estado actual.
        self._say("\n\n".join(p for p in partes if p),
                  buttons=(messages.BOTON_REANUDAR_GUARDIAN if dormido
                           else messages.BOTON_SUSPENDER_GUARDIAN))
        return True

    def _reset(self) -> bool:
        with self.db.transaction():
            if self.guardian:
                self.guardian.reset()
            if self.pomodoro:
                self.pomodoro.reset(announce=False)
            self.db.execute("UPDATE timer SET active = 0, status = 'idle' WHERE id = 1")
            self.db.set_state(SUSPENDED_KEY, False)
            self.db.set_state(GUARDIAN_SUSPENDED_KEY, False)
            self.db.enqueue(self.config.owner_chat_id, messages.ESTADO_RESETEADO)
            self.db.audit("system", "reset")
        return True

    def _cancel(self) -> bool:
        cancelado = self.guardian.cancel_active() if self.guardian else False
        self._say(messages.GUARDIAN_CANCELADO if cancelado else messages.GUARDIAN_SIN_FLUJO)
        return True

    def _destinataria(self):
        """A quién le llega la sorpresa.

        Reusa MASTIL_LITE_USERS, que es donde ya está su chat: no hace falta
        configurar nada nuevo ni escribir un chat_id en el código.

        En producción hay dos usuarias —ella y el propietario en modo espejo—
        y gana la que no es el propietario. En desarrollo sólo está él, así
        que la sorpresa le llega a sí mismo y el comando se puede probar sin
        involucrarla a ella.
        """
        propio = None
        for usuario in self.config.lite_users:
            if not self.config.is_owner(usuario.chat_id):
                return usuario
            propio = usuario
        return propio

    def _sorpresa(self, raw_text: str) -> bool:
        texto = raw_text.replace("/sorpresa", "", 1).strip()
        if not texto:
            self._say(messages.SORPRESA_USO)
            return True
        self.enviar_sorpresa(texto)
        return True

    def enviar_sorpresa(self, texto: str, foto: str | None = None) -> bool:
        """Manda la sorpresa y dice cómo salió. True si Telegram la aceptó.

        Un solo camino de envío para las dos rutas —el comando `/sorpresa` y el
        flujo con botones—, así que la destinataria y el formato se deciden en
        un solo lugar. Con `foto`, va como **un** mensaje: el texto de pie
        pero mostrado por encima de la imagen.
        """
        destino = self._destinataria()
        if not destino:
            self._say(messages.SORPRESA_SIN_DESTINO)
            return False

        # Directo, no por la outbox: confirmar sin saber si Telegram lo aceptó
        # sería inventar un acuse de recibo.
        try:
            if foto:
                respuesta = self.telegram.send_photo(
                    destino.chat_id, foto, messages.sorpresa(texto),
                    caption_arriba=True,
                )
            else:
                respuesta = self.telegram.send_message(
                    destino.chat_id, messages.sorpresa(texto)
                )
            if not (respuesta or {}).get("ok"):
                raise RuntimeError(f"Telegram respondió: {respuesta}")
        except Exception as exc:
            print(f"[sorpresa] no pude enviar: {exc}", flush=True)
            self._say(messages.SORPRESA_ERROR)
            return False

        self._say(messages.sorpresa_enviada(destino.name))
        self.db.audit("system", "sorpresa", "con foto" if foto else "")
        return True

    def _lite_count(self) -> bool:
        """Cuántos recordatorios activos tiene la usuaria asistida. Nunca cuáles."""
        try:
            row = self.db.one(
                """
                SELECT COUNT(*) AS c FROM lite_reminders
                WHERE status IN ('pending', 'alerting')
                """
            )
            self._say(f"Recordatorios activos de la usuaria asistida: {int(row['c'])}.")
        except Exception as exc:
            print(f"[lite] conteo de recordatorios: {exc}", flush=True)
            self._say("No pude consultar los recordatorios activos de la usuaria asistida.")
        return True

    def _test(self, command: str) -> bool:
        if command == "/test_cierre":
            import random
            self._say(random.choice(messages.MENSAJES_CIERRE))
            return True

        if not self.guardian:
            return False

        if command == "/test_freno":
            self._say("Test admin: Fase Freno activada.")
            self.guardian.admin_test("brake")
            return True
        if command == "/test_chequeo":
            self.guardian.admin_test("check")
            return True
        if command == "/test_rescate":
            self._say("Test admin: Rescate normal activado.")
            self.guardian.admin_test("rescue")
            return True
        if command == "/test_rescate30":
            self._say("Test admin: Rescate acelerado activado.")
            self.guardian.admin_test("rescue_fast")
            return True
        return False
