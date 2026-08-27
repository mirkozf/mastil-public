"""Entrada única de Telegram.

Un solo lugar decide quién atiende cada mensaje, en un orden explícito y
legible. En el legacy esto estaba repartido entre `read_telegram`,
`handle_command` y dos módulos que parcheaban `urlopen` para espiar los
updates antes que nadie; el orden real dependía del orden de los imports.

Prioridades, en este orden y sin excepciones:

1. **Mástil Lite** ve los mensajes de sus usuarias. Es el único camino para
   la usuaria asistida y nunca toca los módulos del propietario.
2. Desde acá, sólo se procesa la cuenta del propietario.
3. Un texto que empieza con `/` es un comando. Vigía jamás lo recibe: así un
   `/listo` no puede ser interpretado como duración ni como código.
4. Una foto va a Vigía.
5. Texto libre va a Vigía (duraciones, códigos, respuestas sin `/`).
"""

from __future__ import annotations

from typing import Any


class Router:
    def __init__(self, config, db, telegram, modules: dict[str, Any]):
        self.config = config
        self.db = db
        self.telegram = telegram
        self.modules = modules

        # Orden de la cadena de comandos. El primero que devuelve True gana.
        self.command_chain = [
            modules["panel"],
            # Vigía atiende /vigia y sus comandos. Antes no estaba en la
            # cadena, así que /vigia_cancelar y /vigia_stop no llegaban a
            # ningún lado: se procesaban como comando y nadie los tomaba.
            modules["vigia"],
            modules["timer"],
            modules["system"],
            modules["pomodoro"],
            modules["gmail"],
            modules["guardian"],
        ]

    # ------------------------------------------------------------ updates

    def process(self, update: dict[str, Any]) -> None:
        callback = update.get("callback_query")
        if callback:
            self._process_callback(callback)
            return

        message = update.get("message")
        if not message:
            return
        self._process_message(message)

    def _process_callback(self, callback: dict[str, Any]) -> None:
        chat_id = str(
            (callback.get("message") or {}).get("chat", {}).get("id", "")
        )
        data = str(callback.get("data") or "").strip()

        if not self.config.is_owner(chat_id) or not data:
            self.telegram.answer_callback(callback.get("id", ""))
            return

        # La cola lleva en el callback a qué evento pendiente se refiere, así
        # que necesita el callback entero para poder decir que ya expiró.
        if data.startswith("cola:"):
            self.telegram.answer_callback(callback.get("id", ""))
            print(f"[router] cola callback={data}", flush=True)
            try:
                self.modules["guardian"].handle_cola_callback(callback)
            except Exception as exc:
                print(f"[router] Cola: {exc}", flush=True)
            return

        # El Panel navega editando el mensaje, así que necesita el callback
        # entero (de dónde viene y qué mensaje reemplazar). Se le responde
        # primero para que el botón no quede girando mientras navega.
        if data.startswith("panel:"):
            self.telegram.answer_callback(callback.get("id", ""))
            print(f"[router] panel callback={data}", flush=True)
            try:
                self.modules["panel"].handle_callback(callback)
            except Exception as exc:
                print(f"[router] Panel: {exc}", flush=True)
            return

        self.telegram.answer_callback(callback.get("id", ""))
        print(f"[router] callback={data}", flush=True)
        self.handle_command(data, callback.get("id"))

    def _process_message(self, message: dict[str, Any]) -> None:
        chat_id = str((message.get("chat") or {}).get("id", ""))
        text = str(message.get("text") or "").strip()

        es_lite = self.config.lite_user(chat_id) is not None
        es_owner = self.config.is_owner(chat_id)

        # 1. Usuaria Lite pura (la usuaria asistida): sólo Lite, nunca nada más.
        if es_lite and not es_owner:
            try:
                self.modules["lite"].handle_message(chat_id, text)
            except Exception as exc:
                print(f"[router] Mástil Lite error: {exc}", flush=True)
            return

        # 2. Desde acá, sólo el propietario.
        if not es_owner:
            return

        # 3. Comandos. Vigía nunca los ve.
        #
        # Tienen prioridad sobre el Panel: un formulario a medio llenar jamás
        # se traga un comando. Y como escribir un comando es haberse ido a
        # otra cosa, ese formulario se descarta en vez de quedar armado
        # esperando el próximo texto suelto.
        if text.startswith("/"):
            print(f"[router] command={text}", flush=True)
            self.modules["panel"].olvidar_todo()
            self.handle_command(text, message.get("message_id"))
            return

        # 3a. Un dato que el Panel está esperando. Sólo entra si hay un botón
        # que lo pidió hace un momento; si no, sigue de largo como siempre.
        user_id = str((message.get("from") or {}).get("id", chat_id))
        try:
            if self.modules["panel"].handle_text(
                user_id, chat_id, text, message.get("message_id")
            ):
                return
        except Exception as exc:
            print(f"[router] Panel: {exc}", flush=True)

        # 3b. Modo espejo: el propietario también figura como usuaria Lite para
        # poder probar ese flujo sobre sí mismo. Sólo se lleva lo que es
        # inequívocamente de Lite; el resto sigue hacia Vigía como siempre.
        if es_lite and self.modules["lite"].matches(chat_id, text):
            print("[router] lite(espejo)", flush=True)
            try:
                self.modules["lite"].handle_message(chat_id, text)
            except Exception as exc:
                print(f"[router] Mástil Lite error: {exc}", flush=True)
            return

        # 4. Fotos. El Panel primero: si hay una sorpresa esperando su imagen,
        # esa foto es para ella. Sólo cuando no hay ninguna pasa a Vigía, que
        # es su destino de siempre.
        if message.get("photo"):
            try:
                if self.modules["panel"].handle_photo(user_id, chat_id, message):
                    return
            except Exception as exc:
                print(f"[router] Panel foto: {exc}", flush=True)
            if self.modules["vigia"].handle_photo(message):
                return

        # 5. Texto libre: duraciones y códigos.
        #
        # Vigía primero, para no cambiar lo que ya funcionaba. Guardian queda
        # de respaldo: sólo se queda con el texto si está esperando su código.
        if text:
            if self.modules["vigia"].handle_text(text):
                return
            self.modules["guardian"].handle_text(text)

    # ----------------------------------------------------------- comandos

    def handle_command(self, raw_text: str, source_id: object = None) -> None:
        raw_text = raw_text.strip()
        if not raw_text:
            return

        command = raw_text.split()[0].lower().split("@", 1)[0]

        # Intervalos necesita saber de qué mensaje viene para no registrar dos
        # marcas si Telegram reintenta la entrega.
        if command in (
            "/marca", "/tiempo", "/reset",
            # Los dos botones de la fricción de /tiempo. Van por acá y no por
            # la cadena porque Intervalos no está en ella.
            "/tiempo_mostrar", "/tiempo_dejarlo",
        ):
            try:
                self.modules["intervalos"].handle(command, source_id)
            except Exception as exc:
                print(f"[router] Intervalos: {exc}", flush=True)
            return

        # /cal necesita el id del mensaje para que un reintento de Telegram no
        # cree el mismo evento dos veces. Se mantiene aislado del resto de
        # comandos para no cambiar sus contratos existentes.
        if command == "/cal":
            try:
                self.modules["calendar"].handle_command(command, raw_text, source_id)
            except Exception as exc:
                print(f"[router] Calendar: {exc}", flush=True)
            return

        # Los comandos que cortan todo también cierran Vigía y reponen el
        # calendario, pase lo que pase después.
        if command in ("/suspender", "/cancelar", "/reset_estado"):
            try:
                self.modules["vigia"].stop(command)
            except Exception as exc:
                print(f"[router] vigía stop: {exc}", flush=True)
            try:
                self.modules["system"].restore_calendar(command)
            except Exception as exc:
                print(f"[router] calendar restore: {exc}", flush=True)

        for module in self.command_chain:
            try:
                if module.handle_command(command, raw_text):
                    return
            except Exception as exc:
                print(f"[router] {type(module).__name__}: {exc}", flush=True)
                return
