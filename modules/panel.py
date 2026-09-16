"""Panel: los mismos comandos, tocando botones.

No agrega comportamiento. Es una segunda puerta a lo que ya existe, y por eso
la lógica de cada acción sigue viviendo donde vivía:

    /comando ──────────┐
                       ├──> el mismo handler de siempre
    botón callback ────┘

El truco que lo mantiene chico es que el `callback_data` de un botón de acción
es el comando literal (`/marca`, `/timer 10`). El router ya sabe despachar eso,
así que esos botones no pasan por este archivo en absoluto.

Acá sólo queda lo que un comando no sabe hacer:

- **navegar** editando el mismo mensaje, para que abrir cuatro menús no deje
  cuatro mensajes en la pantalla;
- **pedir un dato** cuando el comando necesita argumentos, y después armar ese
  mismo comando y entregárselo al router.

El estado de esos formularios vive en memoria y a propósito. Es un dato de
interfaz que dura segundos; guardarlo en SQLite obligaría a una tabla, una
migración y una limpieza para algo que se puede perder sin consecuencias. Si el
proceso reinicia a mitad de un formulario, se vuelve a tocar el botón.
"""

from __future__ import annotations

from datetime import datetime, timezone

import messages
from modules.calendar_commands import (ESTADO_AMBIGUA, ESTADO_OK,
                                       ESTADO_SIN_CERO, aplicar_franja,
                                       franja_de, interpretar_hora,
                                       token_hora)
from modules.pomodoro import descanso_recomendado
from modules import reporte

PREFIJO = "panel:"
ASISTQ_PREGUNTA_MAX = 1000
ASISTQ_OPCION_MAX = 48

# Cada entrada es una pantalla completa: título y teclado. Ningún menú calcula
# nada; si hubiera que decidir algo en tiempo real, no sería un menú.
# Donde esta el panel ahora mismo. Va en `system_state` para que sobreviva
# a un reinicio: si se pierde, el panel deja de saber cual de todos los
# mensajes de la conversacion es el suyo.
#
# `outbox_id` es transitorio: el `message_id` real no existe hasta que
# Telegram acepta el envio, asi que el runtime lo completa despues.
PANEL_OUTBOX_KEY = "panel_outbox_id"
PANEL_MESSAGE_KEY = "panel_message_id"
PANEL_MENU_KEY = "panel_menu"
PANEL_SNAPSHOT_KEY = "panel_snapshot"

# Comandos que devuelven el panel aunque el boton se haya apretado desde
# otro mensaje.
#
# Los avisos del timer traen su propio boton APAGAR, y una alarma puede
# sonar diez veces antes de que la cortes: para entonces el panel quedo
# diez mensajes atras y ya no se encuentra. Apagar la alarma es volver al
# punto de partida, asi que el panel vuelve con ella.
DEVUELVEN_PANEL = ("/apagar",)

MENUS = {
    "panel:home": (messages.PANEL_TITULO, messages.PANEL_BOTONES),
    "panel:intervalos": (
        messages.PANEL_INTERVALOS_TITULO, messages.PANEL_INTERVALOS_BOTONES,
    ),
    "panel:calendar": (
        messages.PANEL_CALENDAR_TITULO, messages.PANEL_CALENDAR_BOTONES,
    ),
    # Las tres modalidades del timer. `panel:timer` NO está acá: se arma
    # sola porque depende de si hay algo corriendo.
    "panel:tm:cuenta": (
        messages.PANEL_TIMER_CUENTA, messages.PANEL_TIMER_CUENTA_BOTONES,
    ),
    "panel:tm:cada": (
        messages.PANEL_TIMER_CADA, messages.PANEL_TIMER_CADA_BOTONES,
    ),
    "panel:pomodoro": (
        messages.PANEL_POMODORO_TITULO, messages.PANEL_POMODORO_BOTONES,
    ),
    "panel:gmail": (messages.PANEL_GMAIL_TITULO, messages.PANEL_GMAIL_BOTONES),
    "panel:system": (
        messages.PANEL_SYSTEM_TITULO, messages.PANEL_SYSTEM_BOTONES,
    ),
    "panel:vigia": (
        messages.PANEL_VIGIA_TITULO, messages.PANEL_VIGIA_BOTONES,
    ),
}

# Botón -> (flujo, primer paso, texto que se pide).
PIDEN_TEXTO = {
    "panel:cal:hoy": ("cal_hoy", "razon", messages.PANEL_CAL_RAZON),
    "panel:cal:manana": ("cal_manana", "razon", messages.PANEL_CAL_RAZON),
    "panel:cal:otro": ("cal_otro", "fecha", messages.PANEL_CAL_FECHA),
    "panel:tm:otro": ("timer_otro", "minutos", messages.PANEL_TIMER_OTRO),
    # AVISAR A pide la hora directo: la pantalla intermedia sólo repetía
    # "elegir la hora". El callback viejo queda por los paneles que todavía
    # lo tengan en pantalla.
    "panel:tm:hora": (
        "timer_hora", "hora", messages.PANEL_TIMER_PIDE_HORA,
    ),
    "panel:tm:hora:pedir": (
        "timer_hora", "hora", messages.PANEL_TIMER_PIDE_HORA,
    ),
    "panel:tm:cada:otro": (
        "timer_cada", "minutos", messages.PANEL_TIMER_PIDE_CADA,
    ),
    "panel:tm:config": (
        "timer_config", "minutos", messages.PANEL_TIMER_CONFIG_MINUTOS,
    ),
    "panel:pomo:otro": ("pomo_minutos", "minutos", messages.PANEL_POMO_MINUTOS),
    "panel:pomo:foco": ("pomo_foco", "foco", messages.PANEL_POMO_FOCO),
    "panel:gm:contenido": ("gmail", "numero", messages.PANEL_GMAIL_NUMERO),
    # Reporte de Intervalos: las dos fechas se piden con el mismo formulario
    # que todo lo demás. El rango elegido vive aparte, en `_reportes`.
    "panel:rep:desde": ("rep_desde", "fecha", messages.REPORTE_PIDE_DESDE),
    "panel:rep:hasta": ("rep_hasta", "fecha", messages.REPORTE_PIDE_HASTA),
    # El motivo para romper el límite del buzón. El Panel sólo junta el texto;
    # evaluarlo y decidir qué hacer con él es cosa de Gmail.
    "panel:gm:motivo": ("gmail_motivo", "motivo", messages.GMAIL_MOTIVO_ESCRIBIR),
    # El objetivo de Vigía es texto libre, igual que por comando.
    "panel:sor:texto": ("sorpresa_texto", "texto",
                        messages.SORPRESA_PIDE_TEXTO_SIN_FOTO),
    "panel:sor:foto": ("sorpresa_texto", "texto",
                       messages.SORPRESA_PIDE_TEXTO_CON_FOTO),
    "panel:vig:objetivo": ("vigia_objetivo", "objetivo",
                           messages.PANEL_VIGIA_OBJETIVO),
    "panel:vig:aclarar": ("vigia_aclarar", "aclaracion",
                          messages.VIGIA_MOTIVO_ESCRIBIR),
}

# Los cuatro campos del contexto mínimo salen de la misma tabla que dibuja sus
# botones, para que agregar uno no obligue a tocar dos listas.
PIDEN_TEXTO.update({
    callback: (f"vigia_ctx_{clave}", clave, prompt)
    for clave, _, callback, prompt in messages.PANEL_VIG_CTX_CAMPOS
})


