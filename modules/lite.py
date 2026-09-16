"""Mástil Lite: recordatorios para la usuaria asistida.

Es el módulo con las reglas de privacidad más estrictas del sistema. El
propietario puede saber que **hubo** un recordatorio, que se creó o que no se
confirmó. Nunca su texto. Por eso `activity_enc` va cifrado en la base y sólo
se descifra para mostrárselo a ella.

La experiencia es deliberadamente rígida: se entra escribiendo «recordar» y se
sale por la misma palabra, con un número de cuatro dígitos en una imagen grande
para apagar la alarma. Sin comandos con `/`, sin botones, sin menús.

Hay dos caminos para crear, y conviven: la sintaxis completa de una sola línea
(`recordar hoy 21:30 bañarme`), y un borrador guiado que pregunta de a una cosa
por vez cuando esa sintaxis no sale. Componer la línea entera de memoria es
justamente lo caro; el borrador paga ese costo.

El cifrado es el mismo del legacy, byte por byte: los recordatorios que ya
existen se siguen leyendo sin recifrar nada.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import messages
from integrations.telegram import make_code_image

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
}
NOMBRE_MES = {v: k for k, v in MESES.items() if k != "setiembre"}

# Pasos del borrador guiado.
PASO_ACTIVIDAD = "actividad"
PASO_DIA = "dia"
PASO_HORA = "hora"
PASO_FRANJA = "franja"
PASO_CONFIRMAR = "confirmar"

# Un borrador a medias no se guarda para siempre: vence solo y en silencio.
# No insiste ni vuelve a preguntar — Lite no es Guardian.
BORRADOR_MINUTOS = 15

# Respuestas libres. Van sin tildes porque se comparan contra `_norm`.
CANCELAR = {"nada", "cancelar", "dejalo", "dejarlo", "chao", "olvidalo",
            "no importa", "salir", "ninguno", "ninguna"}
SI = {"si", "ya", "listo", "correcto", "esta bien", "ok", "dale", "bueno",
      "asi es", "confirmo", "claro"}
NO = {"no", "esta mal", "cambiar", "otra vez", "mal"}


def _norm(text: str) -> str:
    text = (text or "").strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


class LiteModule:
    def __init__(self, config, db):
        self.config = config
        self.db = db
        self._secret: bytes | None = None
        self._ensure_settings()

    def _ensure_settings(self) -> None:
        with self.db.transaction():
            for user in self.config.lite_users:
                self.db.execute(
                    """
                    INSERT OR IGNORE INTO lite_settings(user_chat_id, paused, updated_at_utc)
                    VALUES (?, 0, ?)
                    """,
                    (user.chat_id, datetime.now(timezone.utc).isoformat()),
                )

    # ------------------------------------------------------------- cifrado

    def secret(self) -> bytes:
        if self._secret is not None:
            return self._secret
        path = self.config.lite_secret_path
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(base64.urlsafe_b64encode(os.urandom(32)))
        self._secret = base64.urlsafe_b64decode(path.read_bytes().strip())
        return self._secret

    def _stream(self, nonce: bytes, length: int) -> bytes:
        key = self.secret()
        out = b""
        index = 0
        while len(out) < length:
            out += hashlib.sha256(key + nonce + index.to_bytes(4, "big")).digest()
            index += 1
        return out[:length]

    def encrypt(self, text: str) -> str:
        data = text.encode("utf-8")
        nonce = os.urandom(16)
        cipher = bytes(a ^ b for a, b in zip(data, self._stream(nonce, len(data))))
        return base64.urlsafe_b64encode(nonce + cipher).decode("ascii")

    def decrypt(self, payload: str) -> str:
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        nonce, cipher = raw[:16], raw[16:]
        data = bytes(a ^ b for a, b in zip(cipher, self._stream(nonce, len(cipher))))
        return data.decode("utf-8")

    # -------------------------------------------------------------- envíos

    def _to_user(self, chat_id: str, text: str, photo=None, delete_photo=False) -> None:
        self.db.enqueue(chat_id, text, photo_path=photo,
                        parse_mode="HTML", delete_photo=delete_photo)

    def _to_owner(self, text: str) -> None:
        self.db.enqueue(self.config.owner_chat_id, text)

    # -------------------------------------------------------------- parsing

    def parse(self, text: str, tz: str):
        ahora = datetime.now(ZoneInfo(tz))

        match = re.match(r"^\s*recordar\s+hoy\s+(\d{1,2}):([0-5]\d)\s+(.+?)\s*$", text, re.I)
        if match:
            hh, mm, actividad = int(match.group(1)), int(match.group(2)), match.group(3).strip()
            if hh > 23 or not actividad:
                return None
            cuando = ahora.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if cuando <= ahora:
                return None
            return cuando, "hoy", f"{hh:02d}:{mm:02d}", actividad

        match = re.match(
            r"^\s*recordar\s+(\d{1,2})\s+de\s+([a-zA-ZáéíóúñÁÉÍÓÚÑ]+)\s+(\d{1,2}):([0-5]\d)\s+(.+?)\s*$",
            text, re.I,
        )
        if not match:
            return None

        dia = int(match.group(1))
        mes = MESES.get(_norm(match.group(2)))
        hh, mm = int(match.group(3)), int(match.group(4))
        actividad = match.group(5).strip()

        if not mes or hh > 23 or not actividad:
            return None
        try:
            cuando = datetime(ahora.year, mes, dia, hh, mm, tzinfo=ZoneInfo(tz))
        except ValueError:
            return None
        if cuando <= ahora:
            cuando = datetime(ahora.year + 1, mes, dia, hh, mm, tzinfo=ZoneInfo(tz))

        return cuando, f"{dia} de {NOMBRE_MES[mes]}", f"{hh:02d}:{mm:02d}", actividad

    # ------------------------------------------------------------- mensajes

    def matches(self, chat_id: str, text: str) -> bool:
        """¿Este texto es para Lite?

        Existe por el modo espejo: el propietario puede figurar como usuaria
        Lite para probar el flujo completo sobre sí mismo. Pero su chat también
        recibe comandos y las respuestas libres de Vigía, así que Lite sólo
        puede quedarse con lo que inequívocamente le pertenece.

        El caso delicado son los 4 dígitos, porque Vigía usa códigos del mismo
        largo. Se resuelve por hecho, no por adivinanza: Lite reclama el número
        únicamente si tiene una alarma sonando para ese chat. Si no la tiene,
        el texto sigue de largo hacia Vigía.
        """
        if not self.config.lite_user(chat_id):
            return False

        limpio = _norm(text)
        if limpio.startswith("recordar") or limpio == "recuerdame":
            return True

        if re.match(r"^\d{4}$", limpio):
            fila = self.db.one(
                """
                SELECT id FROM lite_reminders
                WHERE user_chat_id = ? AND status = 'alerting' AND alert_code = ?
                LIMIT 1
                """,
                (str(chat_id), limpio),
            )
            return fila is not None

        # Un borrador abierto reclama cualquier respuesta suya: está
        # contestando una pregunta, no escribiendo un comando. Mismo criterio
        # que arriba — se resuelve por hecho, no por adivinanza.
        return self._borrador_leer(chat_id) is not None

    def handle_message(self, chat_id: str, text: str) -> bool:
        user = self.config.lite_user(chat_id)
        if not user:
            return False

        limpio = _norm(text)

        # Una alarma sonando manda sobre todo lo demás: apagarla es lo urgente.
        # Además su código son 4 dígitos, que en mitad de un borrador podrían
        # confundirse con una hora, así que el desempate va primero y por hecho.
        if re.match(r"^\d{4}$", limpio) and self._alarma_sonando(chat_id):
            return self._confirm(user, limpio)

        borrador = self._borrador_leer(chat_id)
        if borrador is not None:
            return self._borrador_paso(user, borrador, text, limpio)

        if limpio in ("/start", "start", "hola", "hola soy yo"):
            with self.db.transaction():
                self._to_user(chat_id, messages.LITE_BIENVENIDA)
            return True

        if limpio == "recuerdame":
            return self._list(user)

        if re.match(r"^\d{4}$", limpio):
            return self._confirm(user, limpio)

        if limpio.startswith("recordar"):
            return self._create(user, text)

        with self.db.transaction():
            self._to_user(chat_id, messages.LITE_AYUDA)
            self._to_owner(messages.lite_aviso_invalido(user.name))
        return True

    def _create(self, user, text: str) -> bool:
        parsed = self.parse(text, user.timezone)
        if not parsed:
            # La línea completa no salió. Devolverle el formato sería devolverle
            # justo lo caro: componer la frase entera de memoria. Se abre el
            # borrador y se le pregunta de a una cosa.
            return self._borrador_abrir(user, text)

        cuando, fecha, hora, actividad = parsed
        with self.db.transaction():
            self._guardar(user, cuando, fecha, hora, actividad)
        return True

    def _guardar(self, user, cuando, fecha: str, hora: str, actividad: str,
                 cierre: str = "") -> None:
        """Inserta el recordatorio y avisa. Va DENTRO de una transacción.

        Los dos caminos de creación —la línea completa y el borrador guiado—
        terminan acá, así que el cifrado y el aviso al propietario no pueden
        quedar distintos según por dónde se entró.
        """
        self.db.execute(
            """
            INSERT INTO lite_reminders
                (user_chat_id, user_name, remind_at_utc, display_date,
                 display_time, activity_enc, status, created_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                user.chat_id, user.name,
                cuando.astimezone(timezone.utc).isoformat(),
                fecha, hora, self.encrypt(actividad),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._to_user(user.chat_id,
                      messages.lite_creado(fecha, hora, actividad) + cierre)
        self._to_owner(messages.lite_aviso_creado(user.name))
        self.db.audit("lite", "create")

    # ------------------------------------------------------------- borrador
    #
    # El borrador vive en `system_state`, no en una tabla nueva: es una fila por
    # usuaria y se borra al terminar.
    #
    # Va CIFRADO con la misma llave de los recordatorios. Contiene el texto que
    # ella escribió antes de que exista la fila definitiva, así que dejarlo en
    # claro filtraría exactamente lo que este módulo existe para proteger.

    def _borrador_key(self, chat_id: str) -> str:
        return f"lite_borrador:{chat_id}"

    def _borrador_leer(self, chat_id: str):
        crudo = self.db.get_state(self._borrador_key(chat_id))
        if not crudo:
            return None
        try:
            datos = json.loads(self.decrypt(crudo))
            nacido = datetime.fromisoformat(datos["creado"])
        except Exception:
            self._borrador_descartar(chat_id)
            return None

        vencido = (datetime.now(timezone.utc) - nacido).total_seconds()
        if vencido > BORRADOR_MINUTOS * 60:
            self._borrador_descartar(chat_id)
            return None
        return datos

    def _borrador_descartar(self, chat_id: str) -> None:
        """Limpieza perezosa, fuera de transacción: nadie recibe un mensaje."""
        with self.db.transaction():
            self._borrador_borrar(chat_id)

    def _borrador_borrar(self, chat_id: str) -> None:
        self.db.execute("DELETE FROM system_state WHERE key = ?",
                        (self._borrador_key(chat_id),))

    def _borrador_guardar(self, chat_id: str, datos: dict) -> None:
        self.db.set_state(
            self._borrador_key(chat_id),
            self.encrypt(json.dumps(datos, ensure_ascii=False)),
        )

    def _alarma_sonando(self, chat_id: str) -> bool:
        fila = self.db.one(
            "SELECT id FROM lite_reminders WHERE user_chat_id = ? AND status = 'alerting' LIMIT 1",
            (str(chat_id),),
        )
        return fila is not None

    def _borrador_abrir(self, user, text: str) -> bool:
        resto = re.sub(r"^\s*recordar\s*", "", text, flags=re.I).strip()

        # El resto sólo se toma como actividad si no arranca con algo que
        # parezca fecha u hora: `recordar hoy 25:00 x` es un intento fallido de
        # la sintaxis vieja, no una tarea que se llama «hoy 25:00 x».
        primera = _norm(resto).split(" ")[0] if resto else ""
        parece_fecha = (not resto) or primera in ("hoy", "manana") or primera.isdigit()
        actividad = "" if parece_fecha else resto

        datos = {
            "paso": PASO_DIA if actividad else PASO_ACTIVIDAD,
            "actividad": actividad,
            "creado": datetime.now(timezone.utc).isoformat(),
        }
        with self.db.transaction():
            self._borrador_guardar(user.chat_id, datos)
            self._to_user(
                user.chat_id,
                messages.LITE_GUIA_DIA if actividad else messages.LITE_GUIA_ACTIVIDAD,
            )
        return True

    def _borrador_paso(self, user, datos: dict, text: str, limpio: str) -> bool:
        if limpio in CANCELAR:
            with self.db.transaction():
                self._borrador_borrar(user.chat_id)
                self._to_user(user.chat_id, messages.LITE_GUIA_CANCELADO)
            return True

        paso = datos.get("paso")

        if paso == PASO_ACTIVIDAD:
            actividad = text.strip()
            if not actividad:
                with self.db.transaction():
                    self._to_user(user.chat_id, messages.LITE_GUIA_ACTIVIDAD)
                return True
            datos["actividad"] = actividad
            datos["paso"] = PASO_DIA
            with self.db.transaction():
                self._borrador_guardar(user.chat_id, datos)
                self._to_user(user.chat_id, messages.LITE_GUIA_DIA)
            return True

        if paso == PASO_DIA:
            dia = self._parse_dia(limpio, user.timezone)
            if not dia:
                with self.db.transaction():
                    self._to_user(user.chat_id, messages.LITE_GUIA_DIA_OTRA_VEZ)
                return True
            datos["dia"], datos["fecha"] = dia
            datos["paso"] = PASO_HORA
            with self.db.transaction():
                self._borrador_guardar(user.chat_id, datos)
                self._to_user(user.chat_id, messages.LITE_GUIA_HORA)
            return True

        if paso == PASO_HORA:
            # Si la hora de hoy ya pasó, «mañana» corre el día sin obligarla a
            # empezar todo de nuevo.
            if limpio == "manana":
                return self._borrador_mover_manana(user, datos)

            hora = self._parse_hora(limpio)
            if not hora:
                with self.db.transaction():
                    self._to_user(user.chat_id, messages.LITE_GUIA_HORA_OTRA_VEZ)
                return True

            hh, mm, ambiguo = hora
            if ambiguo:
                datos["hh"], datos["mm"] = hh, mm
                datos["paso"] = PASO_FRANJA
                with self.db.transaction():
                    self._borrador_guardar(user.chat_id, datos)
                    self._to_user(user.chat_id, messages.LITE_GUIA_FRANJA)
                return True
            return self._borrador_hora_lista(user, datos, hh, mm)

        if paso == PASO_FRANJA:
            franja = self._parse_franja(limpio)
            if franja is None:
                with self.db.transaction():
                    self._to_user(user.chat_id, messages.LITE_GUIA_FRANJA)
                return True
            hh = int(datos.get("hh", 0)) % 12
            if franja == "pm":
                hh += 12
            return self._borrador_hora_lista(user, datos, hh, int(datos.get("mm", 0)))

        if paso == PASO_CONFIRMAR:
            if limpio in SI:
                return self._borrador_cerrar(user, datos)
            if limpio in NO:
                with self.db.transaction():
                    self._borrador_borrar(user.chat_id)
                    self._to_user(user.chat_id, messages.LITE_GUIA_CANCELADO)
                return True
            with self.db.transaction():
                self._to_user(user.chat_id, messages.LITE_GUIA_CONFIRMA_OTRA_VEZ)
            return True

        # Paso desconocido: nunca dejarla atrapada en un borrador sin salida.
        with self.db.transaction():
            self._borrador_borrar(user.chat_id)
            self._to_user(user.chat_id, messages.LITE_AYUDA)
        return True

    def _borrador_mover_manana(self, user, datos: dict) -> bool:
        manana = (datetime.now(ZoneInfo(user.timezone)) + timedelta(days=1)).date()
        datos["dia"] = manana.isoformat()
        datos["fecha"] = "mañana"
        datos["paso"] = PASO_HORA
        with self.db.transaction():
            self._borrador_guardar(user.chat_id, datos)
            self._to_user(user.chat_id, messages.LITE_GUIA_MANANA)
        return True

    def _borrador_hora_lista(self, user, datos: dict, hh: int, mm: int) -> bool:
        cuando = self._componer(datos, hh, mm, user.timezone)
        if cuando <= datetime.now(ZoneInfo(user.timezone)):
            datos["paso"] = PASO_HORA
            with self.db.transaction():
                self._borrador_guardar(user.chat_id, datos)
                self._to_user(user.chat_id, messages.LITE_GUIA_HORA_PASADA)
            return True

        datos["hora"] = f"{hh:02d}:{mm:02d}"
        datos["paso"] = PASO_CONFIRMAR
        with self.db.transaction():
            self._borrador_guardar(user.chat_id, datos)
            self._to_user(user.chat_id, messages.lite_guia_confirmar(
                datos["fecha"], datos["hora"], datos["actividad"]))
        return True

    def _borrador_cerrar(self, user, datos: dict) -> bool:
        hh, mm = (int(parte) for parte in datos["hora"].split(":"))
        cuando = self._componer(datos, hh, mm, user.timezone)

        # Se revalida al confirmar: entre la pregunta y el «sí» pudo pasar la
        # hora, y un recordatorio que nace vencido no avisa nunca.
        if cuando <= datetime.now(ZoneInfo(user.timezone)):
            datos["paso"] = PASO_HORA
            with self.db.transaction():
                self._borrador_guardar(user.chat_id, datos)
                self._to_user(user.chat_id, messages.LITE_GUIA_HORA_PASADA)
            return True

        with self.db.transaction():
            self._borrador_borrar(user.chat_id)
            self._guardar(user, cuando, datos["fecha"], datos["hora"],
                          datos["actividad"], cierre=messages.LITE_INVITACION)
        return True

    def _componer(self, datos: dict, hh: int, mm: int, tz: str) -> datetime:
        dia = date.fromisoformat(datos["dia"])
        return datetime(dia.year, dia.month, dia.day, hh, mm, tzinfo=ZoneInfo(tz))

    def _parse_dia(self, limpio: str, tz: str):
        """Devuelve (fecha ISO, etiqueta para mostrar) o None."""
        ahora = datetime.now(ZoneInfo(tz))
        if limpio == "hoy":
            return ahora.date().isoformat(), "hoy"
        if limpio == "manana":
            return (ahora + timedelta(days=1)).date().isoformat(), "mañana"

        match = re.match(r"^(\d{1,2})\s*(?:de\s+)?([a-z]+)$", limpio)
        if not match:
            return None
        mes = MESES.get(match.group(2))
        if not mes:
            return None
        try:
            fecha = date(ahora.year, mes, int(match.group(1)))
        except ValueError:
            return None
        if fecha < ahora.date():
            try:
                fecha = date(ahora.year + 1, mes, int(match.group(1)))
            except ValueError:
                return None
        return fecha.isoformat(), f"{int(match.group(1))} de {NOMBRE_MES[mes]}"

    def _parse_hora(self, limpio: str):
        """Devuelve (hh, mm, ambiguo) o None.

        `ambiguo` es True cuando dijo un número de 1 a 12 sin aclarar si era de
        la mañana o de la tarde. Ahí se pregunta en vez de adivinar: un recordatorio
        a las nueve de la noche en vez de las nueve de la mañana no es un detalle.
        """
        match = re.match(r"^(\d{2})(\d{2})$", limpio)
        if match:
            hh, mm = int(match.group(1)), int(match.group(2))
            if hh > 23 or mm > 59:
                return None
            return hh, mm, 1 <= hh <= 12

        match = re.match(r"^(?:a\s+las\s+)?(\d{1,2})(?:[:.\s](\d{1,2}))?\s*(.*)$", limpio)
        if not match:
            return None
        hh = int(match.group(1))
        mm = int(match.group(2) or 0)
        if hh > 23 or mm > 59:
            return None

        franja = self._parse_franja(match.group(3) or "")
        if franja == "am":
            return (0 if hh == 12 else hh), mm, False
        if franja == "pm":
            return (hh if hh >= 12 else hh + 12), mm, False

        if hh == 0 or hh >= 13:
            return hh, mm, False
        return hh, mm, True

    def _parse_franja(self, limpio: str):
        if not limpio:
            return None
        if re.search(r"\b(am|manana|madrugada)\b", limpio):
            return "am"
        if re.search(r"\b(pm|tarde|noche|mediodia)\b", limpio):
            return "pm"
        return None

    def _list(self, user) -> bool:
        filas = self.db.query(
            """
            SELECT * FROM lite_reminders
            WHERE user_chat_id = ? AND status IN ('pending', 'alerting')
            ORDER BY remind_at_utc ASC LIMIT 20
            """,
            (user.chat_id,),
        )
        with self.db.transaction():
            if not filas:
                self._to_user(user.chat_id, messages.LITE_SIN_PENDIENTES)
                return True

            ahora = datetime.now(ZoneInfo(user.timezone))
            items = []
            for fila in filas:
                cuando = datetime.fromisoformat(fila["remind_at_utc"]).astimezone(
                    ZoneInfo(user.timezone)
                )
                fecha = "Hoy" if cuando.date() == ahora.date() else (
                    f"{cuando.day} de {NOMBRE_MES[cuando.month]}"
                )
                items.append((fecha, fila["display_time"], self.decrypt(fila["activity_enc"])))
            self._to_user(user.chat_id, messages.lite_listado(items))
        return True

    def _confirm(self, user, code: str) -> bool:
        fila = self.db.one(
            """
            SELECT * FROM lite_reminders
            WHERE user_chat_id = ? AND status = 'alerting' AND alert_code = ?
            ORDER BY first_alert_utc ASC LIMIT 1
            """,
            (user.chat_id, code),
        )
        with self.db.transaction():
            if not fila:
                self._to_user(user.chat_id, messages.LITE_CODIGO_NO_ENCONTRADO)
                return True
            self.db.execute(
                "UPDATE lite_reminders SET status='confirmed', confirmed_at_utc=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), fila["id"]),
            )
            self._to_user(user.chat_id, messages.LITE_APAGADO)
            self.db.audit("lite", "confirm")
        return True

    # ------------------------------------------------------------------ tick

    def _paused(self, chat_id: str) -> bool:
        fila = self.db.one(
            "SELECT paused FROM lite_settings WHERE user_chat_id = ?", (chat_id,)
        )
        return bool(fila and fila["paused"])

    def tick(self) -> None:
        ahora = datetime.now(timezone.utc)

        # 1. Los que vencieron pasan a sonar, con su código.
        vencidos = self.db.query(
            "SELECT * FROM lite_reminders WHERE status='pending' AND remind_at_utc <= ?",
            (ahora.isoformat(),),
        )
        for fila in vencidos:
            if self._paused(fila["user_chat_id"]):
                continue
            with self.db.transaction():
                self.db.execute(
                    """
                    UPDATE lite_reminders
                    SET status='alerting', alert_code=?, first_alert_utc=?, last_alert_utc=?
                    WHERE id=?
                    """,
                    (f"{random.randint(1000, 9999)}", ahora.isoformat(),
                     "1970-01-01T00:00:00+00:00", fila["id"]),
                )

        # 2. Los que están sonando: insistir o rendirse.
        for fila in self.db.query(
            "SELECT * FROM lite_reminders WHERE status='alerting' ORDER BY first_alert_utc ASC"
        ):
            if self._paused(fila["user_chat_id"]):
                continue

            primero = datetime.fromisoformat(fila["first_alert_utc"])
            ultimo = datetime.fromisoformat(fila["last_alert_utc"])

            if (ahora - primero).total_seconds() >= self.config.lite_max_alert_seconds:
                with self.db.transaction():
                    self.db.execute(
                        "UPDATE lite_reminders SET status='timeout', timeout_at_utc=? WHERE id=?",
                        (ahora.isoformat(), fila["id"]),
                    )
                    self._to_user(fila["user_chat_id"], messages.LITE_DETENIDO)
                    self._to_owner(messages.lite_aviso_sin_confirmar(fila["user_name"]))
                continue

            if (ahora - ultimo).total_seconds() >= self.config.lite_alert_every_seconds:
                self._alert(fila, ahora)

    def _alert(self, fila, ahora: datetime) -> None:
        actividad = self.decrypt(fila["activity_enc"])
        caption = messages.lite_alerta(actividad)
        destino = self.config.evidence_dir.parent / "lite"
        destino.mkdir(parents=True, exist_ok=True)
        imagen = destino / f"codigo-{fila['id']}-{int(ahora.timestamp())}.png"

        try:
            make_code_image(fila["alert_code"], imagen)
        except Exception as exc:
            # Si la imagen falla, el número va en texto. Nunca dejarla sin
            # forma de apagar la alarma.
            print(f"[lite] no pude generar la imagen: {exc}", flush=True)
            with self.db.transaction():
                self.db.execute(
                    "UPDATE lite_reminders SET last_alert_utc=? WHERE id=?",
                    (ahora.isoformat(), fila["id"]),
                )
                self._to_user(
                    fila["user_chat_id"],
                    f"{caption}\n\n<b>Número:</b> <code>{fila['alert_code']}</code>",
                )
            return

        with self.db.transaction():
            self.db.execute(
                "UPDATE lite_reminders SET last_alert_utc=? WHERE id=?",
                (ahora.isoformat(), fila["id"]),
            )
            self._to_user(fila["user_chat_id"], caption,
                          photo=str(imagen), delete_photo=True)
