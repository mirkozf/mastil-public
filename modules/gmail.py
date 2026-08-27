"""Gmail bajo demanda.

Nunca avisa que llegó un correo: eso sería exactamente la interrupción no
solicitada que el resto de Mástil trata de evitar.

El flujo tiene una barrera deliberada. Primero se ven **remitentes numerados**,
y sólo si el propietario pide un número se trae el contenido. `/gmail_asuntos`
fue retirado por eso: un asunto en pantalla ya es contenido emocional que nadie
pidió ver. El modo `base64` no cifra nada; pone una barrera visual para poder
pasarle el correo a otra IA sin leerlo de paso.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime

import messages
from core.scheduler import now_local

# ==========================================================================
# Dos revisiones por día
# ==========================================================================
# La cuenta conectada a Mástil recibe correo de una sola persona, así que no
# hace falta filtrar nada: el buzón entero es ese buzón.
#
# Revisar es mirar el buzón (`/gmail_hay`, `/gmail_remitentes`). Abrir un
# correo ya elegido no cuenta ni se limita: el precio se paga al decidir mirar.
#
# Esto NO bloquea. La regla es del usuario y puede romperla; lo que la fricción
# impide es que la rompa sin notar que la está rompiendo.

REVISIONES = ("/gmail_hay", "/gmail_remitentes")

# Botones del flujo de fricción. No consultan nada, así que se saltan el acuse
# de "consultando" y el conteo.
FRICCION = ("/gmail_igual", "/gmail_dejarlo", "/gmail_si", "/gmail_reintentar")

# Contador del día, **por opción**. Gastar las dos miradas en "¿hay correos?"
# no debería dejarte sin poder ver de quién son: son preguntas distintas y cada
# una tiene su propio par.
#
# En `system_state`, sin tabla nueva:
#   {"fecha": "YYYY-MM-DD", "usos": {"/gmail_hay": {"n": 1, "ultima": iso}}}
CONTADOR_KEY = "gmail_revisiones"


class GmailModule:
    def __init__(self, config, db, bridge, telegram=None, vision=None):
        self.config = config
        self.db = db
        self.bridge = bridge
        # Sólo para el acuse inmediato. Las respuestas de verdad siguen yendo
        # por la outbox.
        self.telegram = telegram
        # `Vision` no guarda estado —es una api_key y un modelo—, así que
        # tener el suyo no compite con el de Vigía y evita tocar el arranque.
        # El parámetro queda para que las pruebas inyecten uno falso.
        if vision is None:
            from integrations.vision import Vision
            vision = Vision(config.gemini_api_key, config.gemini_model)
        self.vision = vision
        # Fricción en curso. En memoria a propósito: dura segundos y perderla
        # en un reinicio es exactamente lo que corresponde — se vuelve a
        # empezar, y no queda una revisión a medio autorizar.
        self._friccion: dict | None = None

    def _say(self, text: str, buttons=None) -> None:
        with self.db.transaction():
            # Telegram corta cerca de 4096 caracteres; troceamos antes.
            trozos = [text[i:i + 3500] for i in range(0, len(text), 3500)] or [""]
            for indice, chunk in enumerate(trozos):
                self.db.enqueue(
                    self.config.owner_chat_id, chunk,
                    buttons=buttons if indice == len(trozos) - 1 else None,
                )

    # ------------------------------------------------------ contador diario

    def _hoy(self) -> str:
        """Fecha local del sistema, la misma que usa todo el scheduler."""
        return now_local().strftime("%Y-%m-%d")

    def _contador(self) -> dict:
        """El del día entero. Uno de otra fecha ya no cuenta: el día es el corte."""
        estado = self.db.get_state(CONTADOR_KEY) or {}
        if estado.get("fecha") != self._hoy() or "usos" not in estado:
            return {"fecha": self._hoy(), "usos": {}}
        return estado

    def _uso(self, command: str) -> dict:
        return self._contador()["usos"].get(command) or {"n": 0, "ultima": None}

    def _anotar_revision(self, command: str) -> None:
        estado = self._contador()
        uso = estado["usos"].get(command) or {"n": 0, "ultima": None}
        uso["n"] = int(uso.get("n", 0)) + 1
        uso["ultima"] = now_local().isoformat()
        estado["usos"][command] = uso
        with self.db.transaction():
            self.db.set_state(CONTADOR_KEY, estado)
            self.db.audit("gmail", "revision",
                          f"{command} {uso['n']}/{messages.GMAIL_LIMITE_DIARIO}")

    def _agotado(self, command: str) -> bool:
        return int(self._uso(command).get("n", 0)) >= messages.GMAIL_LIMITE_DIARIO

    # ------------------------------------------------------------ comandos

    def handle_command(self, command: str, raw_text: str) -> bool:
        if not command.startswith("/gmail_"):
            return False

        if not self.bridge.enabled:
            self._say(messages.GMAIL_DESHABILITADO)
            return True

        # Los botones de la fricción no consultan nada: ni acuse ni conteo.
        if command in FRICCION:
            return self._friccion_paso(command)

        # Mirar el buzón con las revisiones agotadas abre la fricción en vez
        # de la consulta. Abrir un correo concreto no pasa por acá.
        if command in REVISIONES and self._agotado(command):
            self._friccion = {"comando": command, "paso": "limite", "motivo": None}
            self._say(messages.gmail_limite_alcanzado(command),
                      buttons=messages.GMAIL_BOTONES_LIMITE)
            return True

        # Consultar el Apps Script tarda. El acuse va directo para que no
        # llegue junto con la respuesta, que es cuando ya no sirve de nada.
        if self.telegram and command != "/gmail_ayuda":
            try:
                self.telegram.send_message(
                    self.config.owner_chat_id, messages.GMAIL_CONSULTANDO
                )
            except Exception:
                pass

        try:
            hecho = self._dispatch(command, raw_text)
        except Exception as exc:
            self._say(f"Error Gmail Bridge: {exc}")
            return True

        # Se anota después de que la consulta salió bien: una revisión que
        # falló no gastó nada.
        if hecho and command in REVISIONES:
            self._anotar_revision(command)
        return hecho

    # ----------------------------------------------------------- fricción

    def _friccion_paso(self, command: str) -> bool:
        """Los cuatro botones. Ninguno abre el buzón salvo el último."""
        if command == "/gmail_dejarlo":
            self._friccion = None
            self._say(messages.GMAIL_DEJADO)
            return True

        if not self._friccion:
            # Un botón viejo, o el proceso se reinició en medio del flujo.
            self._say(messages.GMAIL_SIN_FRICCION)
            return True

        if command == "/gmail_igual":
            self._friccion["paso"] = "motivo"
            self._say(messages.GMAIL_PIDE_MOTIVO,
                      buttons=messages.GMAIL_BOTONES_MOTIVO)
            return True

        if command == "/gmail_reintentar":
            if not self._friccion.get("motivo"):
                self._say(messages.GMAIL_PIDE_MOTIVO,
                          buttons=messages.GMAIL_BOTONES_MOTIVO)
                return True
            return self._evaluar()

        # /gmail_si — el único punto que abre. Sólo desde la confirmación.
        if self._friccion.get("paso") != "confirmar":
            self._say(messages.GMAIL_SIN_FRICCION)
            return True

        objetivo = self._friccion["comando"]
        # Se limpia antes de consultar: un segundo clic ya no encuentra nada
        # que confirmar, así que no puede duplicar la revisión.
        self._friccion = None

        if self.telegram:
            try:
                self.telegram.send_message(
                    self.config.owner_chat_id, messages.GMAIL_CONSULTANDO
                )
            except Exception:
                pass
        try:
            hecho = self._dispatch(objetivo, objetivo)
        except Exception as exc:
            self._say(f"Error Gmail Bridge: {exc}")
            return True
        if hecho:
            self._anotar_revision(objetivo)
        return True

    def recibir_motivo(self, texto: str) -> bool:
        """El motivo escrito. Lo entrega el formulario del Panel."""
        if not self._friccion:
            self._say(messages.GMAIL_SIN_FRICCION)
            return True
        self._friccion["motivo"] = (texto or "").strip()
        return self._evaluar()

    def _contexto_operativo(self) -> str:
        """Sólo lo que Mástil sabe de verdad. Sin inferir relación alguna."""
        evento, pendientes = None, 0
        try:
            fila = self.db.one(
                "SELECT title FROM guardian_events "
                "WHERE is_active = 1 AND phase != 'done' LIMIT 1"
            )
            evento = fila["title"] if fila else None
            cuenta = self.db.one(
                "SELECT COUNT(*) AS c FROM guardian_events "
                "WHERE phase IN ('queued', 'decision')"
            )
            pendientes = int(cuenta["c"]) if cuenta else 0
        except Exception as exc:
            print(f"[gmail] sin contexto operativo: {exc}", flush=True)
        return messages.gmail_contexto_operativo(evento, pendientes)

    def _evaluar(self) -> bool:
        comando = self._friccion.get("comando", "")
        estado = self._uso(comando)
        ahora = now_local()
        ultima = estado.get("ultima")
        if ultima:
            desde = ahora - datetime.fromisoformat(ultima)
            horas, resto = divmod(int(desde.total_seconds()), 3600)
            transcurrido = f"{horas}h {resto // 60:02d}m"
            ultima_txt = datetime.fromisoformat(ultima).strftime("%H:%M")
        else:
            transcurrido = "desconocido"
            ultima_txt = "sin registro"

        prompt = messages.GMAIL_PROMPT.format(
            consulta=messages.GMAIL_NOMBRES.get(comando, comando),
            limite=messages.GMAIL_LIMITE_DIARIO,
            usadas=estado.get("n", 0),
            ahora=ahora.strftime("%d/%m/%Y %H:%M"),
            ultima=ultima_txt,
            transcurrido=transcurrido,
            motivo=self._friccion.get("motivo", ""),
            contexto=self._contexto_operativo(),
        )

        resultado = (
            self.vision.evaluar_texto(prompt) if self.vision
            else {"ok": False, "error": "sin Vision"}
        )
        if not resultado.get("ok"):
            # Que Gemini falle no es permiso: se queda donde estaba, con el
            # motivo intacto para poder reintentar sin volver a escribirlo.
            print(f"[gmail] evaluación fallida: {resultado.get('error')}", flush=True)
            self._friccion["paso"] = "motivo"
            self._say(messages.GMAIL_EVAL_FALLO, buttons=messages.GMAIL_BOTONES_FALLO)
            return True

        self._friccion["paso"] = "confirmar"
        self._say(
            messages.gmail_ultima_confirmacion(resultado["texto"]),
            buttons=messages.GMAIL_BOTONES_CONFIRMAR,
        )
        return True

    def _dispatch(self, command: str, raw_text: str) -> bool:
        if command == "/gmail_ayuda":
            self._say(messages.GMAIL_AYUDA)
            return True

        if command == "/gmail_asuntos":
            self._say(messages.GMAIL_ASUNTOS_RETIRADO)
            return True

        if command == "/gmail_hay":
            self._say(f"📬 Gmail\nHay {self.bridge.count_unread()} hilos no leídos en inbox.")
            return True

        if command == "/gmail_remitentes":
            items = self.bridge.list_unread()
            if not items:
                self._say(messages.GMAIL_SIN_NO_LEIDOS)
                return True

            with self.db.transaction():
                self.db.execute("DELETE FROM gmail_session")
                ahora = datetime.now().astimezone().isoformat()
                for numero, item in enumerate(items, 1):
                    self.db.execute(
                        """
                        INSERT INTO gmail_session(n, message_id, sender, subject, date, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (numero, item.get("id"), item.get("from"),
                         item.get("subject"), item.get("date"), ahora),
                    )

            lineas = ["📬 Remitentes no leídos\n"]
            for numero, item in enumerate(items, 1):
                lineas.append(f"{numero}. {item.get('from', '(sin remitente)')}")
            self._say("\n".join(lineas))
            return True

        match = re.match(
            r"^/gmail_contenido\s+(\d+)(?:\s+(natural|base64))?$",
            raw_text.strip().lower(),
        )
        if match:
            return self._content(int(match.group(1)), match.group(2) or "natural")

        return False

    def _content(self, numero: int, modo: str) -> bool:
        fila = self.db.one("SELECT * FROM gmail_session WHERE n = ?", (numero,))
        if not fila:
            self._say(messages.GMAIL_NUMERO_NO_ENCONTRADO)
            return True

        data = self.bridge.get_content(fila["message_id"])
        cuerpo = data.get("body", "")

        if modo == "base64":
            payload = json.dumps({
                "from": data.get("from"),
                "subject": data.get("subject"),
                "date": data.get("date"),
                "truncated": data.get("truncated"),
                "body": cuerpo,
            }, ensure_ascii=False, indent=2)
            codificado = base64.b64encode(payload.encode("utf-8")).decode("ascii")
            self._say(
                f"📬 Correo {numero} - Base64\n"
                "Asunto y contenido van codificados.\n\n"
                f"{codificado}"
            )
            return True

        self._say(
            f"📬 Correo {numero}\n\n"
            f"De: {data.get('from')}\n"
            f"Asunto: {data.get('subject')}\n"
            f"Fecha: {data.get('date')}\n"
            f"Truncado: {'sí' if data.get('truncated') else 'no'}\n\n"
            f"Contenido:\n{cuerpo}"
        )
        return True