class PanelModule:
    def __init__(self, config, db):
        self.config = config
        self.db = db
        # Se completa en el arranque: el router se construye después que los
        # módulos, así que no puede llegar por el constructor.
        self.router = None
        # (user_id, chat_id) -> formulario a medio llenar.
        self._pendientes: dict[tuple[str, str], dict] = {}
        # (user_id, chat_id) -> rango del reporte. Va aparte de `_pendientes`
        # porque tiene que sobrevivir entre DESDE, HASTA y EXPORTAR, que son
        # tres toques de botón con dos formularios en el medio.
        self._reportes: dict[tuple[str, str], dict] = {}
        # (user_id, chat_id) -> sorpresa a medio armar: modo, texto y foto.
        # Va aparte de `_pendientes` por lo mismo que el reporte: sobrevive
        # entre varios toques de botón, con formularios en el medio.
        self._sorpresas: dict[tuple[str, str], dict] = {}
        # Borrador del creador. Las preguntas ya enviadas viven en SQLite;
        # sólo el formulario incompleto se descarta al reiniciar.
        self._preguntas_asistidas: dict[tuple[str, str], dict] = {}
        # Tu último mensaje, sea o no para el Panel. Una pantalla que contesta
        # a ESE mensaje sigue viva cuando el panel se recrea abajo; en cuanto
        # llega otro, ya es un recuerdo. En memoria, igual que los formularios:
        # tras un reinicio no queda nada a medio contestar.
        self._ultimo_mensaje = None
        # Mientras se atiende un mensaje, a cuál contesta cada pantalla.
        self._respondiendo_a = None

    def attach(self, router) -> None:
        self.router = router

    # ------------------------------------------------------------- básicos

    def _pantalla(self, chat_id, texto, botones, message_id=None,
                  menu=None, responde_a=None) -> None:
        """Edita si hay `message_id`; si no, manda uno nuevo.

        Cuando manda uno nuevo anota en que fila de la outbox quedo, para
        que el runtime pueda decirle despues en que mensaje aterrizo.
        """
        with self.db.transaction():
            fila = self.db.enqueue(
                chat_id, texto, buttons=botones, message_id=message_id
            )
            if message_id is None:
                self.db.set_state(PANEL_OUTBOX_KEY, fila)
                self.db.set_state(PANEL_MESSAGE_KEY, None)
            else:
                self.db.set_state(PANEL_MESSAGE_KEY, message_id)
            if menu:
                self.db.set_state(PANEL_MENU_KEY, menu)
            # El panel puede ser borrado y recreado al final del chat. Guardar
            # su pantalla exacta evita perder un formulario o confirmacion.
            self.db.set_state(PANEL_SNAPSHOT_KEY, {
                "text": texto,
                "buttons": botones or [],
                # A qué mensaje tuyo contesta esta pantalla, si contesta a uno.
                "responde_a": (responde_a if responde_a is not None
                               else self._respondiendo_a),
            })

    def adopt_message_id(self, chat_id: str, message_id: int) -> None:
        """Mueve los formularios vivos al panel recien recreado."""
        chat_id = str(chat_id)
        for (user_id, pending_chat), pending in self._pendientes.items():
            if str(pending_chat) == chat_id:
                pending["message_id"] = int(message_id)

    def recreate_current(self, chat_id: str) -> None:
        """Encola una sola copia del panel al pie del chat, en el menú principal.

        Cuando el panel se recrea abajo NO arrastra dónde estabas. Una pantalla
        vieja reapareciendo al pie —un pedido que ya cumpliste, un menú del que
        ya te fuiste— confunde más de lo que ahorra: parece que el sistema te
        está pidiendo algo cuando sólo está repitiendo el pasado.

        Dos excepciones, y por lo mismo: ahí la pantalla no es un recuerdo sino
        la pregunta viva.

        - Un formulario esperando que escribas. Borrarlo te dejaría escribiendo
          a ciegas.
        - La respuesta a lo último que mandaste. Tu propio mensaje es lo que
          empuja el panel hacia abajo: si al recrearse se descartara lo que te
          acaba de contestar —la elección de formato tras el número del
          correo—, la pregunta desaparecería antes de poder elegir. En cuanto
          mandas otra cosa o aprietas una acción, deja de ser respuesta.
        """
        has_form = any(
            str(pending_chat) == str(chat_id)
            for _, pending_chat in self._pendientes
        )
        snapshot = self.db.get_state(PANEL_SNAPSHOT_KEY)

        if not has_form and not self._responde_al_ultimo(snapshot):
            # Con una tarea de Vigía viva el home no es el sitio: ese flujo
            # tiene muchos pasos y cada uno devolvía el panel a la entrada,
            # obligando a rehacer el camino en mitad de la tarea. Se vuelve a
            # su menú —al MENÚ, no a la pantalla anterior—, así que ningún
            # pedido ya cumplido revive por esta puerta.
            destino = "panel:vigia" if self._vigia() else "panel:home"
            with self.db.transaction():
                self.db.set_state(PANEL_SNAPSHOT_KEY, None)
                self.db.set_state(PANEL_MENU_KEY, destino)
            titulo, botones = MENUS[destino]
            self._pantalla(chat_id, self._titulo(destino, titulo),
                           botones, menu=destino)
            return

        menu = self.db.get_state(PANEL_MENU_KEY) or "panel:home"
        if isinstance(snapshot, dict) and snapshot.get("text"):
            self._pantalla(
                chat_id,
                snapshot["text"],
                snapshot.get("buttons") or [],
                menu=menu,
                # Sigue contestando al mismo mensaje: si después llega un aviso
                # y el panel vuelve a bajar, la pregunta sigue en pie.
                responde_a=snapshot.get("responde_a"),
            )
            return

        titulo, botones = MENUS.get(menu, MENUS["panel:home"])
        self._pantalla(chat_id, self._titulo(menu, titulo), botones, menu=menu)

    def _responde_al_ultimo(self, snapshot) -> bool:
        """La pantalla guardada contesta a tu último mensaje."""
        if not isinstance(snapshot, dict) or not snapshot.get("text"):
            return False
        destino = snapshot.get("responde_a")
        return destino is not None and destino == self._ultimo_mensaje

    def _pedir(self, clave, chat_id, message_id, flujo, paso, texto,
               datos=None, botones=None) -> None:
        self._pendientes[clave] = {
            "flujo": flujo,
            "paso": paso,
            "datos": dict(datos or {}),
            "message_id": message_id,
        }
        self._pantalla(chat_id, texto,
                       botones or messages.PANEL_PIDE_BOTONES, message_id)

    # --- pantallas de otro módulo ----------------------------------------
    # Otro módulo puede navegar sobre el Panel sin tocar sus internals:
    # mostrar una pantalla, pedir un texto (que vuelve por su flujo) o abrir
    # un menú.

    def mostrar_modulo(self, clave, chat_id, texto, botones,
                       message_id=None) -> None:
        """Una pantalla de otro módulo, en el lugar del panel."""
        self._olvidar(clave)
        self._pantalla(chat_id, texto, botones, message_id)

    def pedir_modulo(self, clave, chat_id, message_id, flujo, paso,
                     texto) -> None:
        """Un formulario cuyo texto se entrega al módulo dueño del flujo."""
        self._pedir(clave, chat_id, message_id, flujo, paso, texto)

    def abrir_menu(self, clave, chat_id, menu, message_id=None) -> None:
        """Un menú del Panel, igual que tocar su botón."""
        self._olvidar(clave)
        titulo, botones = MENUS[menu]
        self._pantalla(chat_id, self._titulo(menu, titulo), botones,
                       message_id, menu=menu)

    def _olvidar(self, clave) -> None:
        self._pendientes.pop(clave, None)

    def olvidar_todo(self) -> None:
        """Descarta los formularios abiertos. La usa el router ante un comando."""
        self._pendientes.clear()
        self._reportes.clear()
        self._sorpresas.clear()
        self._preguntas_asistidas.clear()
        # Un comando es haberse ido a otra cosa: lo que el panel había
        # contestado antes ya no es respuesta a nada.
        self._ultimo_mensaje = None

    def _ejecutar(self, comando: str, source_id: object) -> None:
        """Entrega el comando armado al router, igual que si se hubiera tecleado."""
        if not self.router:
            print("[panel] sin router: no ejecuto", flush=True)
            return
        self.router.handle_command(comando, source_id)

    # ------------------------------------------------------------ comandos

    def handle_command(self, command: str, raw_text: str) -> bool:
        if command != "/panel":
            return False
        # /panel es también la salida de cualquier formulario a medio llenar.
        self.olvidar_todo()
        self._pantalla(
            self.config.owner_chat_id, messages.PANEL_TITULO,
            messages.PANEL_BOTONES, menu="panel:home",
        )
        return True

    # ----------------------------------------------------------- callbacks

    def handle_callback(self, callback: dict) -> bool:
        data = str(callback.get("data") or "").strip()
        if not data.startswith(PREFIJO):
            return False

        mensaje = callback.get("message") or {}
        chat_id = str((mensaje.get("chat") or {}).get("id", ""))
        message_id = mensaje.get("message_id")
        user_id = str((callback.get("from") or {}).get("id", chat_id))
        clave = (user_id, chat_id)

        # Navegar cancela cualquier formulario: si volviste al menú, el dato
        # que se estaba pidiendo ya no se está pidiendo.
        if data in MENUS:
            self._olvidar(clave)
            # Volver a un menú es haberse ido del reporte: el rango se descarta.
            self._reportes.pop(clave, None)
            self._sorpresas.pop(clave, None)
            self._preguntas_asistidas.pop(clave, None)
            texto, botones = MENUS[data]
            self._pantalla(chat_id, self._titulo(data, texto), botones,
                           message_id, menu=data)
            return True

        # El timer se dibuja segun lo que haya corriendo. `panel:tm:modos`
        # es la misma pantalla forzando las tres opciones, para cambiar de
        # modalidad sin tener que detener primero.
        if data in ("panel:timer", "panel:tm:modos"):
            self._olvidar(clave)
            self._timer_pantalla(chat_id, message_id,
                                 forzar_modos=data.endswith(":modos"))
            return True

        # Elegido el intervalo, se pregunta por cuánto rato. El intervalo no
        # se guarda en ningún lado: viaja dentro de los botones del paso
        # siguiente, así que no hay formulario que pueda quedar a medias.
        if data.startswith("panel:tm:cada:") and data.split(":")[-1].isdigit():
            cada = int(data.split(":")[-1])
            self._olvidar(clave)
            self._pantalla(chat_id, messages.panel_timer_duracion(cada),
                           messages.panel_timer_duracion_botones(cada),
                           message_id)
            return True

        if data == "panel:sys:sorpresa":
            self._olvidar(clave)
            self._sorpresas.pop(clave, None)
            self._preguntas_asistidas.pop(clave, None)
            self._pantalla(chat_id, messages.PANEL_SORPRESA_MENU,
                           messages.PANEL_SORPRESA_MENU_BOTONES, message_id)
            return True

        if data == "panel:sor:pregunta":
            self._sorpresas.pop(clave, None)
            self._preguntas_asistidas[clave] = {
                "question": "", "option_a": "", "option_b": "",
            }
            self._pedir(clave, chat_id, message_id, "asistq_create",
                        "question", messages.ASISTQ_PIDE_PREGUNTA)
            return True

        if data in ("panel:asistq:preview:a", "panel:asistq:preview:b"):
            # Permiten ver el teclado exacto; la preview no responde.
            return True

        if data == "panel:asistq:editar":
            self._preguntas_asistidas[clave] = {
                "question": "", "option_a": "", "option_b": "",
            }
            self._pedir(clave, chat_id, message_id, "asistq_create",
                        "question", messages.ASISTQ_PIDE_PREGUNTA)
            return True

        if data == "panel:asistq:cancelar":
            self._olvidar(clave)
            self._preguntas_asistidas.pop(clave, None)
            self._pantalla(chat_id, messages.ASISTQ_CANCELADA,
                           messages.PANEL_SORPRESA_MENU_BOTONES, message_id)
            return True

        if data == "panel:asistq:enviar":
            return self._pregunta_asistida_enviar(clave, chat_id, message_id)

        if data in ("panel:sor:foto", "panel:sor:texto"):
            self._sorpresas[clave] = {
                "modo": "foto" if data.endswith(":foto") else "texto",
                "paso": "texto", "texto": "", "foto": "",
            }
            flujo, paso, texto = PIDEN_TEXTO[data]
            self._pedir(clave, chat_id, message_id, flujo, paso, texto)
            return True

        if data == "panel:sor:cancelar":
            self._olvidar(clave)
            self._sorpresas.pop(clave, None)
            self._preguntas_asistidas.pop(clave, None)
            self._pantalla(chat_id, messages.SORPRESA_CANCELADA,
                           MENUS["panel:system"][1], message_id)
            return True

        if data in ("panel:sor:edtexto", "panel:sor:edfoto",
                    "panel:sor:enviar"):
            return self._sorpresa_paso(data, clave, chat_id, message_id)

        if data == "panel:int:reporte":
            self._olvidar(clave)
            self._reporte_pantalla(clave, chat_id, message_id)
            return True

        if data == "panel:rep:exportar":
            return self._exportar(clave, chat_id, message_id)

        if data in PIDEN_TEXTO:
            flujo, paso, texto = PIDEN_TEXTO[data]
            self._pedir(clave, chat_id, message_id, flujo, paso, texto)
            return True

        if data == "panel:int:reset":
            self._olvidar(clave)
            self._pantalla(
                chat_id, messages.PANEL_INTERVALOS_RESET,
                messages.PANEL_INTERVALOS_RESET_BOTONES, message_id,
            )
            return True

        if data == "panel:int:reset:ok":
            self._olvidar(clave)
            titulo, botones = MENUS["panel:intervalos"]
            self._pantalla(chat_id, titulo, botones, message_id)
            self._ejecutar("/reset", callback.get("id"))
            return True

        if data == "panel:vig:ctx":
            self._olvidar(clave)
            return self._vigia_contexto(chat_id, message_id)

        if data in ("panel:vig:foto", "panel:vig:foto:1", "panel:vig:foto:2"):
            self._olvidar(clave)
            vigia = self._vigia()
            if not vigia:
                self._pantalla(chat_id, messages.PANEL_VIG_SIN_TAREA,
                               MENUS["panel:vigia"][1], message_id)
                return True

            # Sin número todavía, se pregunta. El análisis se dispara al llegar
            # la foto, así que saber cuántas vienen es lo que permite esperar
            # la segunda en vez de planificar con media escena.
            if data == "panel:vig:foto":
                self._pantalla(chat_id, messages.PANEL_VIG_CUANTAS,
                               messages.PANEL_VIG_CUANTAS_BOTONES, message_id)
                return True

            cuantas = 2 if data.endswith(":2") else 1
            vigia.esperar_fotos(cuantas)
            texto = (messages.PANEL_VIG_FOTO_PRIMERA if cuantas == 2
                     else messages.PANEL_VIG_FOTO)
            self._pantalla(chat_id, texto,
                           messages.PANEL_VIG_FOTO_BOTONES, message_id)
            return True

        if data == "panel:vig:cancelar":
            self._olvidar(clave)
            self._pantalla(
                chat_id, messages.PANEL_VIGIA_CANCELAR,
                messages.PANEL_VIGIA_CANCELAR_BOTONES, message_id,
            )
            return True

        if data == "panel:vig:cancelar:ok":
            self._olvidar(clave)
            titulo, botones = MENUS["panel:vigia"]
            self._pantalla(chat_id, titulo, botones, message_id)
            self._ejecutar("/vigia_cancelar", callback.get("id"))
            return True

        if data == "panel:sys:borrar":
            # La marca se nombra por numero y tramo, que es como se la mira en
            # la tabla: horas de reloj no aparecen en ningun lado.
            resumen = None
            if self.router:
                resumen = self.router.modules["intervalos"].ultima_marca_resumen()
            if not resumen:
                titulo, botones = MENUS["panel:system"]
                self._pantalla(chat_id, messages.PANEL_BORRAR_SIN_MARCAS,
                               botones, message_id, menu="panel:system")
                return True
            self._pantalla(chat_id, messages.panel_borrar_marca(resumen),
                           messages.PANEL_BORRAR_MARCA_BOTONES, message_id)
            return True

        if data == "panel:sys:borrar:ok":
            titulo, botones = MENUS["panel:system"]
            self._pantalla(chat_id, titulo, botones, message_id,
                           menu="panel:system")
            self._ejecutar("/borrar_marca", callback.get("id"))
            return True

        if data in ("panel:cal:am", "panel:cal:pm"):
            return self._cal_franja(data, clave, chat_id, message_id, callback)

        # Pasos con botones del Timer configurado.
        if data in ("panel:tm:avisos:no", "panel:tm:avisos:si",
                    "panel:tm:razon:no", "panel:tm:razon:si"):
            return self._timer_config(data, clave, chat_id, message_id, callback)

        print(f"[panel] callback desconocido: {data}", flush=True)
        return True

    def _cal_hora(self, clave, chat_id, message_id, flujo, datos, valor,
                  source_id) -> bool:
        """Interpreta la hora escrita y decide si hay que preguntar."""
        estado, hora, minuto = interpretar_hora(valor)

        if estado == ESTADO_AMBIGUA:
            datos["hh"], datos["mm"] = hora, minuto
            self._pedir(clave, chat_id, message_id, flujo, "franja",
                        messages.PANEL_CAL_AMPM, datos,
                        botones=messages.PANEL_CAL_AMPM_BOTONES)
            return True

        if estado != ESTADO_OK:
            texto = (messages.PANEL_CAL_SIN_CERO if estado == ESTADO_SIN_CERO
                     else messages.PANEL_CAL_HORA_INVALIDA)
            self._pedir(clave, chat_id, message_id, flujo, "hora", texto,
                        datos)
            return True

        if flujo == "timer_hora":
            return self._timer_hora_enviar(clave, chat_id, message_id, hora,
                                           minuto, source_id)
        datos["hora"] = token_hora(hora, minuto)
        return self._cal_enviar(clave, chat_id, message_id, flujo, datos,
                                source_id)

    def _cal_cerrar(self, clave, chat_id, message_id, flujo, datos, franja,
                    source_id) -> bool:
        """Ya se sabe la franja: se arma la hora y se manda."""
        hora, minuto = aplicar_franja(int(datos.get("hh", 0)),
                                      int(datos.get("mm", 0)), franja)
        if flujo == "timer_hora":
            return self._timer_hora_enviar(clave, chat_id, message_id, hora,
                                           minuto, source_id)
        datos["hora"] = token_hora(hora, minuto)
        return self._cal_enviar(clave, chat_id, message_id, flujo, datos,
                                source_id)

    def _cal_enviar(self, clave, chat_id, message_id, flujo, datos,
                    source_id) -> bool:
        self._cerrar(clave, chat_id, message_id, "panel:calendar")
        if flujo == "cal_otro":
            self._ejecutar(
                f"/cal {datos['razon']} {datos['fecha']} {datos['hora']}",
                source_id)
        else:
            cuando = " next" if flujo == "cal_manana" else ""
            self._ejecutar(
                f"/cal {datos['razon']}{cuando} {datos['hora']}", source_id)
        return True

    def _timer_hora_enviar(self, clave, chat_id, message_id, hora, minuto,
                           source_id) -> bool:
        """AVISAR A con la hora ya resuelta en 24 horas, que es lo que lee /timer_a.

        Comparte con el Calendario la lectura de la hora y la pregunta AM/PM;
        lo único propio es a qué comando termina entregándola.
        """
        self._cerrar(clave, chat_id, message_id, "panel:timer")
        self._ejecutar(f"/timer_a {hora:02d}:{minuto:02d}", source_id)
        return True

    def _cal_franja(self, data, clave, chat_id, message_id, callback) -> bool:
        """Los botones AM/PM. Escribir `am` o `pm` hace exactamente lo mismo."""
        pendiente = self._pendientes.get(clave)
        if not pendiente or pendiente["paso"] != "franja":
            # El formulario expiró (reinicio, o se navegó a otro lado).
            titulo, botones = MENUS["panel:calendar"]
            self._pantalla(chat_id, titulo, botones, message_id,
                           menu="panel:calendar")
            return True
        franja = "a" if data.endswith(":am") else "p"
        return self._cal_cerrar(clave, chat_id, message_id,
                                pendiente["flujo"], pendiente["datos"],
                                franja, callback.get("id"))

    def _titulo(self, menu: str, estatico: str) -> str:
        """El de Pomodoro dice la duracion vigente y el descanso sugerido.

        El resto de los menus son texto fijo y salen tal cual. Se lee la
        tabla de Pomodoro directamente, igual que la pantalla del Timer lee
        la suya: son los botones diciendo el estado, no un modulo nuevo.
        """
        if menu != "panel:pomodoro":
            return estatico
        fila = self.db.one(
            "SELECT work_minutes FROM pomodoro_session WHERE id = 1")
        trabajo = int((fila and fila["work_minutes"])
                      or self.config.pomodoro_trabajo_minutes)
        return messages.panel_pomodoro_titulo(
            trabajo, descanso_recomendado(trabajo))

    def _timer_pantalla(self, chat_id, message_id, forzar_modos=False) -> None:
        """Una pantalla que dice la verdad de lo que hay.

        Ofrecer PAUSAR sin timer, o tres modalidades cuando ya hay uno
        corriendo, obliga a leer el mensaje para saber qué hacen los
        botones. Acá los botones son el estado.
        """
        timer = self.db.one("SELECT * FROM timer WHERE id = 1")
        activo = bool(timer and timer["active"]) and not forzar_modos

        if not activo:
            texto = messages.PANEL_TIMER_SIN_ACTIVO
            botones = messages.PANEL_TIMER_MODOS
        else:
            resumen = ""
            if self.router:
                resumen = self.router.modules["timer"].resumen_actual()
            texto = messages.panel_timer_activo(resumen)
            botones = messages.panel_timer_botones(timer)
        self._pantalla(chat_id, texto, botones, message_id,
                       menu="panel:timer")

    def _timer_config(self, data, clave, chat_id, message_id, callback) -> bool:
        pendiente = self._pendientes.get(clave)
        if not pendiente or pendiente["flujo"] != "timer_config":
            # El formulario expiró (reinicio, o se navegó a otro lado).
            self._timer_pantalla(chat_id, message_id)
            return True

        datos = pendiente["datos"]

        if data == "panel:tm:avisos:si":
            self._pedir(clave, chat_id, message_id, "timer_config", "avisos",
                        messages.PANEL_TIMER_AVISOS_PIDE, datos)
            return True

        if data == "panel:tm:avisos:no":
            self._pantalla(chat_id, messages.PANEL_TIMER_RAZON,
                           messages.PANEL_TIMER_RAZON_BOTONES, message_id)
            pendiente["paso"] = "razon"
            return True

        if data == "panel:tm:razon:si":
            self._pedir(clave, chat_id, message_id, "timer_config", "razon",
                        messages.PANEL_TIMER_RAZON_PIDE, datos)
            return True

        # panel:tm:razon:no — no hay nada más que preguntar.
        self._olvidar(clave)
        self._ejecutar(self._comando_timer(datos), callback.get("id"))
        self._timer_pantalla(chat_id, message_id)
        return True

    # --------------------------------------------------- texto de un paso

    def handle_text(self, user_id: str, chat_id: str, text: str,
                    source_id: object = None) -> bool:
        """True sólo si había un formulario esperando justo este texto.

        Todo texto que no es comando pasa primero por el Panel, así que acá se
        anota cuál fue tu último mensaje aunque no sea para él. Cada pantalla
        que se muestre mientras se atiende queda marcada como su respuesta.
        """
        self._ultimo_mensaje = source_id
        self._respondiendo_a = source_id
        try:
            return self._atender_texto(user_id, chat_id, text, source_id)
        finally:
            self._respondiendo_a = None

    def _atender_texto(self, user_id: str, chat_id: str, text: str,
                       source_id: object = None) -> bool:
        clave = (str(user_id), str(chat_id))
        valor = (text or "").strip()
        pendiente = self._pendientes.get(clave)
        if not valor:
            if pendiente and pendiente.get("flujo") == "asistq_create":
                self._pantalla(chat_id,
                               f"{messages.ASISTQ_TEXTO_VACIO}\n\n"
                               f"{self._asistq_prompt(pendiente['paso'])}",
                               messages.PANEL_PIDE_BOTONES,
                               pendiente.get("message_id"))
                return True
            return False

        # Llegó texto pero la sorpresa estaba esperando una foto. Se avisa y
        # no se pierde nada: el texto que ya había sigue guardado. Va antes de
        # mirar `_pendientes` porque esperar una foto no deja formulario.
        sorpresa = self._sorpresas.get(clave)
        if sorpresa and sorpresa["paso"] == "foto":
            self._pantalla(chat_id, messages.SORPRESA_FALTA_FOTO,
                           messages.PANEL_PIDE_BOTONES)
            return True

        if not pendiente:
            return False

        flujo = pendiente["flujo"]
        paso = pendiente["paso"]
        datos = pendiente["datos"]
        message_id = pendiente["message_id"]
        if flujo == "asistq_create":
            return self._pregunta_asistida_texto(
                clave, chat_id, message_id, paso, datos, valor
            )

        datos[paso] = valor

        # --- Calendario: el día lo puso el botón, el resto lo escribe la
        # persona y se preserva literal (incluidos ** y ++).
        if flujo in ("cal_hoy", "cal_manana", "cal_otro"):
            if paso == "fecha":
                self._pedir(clave, chat_id, message_id, flujo, "razon",
                            messages.PANEL_CAL_RAZON, datos)
                return True
            if paso == "razon":
                self._pedir(clave, chat_id, message_id, flujo, "hora",
                            messages.PANEL_CAL_HORA, datos)
                return True
            if paso == "hora":
                return self._cal_hora(clave, chat_id, message_id, flujo,
                                      datos, valor, source_id)
            if paso == "franja":
                franja = franja_de(valor)
                if not franja:
                    self._pedir(clave, chat_id, message_id, flujo, "franja",
                                messages.PANEL_CAL_AMPM, datos,
                                botones=messages.PANEL_CAL_AMPM_BOTONES)
                    return True
                return self._cal_cerrar(clave, chat_id, message_id, flujo,
                                        datos, franja, source_id)
            return True

        # --- Timer. La validación de minutos, avisos y razón es la de /timer:
        # acá no se revisa nada, se arma el comando y se entrega.
        if flujo == "timer_otro":
            self._cerrar(clave, chat_id, message_id, "panel:timer")
            self._ejecutar(f"/timer {valor}", source_id)
            return True

        # AVISAR A lee la hora igual que el Calendario: reloj de 12 con a/p, y
        # si falta, pregunta. La franja se contesta escribiendo o con botón.
        if flujo == "timer_hora":
            if paso == "franja":
                franja = franja_de(valor)
                if not franja:
                    self._pedir(clave, chat_id, message_id, flujo, "franja",
                                messages.PANEL_CAL_AMPM, datos,
                                botones=messages.PANEL_CAL_AMPM_BOTONES)
                    return True
                return self._cal_cerrar(clave, chat_id, message_id, flujo,
                                        datos, franja, source_id)
            return self._cal_hora(clave, chat_id, message_id, flujo, datos,
                                  valor, source_id)

        if flujo == "timer_cada":
            self._olvidar(clave)
            if not valor.strip().isdigit():
                self._timer_pantalla(chat_id, message_id)
                return True
            cada = int(valor.strip())
            self._pantalla(chat_id, messages.panel_timer_duracion(cada),
                           messages.panel_timer_duracion_botones(cada),
                           message_id)
            return True

        if flujo == "timer_config":
            if paso == "minutos":
                pendiente["paso"] = "avisos"
                self._pantalla(chat_id, messages.PANEL_TIMER_AVISOS,
                               messages.PANEL_TIMER_AVISOS_BOTONES, message_id)
                return True
            if paso == "avisos":
                pendiente["paso"] = "razon"
                self._pantalla(chat_id, messages.PANEL_TIMER_RAZON,
                               messages.PANEL_TIMER_RAZON_BOTONES, message_id)
                return True
            self._cerrar(clave, chat_id, message_id, "panel:timer")
            self._ejecutar(self._comando_timer(datos), source_id)
            return True

        # --- Pomodoro: /pomodoro acepta un número o un texto de foco, y
        # distinguirlos ya es cosa suya.
        if flujo in ("pomo_minutos", "pomo_foco"):
            self._cerrar(clave, chat_id, message_id, "panel:pomodoro")
            self._ejecutar(f"/pomodoro {valor}", source_id)
            return True

        # --- Gmail: con el número ya se pueden armar los dos comandos, así
        # que el formato se elige sin volver a depender de la memoria.
        if flujo == "gmail":
            self._olvidar(clave)
            self._pantalla(
                chat_id, messages.PANEL_GMAIL_FORMATO,
                messages.panel_gmail_formato_botones(valor), message_id,
            )
            return True

        if flujo == "sorpresa_texto":
            self._olvidar(clave)
            sorpresa = self._sorpresas.get(clave)
            if not sorpresa:
                self._pantalla(chat_id, messages.SORPRESA_SIN_FLUJO,
                               MENUS["panel:system"][1], message_id)
                return True
            sorpresa["texto"] = valor
            if sorpresa["modo"] == "foto" and not sorpresa["foto"]:
                # El texto es lo que se manda; la foto acompaña. Por eso se
                # pide en este orden y no al revés.
                sorpresa["paso"] = "foto"
                self._pantalla(chat_id, messages.SORPRESA_PIDE_FOTO,
                               messages.PANEL_PIDE_BOTONES, message_id)
                return True
            return self._sorpresa_preview(clave, chat_id, message_id)

        # --- Reporte: la fecha se valida acá y se guarda; el Excel se arma
        # recién al tocar EXPORTAR.
        if flujo == "vigia_objetivo":
            self._olvidar(clave)
            self._ejecutar(f"/vigia {valor}", source_id)
            # Creada la tarea, se cae directo en el contexto: es el paso
            # siguiente del diagrama y evita que haya que buscarlo.
            return self._vigia_contexto(chat_id, message_id)

        if flujo.startswith("vigia_ctx_"):
            self._olvidar(clave)
            vigia = self._vigia()
            if vigia:
                vigia.guardar_contexto(flujo.replace("vigia_ctx_", "", 1), valor)
            return self._vigia_contexto(chat_id, message_id)

        if flujo == "vigia_aclarar":
            self._olvidar(clave)
            vigia = self._vigia()
            if vigia:
                # La aclaración entra al contexto y se reanaliza la MISMA foto.
                previo = (vigia.contexto_actual().get("extra") or "").strip()
                vigia.guardar_contexto("extra", f"{previo}\n{valor}".strip())
                vigia.reanalizar()
            return True

        if flujo == "gmail_motivo":
            self._olvidar(clave)
            if self.router:
                self.router.modules["gmail"].recibir_motivo(valor)
            return True

        if flujo in ("rep_desde", "rep_hasta"):
            self._olvidar(clave)
            fecha = reporte.parse_fecha(valor)
            if not fecha:
                self._pantalla(chat_id, messages.REPORTE_FECHA_INVALIDA,
                               messages.reporte_botones(
                                   *self._rango(clave)), message_id)
                return True
            rango = self._reportes.setdefault(clave, {})
            rango["desde" if flujo == "rep_desde" else "hasta"] = fecha
            self._reporte_pantalla(clave, chat_id, message_id)
            return True

        self._olvidar(clave)
        return False

    def reubicar(self, callback: dict) -> bool:
        """El panel vuelve al final de la conversacion tras una accion.

        Un boton de accion (`/marca`, `30 MIN`) no lo atiende el Panel: su
        `callback_data` ES el comando, asi que lo ejecuta el modulo de
        turno y contesta con un mensaje nuevo, abajo. El menu quedaba
        arriba, intacto y con los botones vivos: la respuesta aparecia en
        un lado y el panel seguia en otro.

        La politica central de mensajes hace ahora el movimiento despues de
        que Telegram confirma todos los envios. Aca solo se reconoce si la
        accion pertenecia al panel; no se crean copias por adelantado.

        Devuelve False si el boton no era del panel. Los de Guardian
        vienen en su propio mensaje y no hay que moverles nada.
        """
        mensaje = callback.get("message") or {}
        message_id = mensaje.get("message_id")
        chat_id = str((mensaje.get("chat") or {}).get("id", ""))
        data = str(callback.get("data") or "").strip()
        if not chat_id:
            return False

        viejo = self.db.get_state(PANEL_MESSAGE_KEY)
        if viejo != message_id and data not in DEVUELVEN_PANEL:
            return False

        # Apretaste una acción del panel —NATURAL, BASE64, 30 MIN—: lo que te
        # había preguntado quedó contestado y no tiene que revivir abajo.
        self._ultimo_mensaje = None
        return True

    def _cerrar(self, clave, chat_id, message_id, menu: str) -> None:
        """Termina el formulario y deja el menú de vuelta en su sitio."""
        self._olvidar(clave)
        # El del timer no es estático: depende de lo que quedó corriendo, que
        # es justo lo que acaba de cambiar al cerrar el formulario.
        if menu == "panel:timer":
            self._timer_pantalla(chat_id, message_id)
            return
        titulo, botones = MENUS[menu]
        self._pantalla(chat_id, titulo, botones, message_id)

    # --------------------------------------------------------- sorpresa

    @staticmethod
    def _asistq_prompt(paso: str) -> str:
        return {
            "question": messages.ASISTQ_PIDE_PREGUNTA,
            "option_a": messages.ASISTQ_PIDE_OPCION_A,
            "option_b": messages.ASISTQ_PIDE_OPCION_B,
        }.get(paso, messages.ASISTQ_PIDE_PREGUNTA)

    @staticmethod
    def _asistq_normalizar_opcion(texto: str) -> str:
        return " ".join(texto.split()).casefold()

    def _pregunta_asistida_texto(self, clave, chat_id, message_id, paso,
                             datos, valor) -> bool:
        if paso == "question":
            if len(valor) > ASISTQ_PREGUNTA_MAX:
                self._pantalla(
                    chat_id,
                    f"{messages.ASISTQ_PREGUNTA_LARGA}\n\n"
                    f"{messages.ASISTQ_PIDE_PREGUNTA}",
                    messages.PANEL_PIDE_BOTONES, message_id,
                )
                return True
            datos[paso] = valor
            self._pedir(clave, chat_id, message_id, "asistq_create",
                        "option_a", messages.ASISTQ_PIDE_OPCION_A, datos)
            return True

        if len(valor) > ASISTQ_OPCION_MAX:
            self._pantalla(
                chat_id,
                f"{messages.ASISTQ_OPCION_LARGA}\n\n{self._asistq_prompt(paso)}",
                messages.PANEL_PIDE_BOTONES, message_id,
            )
            return True

        if paso == "option_a":
            datos[paso] = valor
            self._pedir(clave, chat_id, message_id, "asistq_create",
                        "option_b", messages.ASISTQ_PIDE_OPCION_B, datos)
            return True

        if self._asistq_normalizar_opcion(datos.get("option_a", "")) == \
                self._asistq_normalizar_opcion(valor):
            self._pantalla(
                chat_id,
                f"{messages.ASISTQ_OPCIONES_IGUALES}\n\n"
                f"{messages.ASISTQ_PIDE_OPCION_B}",
                messages.PANEL_PIDE_BOTONES, message_id,
            )
            return True

        datos[paso] = valor
        self._olvidar(clave)
        self._preguntas_asistidas[clave] = dict(datos)
        self._pantalla(
            chat_id,
            messages.pregunta_asistida(datos["question"]),
            messages.pregunta_asistida_preview_botones(
                datos["option_a"], datos["option_b"]
            ),
            message_id,
        )
        return True

    def _pregunta_asistida_enviar(self, clave, chat_id, message_id) -> bool:
        borrador = self._preguntas_asistidas.get(clave)
        if not borrador:
            self._pantalla(chat_id, messages.ASISTQ_SIN_BORRADOR,
                           messages.PANEL_SORPRESA_MENU_BOTONES, message_id)
            return True

        destino = None
        if self.router:
            destino = self.router.modules["system"]._destinataria()
        if not destino:
            self._pantalla(chat_id, messages.ASISTQ_SIN_DESTINO,
                           messages.pregunta_asistida_preview_botones(
                               borrador["option_a"], borrador["option_b"]
                           ), message_id)
            return True

        creado = datetime.now(timezone.utc).isoformat()
        with self.db.transaction():
            cursor = self.db.execute(
                """
                INSERT INTO assisted_questions
                    (creator_chat_id, assisted_chat_id, question_text,
                     option_a, option_b, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(self.config.owner_chat_id), str(destino.chat_id),
                 borrador["question"],
                 borrador["option_a"], borrador["option_b"], creado),
            )
            pregunta_id = int(cursor.lastrowid)

        try:
            respuesta = self.router.telegram.send_message(
                str(destino.chat_id),
                messages.pregunta_asistida(borrador["question"]),
                buttons=messages.pregunta_asistida_botones(
                    pregunta_id, borrador["option_a"], borrador["option_b"]
                ),
            )
            telegram_message_id = (respuesta or {}).get("result", {}).get("message_id")
            if not (respuesta or {}).get("ok") or not telegram_message_id:
                raise RuntimeError(f"Telegram respondió: {respuesta}")
        except Exception as exc:
            print(f"[pregunta la usuaria asistida] no pude enviar: {exc}", flush=True)
            with self.db.transaction():
                self.db.execute("DELETE FROM assisted_questions WHERE id = ?",
                                (pregunta_id,))
            self._pantalla(chat_id, messages.ASISTQ_ERROR_ENVIO,
                           messages.pregunta_asistida_preview_botones(
                               borrador["option_a"], borrador["option_b"]
                           ), message_id)
            return True

        with self.db.transaction():
            self.db.execute(
                "UPDATE assisted_questions SET telegram_message_id = ? WHERE id = ?",
                (int(telegram_message_id), pregunta_id),
            )
            self.db.audit("panel", "assisted_question_sent", f"id={pregunta_id}")

        self._olvidar(clave)
        self._preguntas_asistidas.pop(clave, None)
        self._pantalla(chat_id, messages.ASISTQ_ENVIADA,
                       messages.PANEL_SORPRESA_MENU_BOTONES, message_id)
        return True

    def handle_assisted_question_callback(self, callback: dict) -> bool:
        """Registra una única respuesta validando chat, usuario y mensaje."""
        data = str(callback.get("data") or "").strip()
        callback_id = str(callback.get("id") or "")
        parts = data.split(":")
        telegram = self.router.telegram if self.router else None

        if (len(parts) != 3 or parts[0] != "asistq" or
                not parts[1].isdigit() or parts[2] not in ("a", "b")):
            if telegram:
                telegram.answer_callback(callback_id, messages.ASISTQ_NO_DISPONIBLE)
            return True

        pregunta_id = int(parts[1])
        row = self.db.one("SELECT * FROM assisted_questions WHERE id = ?",
                          (pregunta_id,))
        mensaje = callback.get("message") or {}
        callback_chat = str((mensaje.get("chat") or {}).get("id", ""))
        callback_user = str((callback.get("from") or {}).get("id", ""))
        callback_message = mensaje.get("message_id")

        autorizada = (
            row is not None
            and self.config.lite_user(callback_chat) is not None
            and callback_chat == str(row["assisted_chat_id"])
            and callback_user == str(row["assisted_chat_id"])
            and callback_message is not None
            and int(callback_message) == int(row["telegram_message_id"] or -1)
        )
        if not autorizada:
            if telegram:
                telegram.answer_callback(callback_id, messages.ASISTQ_NO_DISPONIBLE)
            return True

        if row["answered_option"] is not None:
            telegram.answer_callback(callback_id, messages.ASISTQ_YA_RESPONDIDA)
            return True

        elegida = parts[2]
        respondida = datetime.now(timezone.utc).isoformat()
        with self.db.transaction():
            cursor = self.db.execute(
                """
                UPDATE assisted_questions
                SET answered_option = ?, answered_at = ?
                WHERE id = ? AND answered_option IS NULL
                """,
                (elegida, respondida, pregunta_id),
            )
        if cursor.rowcount != 1:
            telegram.answer_callback(callback_id, messages.ASISTQ_YA_RESPONDIDA)
            return True

        telegram.answer_callback(callback_id)
        respuesta = row["option_a"] if elegida == "a" else row["option_b"]

        try:
            telegram.edit_message(
                callback_chat, int(callback_message),
                messages.pregunta_asistida_respondida(row["question_text"], respuesta),
                buttons=[],
            )
        except Exception as exc:
            print(f"[pregunta la usuaria asistida] no pude editar: {exc}", flush=True)
            try:
                telegram.send_message(callback_chat,
                                      messages.ASISTQ_RESPUESTA_REGISTRADA)
            except Exception as fallback_exc:
                print(f"[pregunta la usuaria asistida] fallback falló: {fallback_exc}", flush=True)

        try:
            telegram.send_message(
                str(row["creator_chat_id"]),
                messages.pregunta_asistida_notificacion(
                    row["question_text"], respuesta
                ),
            )
        except Exception as exc:
            print(f"[pregunta la usuaria asistida] no pude notificar: {exc}", flush=True)

        with self.db.transaction():
            self.db.audit("panel", "assisted_question_answered",
                          f"id={pregunta_id};option={elegida}")
        return True

    def handle_photo(self, user_id, chat_id, message) -> bool:
        """True sólo si había una sorpresa esperando justo esta foto.

        Toda foto pasa primero por el Panel, sea o no para él: después de
        mandarla, lo que el panel había contestado antes ya no es respuesta.
        """
        self._ultimo_mensaje = message.get("message_id")
        self._respondiendo_a = self._ultimo_mensaje
        try:
            return self._atender_foto(user_id, chat_id, message)
        finally:
            self._respondiendo_a = None

    def _atender_foto(self, user_id, chat_id, message) -> bool:
        clave = (str(user_id), str(chat_id))
        sorpresa = self._sorpresas.get(clave)
        if not sorpresa or sorpresa["modo"] != "foto":
            return False

        fotos = message.get("photo") or []
        if not fotos:
            return False

        if sorpresa["paso"] != "foto":
            # Llegó antes de tiempo. El texto que ya había no se toca.
            self._pantalla(chat_id, messages.SORPRESA_FALTA_TEXTO,
                           messages.PANEL_PIDE_BOTONES)
            return True

        try:
            ruta = self.router.telegram.download_photo(
                fotos[-1]["file_id"], self.config.evidence_dir
            )
        except Exception as exc:
            print(f"[sorpresa] no pude bajar la foto: {exc}", flush=True)
            self._pantalla(chat_id, messages.SORPRESA_PIDE_FOTO,
                           messages.PANEL_PIDE_BOTONES)
            return True

        sorpresa["foto"] = str(ruta)
        self._sorpresa_preview(clave, chat_id, None)
        return True

    def _sorpresa_preview(self, clave, chat_id, message_id) -> bool:
        """Exactamente lo que va a recibir ella, más los botones.

        Con foto va directo por Telegram y no por la outbox: es la única
        manera de mandar el pie de foto por encima de la imagen y con teclado
        en el mismo mensaje, que es como se verá el envío real.
        """
        sorpresa = self._sorpresas.get(clave)
        if not sorpresa:
            self._pantalla(chat_id, messages.SORPRESA_SIN_FLUJO,
                           MENUS["panel:system"][1], message_id)
            return True

        sorpresa["paso"] = "preview"
        vista = messages.sorpresa(sorpresa["texto"])

        if sorpresa["modo"] != "foto":
            self._pantalla(chat_id, vista, messages.SORPRESA_BOTONES_SIN_FOTO,
                           message_id)
            return True

        try:
            self.router.telegram.send_photo(
                chat_id, sorpresa["foto"], vista,
                buttons=messages.SORPRESA_BOTONES_CON_FOTO,
                caption_arriba=True,
            )
        except Exception as exc:
            print(f"[sorpresa] preview falló: {exc}", flush=True)
            self._pantalla(chat_id, messages.SORPRESA_ERROR,
                           messages.SORPRESA_BOTONES_CON_FOTO, message_id)
        return True

    def _sorpresa_paso(self, data, clave, chat_id, message_id) -> bool:
        sorpresa = self._sorpresas.get(clave)
        if not sorpresa:
            self._pantalla(chat_id, messages.SORPRESA_SIN_FLUJO,
                           MENUS["panel:system"][1], message_id)
            return True

        if data == "panel:sor:edtexto":
            # Sólo el texto: la foto se conserva.
            sorpresa["paso"] = "texto"
            pide = (messages.SORPRESA_PIDE_TEXTO_CON_FOTO
                    if sorpresa["modo"] == "foto"
                    else messages.SORPRESA_PIDE_TEXTO_SIN_FOTO)
            self._pedir(clave, chat_id, message_id, "sorpresa_texto", "texto", pide)
            return True

        if data == "panel:sor:edfoto":
            # Sólo la foto: el texto se conserva.
            self._olvidar(clave)
            sorpresa["paso"] = "foto"
            self._pantalla(chat_id, messages.SORPRESA_PIDE_FOTO_DE_NUEVO,
                           messages.PANEL_PIDE_BOTONES, message_id)
            return True

        # panel:sor:enviar
        if not sorpresa.get("texto"):
            self._pantalla(chat_id, messages.SORPRESA_FALTA_TEXTO,
                           messages.PANEL_PIDE_BOTONES, message_id)
            return True

        enviado = False
        if self.router:
            enviado = self.router.modules["system"].enviar_sorpresa(
                sorpresa["texto"], sorpresa.get("foto") or None
            )
        if enviado:
            self._sorpresas.pop(clave, None)
        else:
            # No se pierde la preview: se puede reintentar el envío.
            self._pantalla(chat_id, messages.SORPRESA_ERROR,
                           messages.SORPRESA_BOTONES_CON_FOTO
                           if sorpresa["modo"] == "foto"
                           else messages.SORPRESA_BOTONES_SIN_FOTO)
        return True

    # ------------------------------------------------------------- Vigía

    def _vigia(self):
        """El módulo, sólo si hay una tarea en curso."""
        if not self.router:
            return None
        vigia = self.router.modules.get("vigia")
        return vigia if vigia and vigia.sesion_activa() else None

    def _vigia_contexto(self, chat_id, message_id) -> bool:
        """La pantalla de contexto, sobre el mismo mensaje."""
        vigia = self._vigia()
        if not vigia:
            self._pantalla(chat_id, messages.PANEL_VIG_SIN_TAREA,
                           MENUS["panel:vigia"][1], message_id)
            return True
        session = vigia.sesion_activa()
        contexto = vigia.contexto_actual()
        self._pantalla(
            chat_id,
            messages.panel_vigia_contexto(session.objetivo, contexto),
            messages.panel_vigia_contexto_botones(contexto),
            message_id,
        )
        return True

    # ------------------------------------------------ reporte de Intervalos

    def _rango(self, clave):
        """Las dos fechas ya elegidas, en texto, para pintarlas en los botones."""
        rango = self._reportes.get(clave) or {}
        return (
            rango["desde"].strftime("%d/%m/%Y") if rango.get("desde") else None,
            rango["hasta"].strftime("%d/%m/%Y") if rango.get("hasta") else None,
        )

    def _reporte_pantalla(self, clave, chat_id, message_id, texto=None) -> None:
        self._pantalla(
            chat_id, texto or messages.REPORTE_TITULO,
            messages.reporte_botones(*self._rango(clave)), message_id,
        )

    def _exportar(self, clave, chat_id, message_id) -> bool:
        rango = self._reportes.get(clave) or {}
        desde, hasta = rango.get("desde"), rango.get("hasta")

        if not desde or not hasta:
            self._reporte_pantalla(clave, chat_id, message_id,
                                   messages.REPORTE_FALTA_RANGO)
            return True
        if desde > hasta:
            self._reporte_pantalla(clave, chat_id, message_id,
                                   messages.REPORTE_RANGO_INVERTIDO)
            return True

        destino = self.config.evidence_dir.parent / "reportes"
        destino.mkdir(parents=True, exist_ok=True)
        archivo = destino / reporte.nombre_archivo(desde, hasta)

        try:
            hay_datos = reporte.generar(
                self.db, self.config.owner_chat_id, desde, hasta, archivo
            )
        except Exception as exc:
            print(f"[reporte] no pude generar: {exc}", flush=True)
            self._reporte_pantalla(clave, chat_id, message_id, messages.REPORTE_ERROR)
            return True

        if not hay_datos:
            self._reporte_pantalla(clave, chat_id, message_id,
                                   messages.REPORTE_SIN_DATOS)
            return True

        # Directo, no por la outbox: confirmar sin saber si Telegram aceptó el
        # archivo sería inventar un acuse de recibo. Mismo criterio que
        # /sorpresa. El router es quien tiene el cliente de Telegram.
        try:
            respuesta = self.router.telegram.send_document(
                chat_id, archivo,
                messages.reporte_listo(
                    desde.strftime("%d/%m/%Y"), hasta.strftime("%d/%m/%Y"),
                    archivo.name,
                ),
            )
            if not (respuesta or {}).get("ok"):
                raise RuntimeError(f"Telegram respondió: {respuesta}")
        except Exception as exc:
            print(f"[reporte] no pude enviar: {exc}", flush=True)
            self._reporte_pantalla(clave, chat_id, message_id, messages.REPORTE_ERROR)
            return True
        finally:
            try:
                archivo.unlink(missing_ok=True)
            except OSError:
                pass

        self._reporte_pantalla(clave, chat_id, message_id)
        return True

    def _comando_timer(self, datos: dict) -> str:
        """`/timer MIN [AVISOS] [RAZÓN]`, en el orden que ese parser espera."""
        partes = ["/timer", datos.get("minutos", "")]
        if datos.get("avisos"):
            partes.append(datos["avisos"])
        if datos.get("razon"):
            partes.append(datos["razon"])
        return " ".join(p for p in partes if p)
