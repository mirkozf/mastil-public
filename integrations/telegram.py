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
import json
import os
import struct
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Sequence

API_ROOT = "https://api.telegram.org"


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

    # ------------------------------------------------------------- básicos

    def _url(self, method: str) -> str:
        return f"{API_ROOT}/bot{self.token}/{method}"

    def api(self, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = urllib.parse.urlencode(payload).encode("utf-8") if payload else None
        request = urllib.request.Request(self._url(method), data=data, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TelegramError(f"{method} HTTP {exc.code}: {detail[:400]}") from exc

    # ------------------------------------------------------------- updates

    def get_updates(self, offset: int, timeout: int = 1) -> list[dict[str, Any]]:
        result = self.api("getUpdates", {"offset": offset, "timeout": timeout})
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
        payload: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = "true"
        try:
            self.api("answerCallbackQuery", payload)
        except Exception:
            # Un callback sin confirmar deja el botón girando, nada más.
            pass

    # -------------------------------------------------------------- envío

    def send_message(
        self,
        chat_id: str,
        text: str,
        buttons: Sequence[tuple[str, str]] | None = None,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": str(chat_id), "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        teclado = _keyboard(buttons)
        if teclado:
            payload["reply_markup"] = teclado
        return self.api("sendMessage", payload)

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
        vez de encadenar seis. En un momento de impulso, una pantalla que se
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
                return json.loads(response.read().decode("utf-8"))
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
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TelegramError(f"sendDocument HTTP {exc.code}: {detail[:400]}") from exc

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
