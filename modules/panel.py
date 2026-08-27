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

import messages
from modules import reporte

PREFIJO = "panel:"

# Cada entrada es una pantalla completa: título y teclado. Ningún menú calcula
# nada; si hubiera que decidir algo en tiempo real, no sería un menú.
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
    "panel:tm:hora": (
        messages.PANEL_TIMER_HORA, messages.PANEL_TIMER_HORA_BOTONES,
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

    def attach(self, router) -> None:
        self.router = router

    # ------------------------------------------------------------- básicos

    def _pantalla(self, chat_id, texto, botones, message_id=None) -> None:
        """Edita si hay `message_id`; si no, manda uno nuevo."""
        with self.db.transaction():
            self.db.enqueue(
                chat_id, texto, buttons=botones, message_id=message_id
            )

    def _pedir(self, clave, chat_id, message_id, flujo, paso, texto, datos=None) -> None:
        self._pendientes[clave] = {
            "flujo": flujo,
            "paso": paso,
            "datos": dict(datos or {}),
            "message_id": message_id,
        }
        self._pantalla(chat_id, texto, messages.PANEL_PIDE_BOTONES, message_id)

    def _olvidar(self, clave) -> None:
        self._pendientes.pop(clave, None)

    def olvidar_todo(self) -> None:
        """Descarta los formularios abiertos. La usa el router ante un comando."""
        self._pendientes.clear()
        self._reportes.clear()
        self._sorpresas.clear()

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
            self.config.owner_chat_id, messages.PANEL_TITULO, messages.PANEL_BOTONES
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
            texto, botones = MENUS[data]
            self._pantalla(chat_id, texto, botones, message_id)
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
            self._pantalla(chat_id, messages.PANEL_SORPRESA_MENU,
                           messages.PANEL_SORPRESA_MENU_BOTONES, message_id)
            return True

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

        if data == "panel:vig:foto":
            self._olvidar(clave)
            if not self._vigia():
                self._pantalla(chat_id, messages.PANEL_VIG_SIN_TAREA,
                               MENUS["panel:vigia"][1], message_id)
                return True
            self._pantalla(chat_id, messages.PANEL_VIG_FOTO,
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

        # Pasos con botones del Timer configurado.
        if data in ("panel:tm:avisos:no", "panel:tm:avisos:si",
                    "panel:tm:razon:no", "panel:tm:razon:si"):
            return self._timer_config(data, clave, chat_id, message_id, callback)

        print(f"[panel] callback desconocido: {data}", flush=True)
        return True

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
        self._pantalla(chat_id, texto, botones, message_id)

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
        """True sólo si había un formulario esperando justo este texto."""
        clave = (str(user_id), str(chat_id))
        valor = (text or "").strip()
        if not valor:
            return False

        # Llegó texto pero la sorpresa estaba esperando una foto. Se avisa y
        # no se pierde nada: el texto que ya había sigue guardado. Va antes de
        # mirar `_pendientes` porque esperar una foto no deja formulario.
        sorpresa = self._sorpresas.get(clave)
        if sorpresa and sorpresa["paso"] == "foto":
            self._pantalla(chat_id, messages.SORPRESA_FALTA_FOTO,
                           messages.PANEL_PIDE_BOTONES)
            return True

        pendiente = self._pendientes.get(clave)
        if not pendiente:
            return False

        flujo = pendiente["flujo"]
        paso = pendiente["paso"]
        datos = pendiente["datos"]
        message_id = pendiente["message_id"]
        datos[paso] = valor

        # --- Calendario: el día lo puso el botón, el resto lo escribe la
        # persona y se preserva literal (incluidos ** y ++).
        if flujo in ("cal_hoy", "cal_manana"):
            if paso == "razon":
                self._pedir(clave, chat_id, message_id, flujo, "hora",
                            messages.PANEL_CAL_HORA, datos)
                return True
            self._cerrar(clave, chat_id, message_id, "panel:calendar")
            cuando = " next" if flujo == "cal_manana" else ""
            self._ejecutar(
                f"/cal {datos['razon']}{cuando} {datos['hora']}", source_id
            )
            return True

        if flujo == "cal_otro":
            if paso == "fecha":
                self._pedir(clave, chat_id, message_id, flujo, "razon",
                            messages.PANEL_CAL_RAZON, datos)
                return True
            if paso == "razon":
                self._pedir(clave, chat_id, message_id, flujo, "hora",
                            messages.PANEL_CAL_HORA, datos)
                return True
            self._cerrar(clave, chat_id, message_id, "panel:calendar")
            self._ejecutar(
                f"/cal {datos['razon']} {datos['fecha']} {datos['hora']}", source_id
            )
            return True

        # --- Timer. La validación de minutos, avisos y razón es la de /timer:
        # acá no se revisa nada, se arma el comando y se entrega.
        if flujo == "timer_otro":
            self._cerrar(clave, chat_id, message_id, "panel:timer")
            self._ejecutar(f"/timer {valor}", source_id)
            return True

        # La hora y el intervalo son datos, no comandos: el Panel los junta
        # y el timer los valida, igual que con los minutos de siempre.
        if flujo == "timer_hora":
            self._cerrar(clave, chat_id, message_id, "panel:timer")
            self._ejecutar(f"/timer_a {valor}", source_id)
            return True

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

    def handle_photo(self, user_id, chat_id, message) -> bool:
        """True sólo si había una sorpresa esperando justo esta foto."""
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
