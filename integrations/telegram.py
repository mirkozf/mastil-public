"""Cliente de la API de Telegram.

En el legacy, Mástil Lite y Gmail Bridge interceptaban `getUpdates` parcheando
`urllib.request.urlopen` a nivel global: cada uno envolvía la función y leía la
respuesta al vuelo. Funcionaba, pero significaba que dos módulos podían leer el
mismo update sin que ninguno supiera del otro, y que el orden dependía de cuál
se importó primero.

Acá hay un solo cliente y un solo lector de updates. Quién atiende cada mensaje
lo decide `core/router.py`, explícitamente.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import queue
import struct
import threading
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Sequence

API_ROOT = "https://api.telegram.org"
API_HOST = "api.telegram.org"


class TelegramError(RuntimeError):
    pass


def _keyboard(buttons: Sequence[Any] | None) -> str | None:
    """Arma el teclado inline.

    Acepta dos formas:
      - plana:   [(etiqueta, comando), ...]        -> una sola fila
      - por filas: [[(e, c), (e, c)], [(e, c)]]    -> una fila por sublista
    """
    if not buttons:
        return None
    filas = buttons if isinstance(buttons[0], (list, tuple)) and buttons[0] and isinstance(
        buttons[0][0], (list, tuple)
    ) else [buttons]
    return json.dumps({
        "inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in fila]
            for fila in filas
        ]
    })


class Telegram:
    def __init__(self, token: str, timeout: int = 20):
        self.token = token
        self.timeout = timeout
        self._message_observer = None
        # Confirmar un botón no cambia ningún estado ni produce contenido.
        # Hacer esa llamada en el hilo principal agregaba una ida y vuelta
        # completa antes de empezar siquiera a editar el menú. Una cola
        # acotada y un único worker conservan el orden de los acuses sin
        # bloquear la respuesta visible del panel.
        self._callback_answers: queue.Queue[dict[str, Any]] = queue.Queue(
            maxsize=64
        )
        self._callback_worker: threading.Thread | None = None
        self._callback_worker_lock = threading.Lock()
        # Conexion reutilizable POR HILO.
        #
        # Abrir el canal contra Telegram cuesta ~115 ms de saludo (TCP mas
        # TLS) antes de mandar un solo byte util, y `urlopen` lo reabre en
        # cada llamada. Reusarla ahorra esos 115 ms en todas menos la
        # primera: es la mitad del tiempo de una transicion de menu.
        #
        # Por hilo y no compartida: el worker de los acuses corre en otro
        # hilo, y dos hilos sobre una misma conexion HTTP se pisan las
        # respuestas entre si.
        #
        # El long polling NO la usa (ver `get_updates`): se queda colgado
        # hasta un minuto esperando, y compartirla dejaria cada boton
        # esperando a que ese poll termine — peor que no reusar nada.
        self._local = threading.local()

    def set_message_observer(self, observer) -> None:
        """Observa envios aceptados sin acoplar los modulos a la politica."""
        self._message_observer = observer

    def _observe(self, chat_id: object, response: dict[str, Any], kind: str) -> None:
        if self._message_observer:
            self._message_observer(chat_id, response, kind)

    # ------------------------------------------------------------- básicos

    def _url(self, method: str) -> str:
        return f"{API_ROOT}/bot{self.token}/{method}"

    def _ruta(self, method: str) -> str:
        return f"/bot{self.token}/{method}"

    def _conexion(self) -> http.client.HTTPSConnection:
        """La conexion de ESTE hilo. Se abre la primera vez y se conserva."""
        conexion = getattr(self._local, "conexion", None)
        if conexion is None:
            conexion = http.client.HTTPSConnection(
                API_HOST, timeout=self.timeout)
            self._local.conexion = conexion
        return conexion

    def _soltar_conexion(self) -> None:
        """Descarta la conexion de este hilo. La proxima llamada abre otra."""
        conexion = getattr(self._local, "conexion", None)
        self._local.conexion = None
        if conexion is not None:
            try:
                conexion.close()
            except Exception:
                pass

    def api(self, method: str, payload: dict[str, Any] | None = None,
            reusar: bool = True) -> dict[str, Any]:
        """Llama a la API.

        Con `reusar` en False va por una conexion suelta: es lo que hace el
        long polling, que no puede ocupar la compartida.
        """
        data = urllib.parse.urlencode(payload).encode("utf-8") if payload else None
        if not reusar:
            return self._api_suelta(method, data)

        try:
            return self._api_reusando(method, data)
        except TelegramError:
            # Telegram contesto y rechazo: no es la conexion, es la
            # peticion. Reintentarla seria mandar dos veces lo mismo.
            raise
        except Exception as exc:
            # El otro lado pudo cerrar la conexion mientras estaba ociosa.
            # Se descarta y se reintenta UNA vez por la via de siempre: un
            # mensaje no se pierde por reusar el canal.
            print(f"[telegram] reabro la conexion tras {exc}", flush=True)
            self._soltar_conexion()
            return self._api_suelta(method, data)

    def _api_reusando(self, method: str, data) -> dict[str, Any]:
        conexion = self._conexion()
        conexion.request(
            "POST", self._ruta(method), body=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        respuesta = conexion.getresponse()
        cuerpo = respuesta.read()
        if respuesta.status >= 400:
            detalle = cuerpo.decode("utf-8", errors="replace")
            raise TelegramError(
                f"{method} HTTP {respuesta.status}: {detalle[:400]}")
        return json.loads(cuerpo.decode("utf-8"))

    def _api_suelta(self, method: str, data) -> dict[str, Any]:
        """Una conexion nueva, como se hacia siempre."""
        request = urllib.request.Request(self._url(method), data=data, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TelegramError(f"{method} HTTP {exc.code}: {detail[:400]}") from exc

    # ------------------------------------------------------------- updates

    def get_updates(self, offset: int, timeout: int = 1) -> list[dict[str, Any]]:
        # Por conexion suelta a proposito: este poll se queda colgado hasta
        # que llega algo, y ocupar la conexion compartida dejaria cualquier
        # boton esperando a que termine.
        result = self.api("getUpdates", {"offset": offset, "timeout": timeout},
                          reusar=False)
        return result.get("result", []) or []

    def drain_updates(self) -> int:
        """Descarta lo pendiente y devuelve el offset siguiente.

        Se usa sólo al arrancar: los mensajes que llegaron mientras Mástil
        estaba caído no deben disparar flujos con horas de retraso.
        """
        highest = 0
        for update in self.api("getUpdates", {"timeout": 0}).get("result", []) or []:
            highest = max(highest, int(update["update_id"]) + 1)
        return highest

    def answer_callback(
        self,
        callback_id: str,
        text: str = "",
        show_alert: bool = False,
    ) -> None:
        if not callback_id:
            return
        payload: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = "true"

        self._ensure_callback_worker()
        try:
            self._callback_answers.put_nowait(payload)
        except queue.Full:
            # Sólo puede ocurrir después de decenas de pulsaciones todavía
            # pendientes. El acuse es efímero: nunca debe frenar los mensajes
            # ni desplazar una acción real de la outbox.
            pass

    def _ensure_callback_worker(self) -> None:
        worker = self._callback_worker
        if worker and worker.is_alive():
            return
        with self._callback_worker_lock:
            worker = self._callback_worker
            if worker and worker.is_alive():
                return
            self._callback_worker = threading.Thread(
                target=self._answer_callbacks,
                name="mastil-telegram-callbacks",
                daemon=True,
            )
            self._callback_worker.start()

    def _answer_callbacks(self) -> None:
        while True:
            payload = self._callback_answers.get()
            try:
                self.api("answerCallbackQuery", payload)
            except Exception:
                # Un callback sin confirmar deja el botón girando, nada más.
                # El menú y su acción siguen por la vía durable normal.
                pass
            finally:
                self._callback_answers.task_done()

    # -------------------------------------------------------------- envío

    def send_message(
        self,
        chat_id: str,
        text: str,
        buttons: Sequence[tuple[str, str]] | None = None,
        parse_mode: str | None = None,
        disable_notification: bool = False,
    ) -> dict[str, Any]:
        """Un mensaje al chat.

        `disable_notification` lo entrega sin sonido ni vibración: llega y se
        ve igual, pero no interrumpe. Es para lo que no trae noticia, como el
        panel, que sólo cambia de lugar.
        """
        payload: dict[str, Any] = {"chat_id": str(chat_id), "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if disable_notification:
            payload["disable_notification"] = True
        teclado = _keyboard(buttons)
        if teclado:
            payload["reply_markup"] = teclado
        response = self.api("sendMessage", payload)
        self._observe(chat_id, response, "text")
        return response

    def edit_message(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        buttons: Sequence[tuple[str, str]] | None = None,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        """Reemplaza el contenido de un mensaje ya enviado.

        Sirve para que un flujo entero ocurra sobre un único mensaje en
        vez de encadenar seis. En un flujo largo, una pantalla que se
        llena de mensajes es ruido; uno solo que va cambiando, no.
        """
        payload: dict[str, Any] = {
            "chat_id": str(chat_id),
            "message_id": int(message_id),
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        payload["reply_markup"] = _keyboard(buttons) or json.dumps({"inline_keyboard": []})
        return self.api("editMessageText", payload)

    def send_photo(
        self,
        chat_id: str,
        photo_path: str | Path,
        caption: str = "",
        parse_mode: str | None = None,
        buttons: Sequence[Any] | None = None,
        caption_arriba: bool = False,
    ) -> dict[str, Any]:
        """Una foto, opcionalmente con teclado y con el texto por encima.

        Telegram pone el pie de foto **debajo** de la imagen salvo que se le
        pida `show_caption_above_media`. No hay forma de invertirlo desde el
        cliente: o va ese campo, o el texto queda abajo.
        """
        boundary = "----Mastil" + hashlib.sha256(os.urandom(16)).hexdigest()[:16]
        body = bytearray()

        def field(name: str, value: object) -> None:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            )
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")

        field("chat_id", chat_id)
        if caption:
            field("caption", caption)
        if parse_mode:
            field("parse_mode", parse_mode)
        if caption_arriba:
            field("show_caption_above_media", "true")
        teclado = _keyboard(buttons)
        if teclado:
            field("reply_markup", teclado)

        path = Path(photo_path)
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="photo"; '
            f'filename="{path.name}"\r\n'.encode()
        )
        body.extend(b"Content-Type: image/png\r\n\r\n")
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        request = urllib.request.Request(
            self._url("sendPhoto"), data=bytes(body), method="POST"
        )
        request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        request.add_header("Content-Length", str(len(body)))

        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                result = json.loads(response.read().decode("utf-8"))
            self._observe(chat_id, result, "photo")
            return result
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TelegramError(f"sendPhoto HTTP {exc.code}: {detail[:400]}") from exc

    def send_document(
        self,
        chat_id: str,
        path: str | Path,
        caption: str = "",
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        """Envía un archivo. Mismo multipart a mano que `send_photo`.

        Va directo y no por la outbox: el reporte se confirma recién cuando
        Telegram lo aceptó, igual que /sorpresa. Decir "generado" sin saberlo
        sería inventar un acuse de recibo.
        """
        boundary = "----Mastil" + hashlib.sha256(os.urandom(16)).hexdigest()[:16]
        body = bytearray()

        def field(name: str, value: object) -> None:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            )
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")

        field("chat_id", chat_id)
        if caption:
            field("caption", caption)
        if parse_mode:
            field("parse_mode", parse_mode)

        archivo = Path(path)
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="document"; '
            f'filename="{archivo.name}"\r\n'.encode()
        )
        body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
        body.extend(archivo.read_bytes())
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        request = urllib.request.Request(
            self._url("sendDocument"), data=bytes(body), method="POST"
        )
        request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        request.add_header("Content-Length", str(len(body)))

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
            self._observe(chat_id, result, "document")
            return result
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TelegramError(f"sendDocument HTTP {exc.code}: {detail[:400]}") from exc

    # -------------------------------------------------------------- borrado

    def delete_message(self, chat_id: str, message_id: int) -> dict[str, Any]:
        return self.api(
            "deleteMessage",
            {"chat_id": str(chat_id), "message_id": int(message_id)},
        )

    def delete_messages(
        self, chat_id: str, message_ids: Sequence[int]
    ) -> dict[str, Any]:
        ids = [int(message_id) for message_id in message_ids]
        if not ids:
            return {"ok": True, "result": True}
        return self.api(
            "deleteMessages",
            {"chat_id": str(chat_id), "message_ids": json.dumps(ids)},
        )

    # ---------------------------------------------------------- descargas

    def download_photo(self, file_id: str, dest_dir: Path, prefix: str = "photo") -> Path:
        """Baja una foto enviada por el usuario y devuelve su ruta local."""
        info = self.api("getFile", {"file_id": file_id})
        result = info.get("result", info)
        remote_path = result["file_path"]

        url = f"{API_ROOT}/file/bot{self.token}/{remote_path}"
        suffix = Path(remote_path).suffix or ".jpg"

        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / f"{prefix}-{os.urandom(6).hex()}{suffix}"

        with urllib.request.urlopen(url, timeout=30) as response:
            target.write_bytes(response.read())
        try:
            target.chmod(0o600)
        except OSError:
            pass
        return target


# ==========================================================================
# Imagen del código
# ==========================================================================
# Un número gigante en pantalla, legible sin lentes y a distancia. Lo usan
# tanto Mástil Lite (la usuaria asistida confirma escribiendo el número) como Vigía.
#
# Se dibuja con display de 7 segmentos y se escribe el PNG a mano con zlib y
# struct. Parece exagerado, pero evita depender de Pillow y de que existan
# fuentes en el sistema: si la imagen no sale, la persona se queda sin poder
# apagar su recordatorio.

_SEGMENTS = {
    "0": "ABCDEF", "1": "BC", "2": "ABGED", "3": "ABGCD",
    "4": "FBGC", "5": "AFGCD", "6": "AFGECD", "7": "ABC",
    "8": "ABCDEFG", "9": "ABFGCD",
}


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    raw = tag + data
    return (
        struct.pack("!I", len(data))
        + raw
        + struct.pack("!I", zlib.crc32(raw) & 0xFFFFFFFF)
    )


def _write_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    rows = bytearray()
    for y in range(height):
        rows.append(0)                       # filtro "none" por fila
        start = y * width * 3
        rows.extend(pixels[start:start + width * 3])

    data = b"\x89PNG\r\n\x1a\n"
    data += _png_chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0))
    data += _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    data += _png_chunk(b"IEND", b"")
    path.write_bytes(data)


def _rect(pixels: bytearray, width: int, height: int,
          x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int]) -> None:
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(width, int(x2)), min(height, int(y2))
    red, green, blue = color
    for y in range(y1, y2):
        base = y * width * 3
        for x in range(x1, x2):
            index = base + x * 3
            pixels[index:index + 3] = bytes((red, green, blue))


# Tipografia de 5x7 para la secuencia de la tregua. El renderizador de siete
# segmentos de mas abajo solo sabe dibujar digitos y le alcanza el lienzo para
# cuatro; la secuencia lleva letras y simbolos a proposito.
#
# Cada glifo son 35 caracteres: siete filas de cinco, concatenadas. "#" pinta,
# "." deja el fondo.
_FUENTE_5X7 = {
    "!": "..#....#....#....#....#.........#..",
    "#": ".#.#..#.#.#####.#.#.#####.#.#..#.#.",
    "$": "..#...#####.#...###...#.#####...#..",
    "%": "##..###..#...#...#...#...#..###..##",
    "*": ".....#.#.#.###.#####.###.#.#.#.....",
    "+": ".......#....#..#####..#....#.......",
    "2": ".###.#...#....#..##..#...#....#####",
    "3": "#####....#...#...##.....##...#.###.",
    "4": "...#...##..#.#.#..#.#####...#....#.",
    "5": "######....####.....#....##...#.###.",
    "6": "..##..#...#....####.#...##...#.###.",
    "7": "#####....#...#...#...#....#....#...",
    "8": ".###.#...##...#.###.#...##...#.###.",
    "9": ".###.#...##...#.####....#...#..##..",
    "=": "..........#####.....#####..........",
    "?": ".###.#...#....#...#...#.........#..",
    "A": ".###.#...##...#######...##...##...#",
    "B": "####.#...##...#####.#...##...#####.",
    "C": ".###.#...##....#....#....#...#.###.",
    "D": "###..#..#.#...##...##...##..#.###..",
    "E": "######....#....####.#....#....#####",
    "F": "######....#....####.#....#....#....",
    "G": ".###.#...##....#.####...##...#.###.",
    "H": "#...##...##...#######...##...##...#",
    "J": "..###...#....#....#....#.#..#..##..",
    "K": "#...##..#.#.#..##...#.#..#..#.#...#",
    "L": "#....#....#....#....#....#....#####",
    "M": "#...###.###.#.##.#.##...##...##...#",
    "N": "#...###..##.#.##.#.##..###...##...#",
    "P": "####.#...##...#####.#....#....#....",
    "Q": ".###.#...##...##...##.#.##..#..##.#",
    "R": "####.#...##...#####.#.#..#..#.#...#",
    "S": ".#####....#.....###.....#....#####.",
    "T": "#####..#....#....#....#....#....#..",
    "U": "#...##...##...##...##...##...#.###.",
    "V": "#...##...##...##...##...#.#.#...#..",
    "W": "#...##...##...##.#.##.#.###.###...#",
    "X": "#...##...#.#.#...#...#.#.#...##...#",
    "Y": "#...##...#.#.#...#....#....#....#..",
    "Z": "#####....#...#...#...#...#....#####",
}


def _glifo(caracter: str) -> list[str]:
    """Las siete filas de cinco pixeles de un caracter."""
    crudo = _FUENTE_5X7.get(caracter)
    if not crudo or len(crudo) != 35:
        return ["....."] * 7
    return [crudo[i * 5:(i + 1) * 5] for i in range(7)]


def make_text_image(texto: str, path: str | Path) -> Path:
    """La secuencia de la tregua, dibujada. De aca no se puede copiar.

    En texto se copia y se pega, y pegar no cuesta atencion: es justo el piloto
    automatico del que la tregua tiene que sacarte. Comparte marco y paleta con
    el codigo de cuatro digitos para que se lea como otra pantalla de Guardian.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    texto = str(texto)
    escala, separacion, margen, grosor = 16, 22, 46, 16
    ancho_glifo, alto_glifo = 5 * escala, 7 * escala

    width = margen * 2 + len(texto) * ancho_glifo + max(0, len(texto) - 1) * separacion
    height = margen * 2 + alto_glifo
    background = (255, 250, 238)
    ink = (18, 24, 33)
    border = (204, 34, 34)

    pixels = bytearray(bytes(background) * (width * height))

    _rect(pixels, width, height, 0, 0, width, grosor, border)
    _rect(pixels, width, height, 0, height - grosor, width, height, border)
    _rect(pixels, width, height, 0, 0, grosor, height, border)
    _rect(pixels, width, height, width - grosor, 0, width, height, border)

    x = margen
    for caracter in texto:
        for fila, patron in enumerate(_glifo(caracter)):
            for columna, punto in enumerate(patron):
                if punto == "#":
                    px, py = x + columna * escala, margen + fila * escala
                    _rect(pixels, width, height, px, py, px + escala, py + escala, ink)
        x += ancho_glifo + separacion

    _write_png(path, width, height, pixels)
    return path


def make_code_image(code: str, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    width, height = 900, 360
    background = (255, 250, 238)
    ink = (18, 24, 33)
    border = (204, 34, 34)

    pixels = bytearray(bytes(background) * (width * height))

    _rect(pixels, width, height, 0, 0, width, 20, border)
    _rect(pixels, width, height, 0, height - 20, width, height, border)
    _rect(pixels, width, height, 0, 0, 20, height, border)
    _rect(pixels, width, height, width - 20, 0, width, height, border)

    digit_w, digit_h, thick, gap = 150, 260, 30, 35
    code = str(code)
    total_w = len(code) * digit_w + (len(code) - 1) * gap
    x = (width - total_w) // 2
    y = 50

    for digit in code:
        coords = {
            "A": (x + thick, y, x + digit_w - thick, y + thick),
            "B": (x + digit_w - thick, y + thick, x + digit_w, y + digit_h // 2 - thick // 2),
            "C": (x + digit_w - thick, y + digit_h // 2 + thick // 2, x + digit_w, y + digit_h - thick),
            "D": (x + thick, y + digit_h - thick, x + digit_w - thick, y + digit_h),
            "E": (x, y + digit_h // 2 + thick // 2, x + thick, y + digit_h - thick),
            "F": (x, y + thick, x + thick, y + digit_h // 2 - thick // 2),
            "G": (x + thick, y + digit_h // 2 - thick // 2, x + digit_w - thick, y + digit_h // 2 + thick // 2),
        }
        for segment in _SEGMENTS.get(digit, ""):
            _rect(pixels, width, height, *coords[segment], ink)
        x += digit_w + gap

    _write_png(path, width, height, pixels)
    return path
