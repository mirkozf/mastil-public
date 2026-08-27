"""Evaluación de evidencia fotográfica con Gemini.

Este módulo opina sobre *imágenes*, nunca sobre tiempo. La decisión de cuándo
empieza un bloque, cuándo se insiste y cuándo se cierra es de `core/scheduler.py`
y de la máquina de estados de Vigía. Acá sólo se responde una pregunta acotada:
¿esta foto muestra lo que la etapa pedía?

El contrato de salida es siempre el mismo diccionario, pase lo que pase:

    {"decision": "APPROVED"|"REJECTED"|"TECHNICAL_ERROR",
     "approved": bool, "confidence": float, "reason": str}
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


PROMPT_SINGLE = """
Eres Vigía de Mástil. Valida una foto de una sesión doméstica tangible fuera del computador.

Actividad: {title}
Tipo: {activity_type}
Etapa: {stage}
Requisito: {requirement}

Reglas:
- No exijas reloj.
- Aprueba solo si la imagen cumple el requisito de esta etapa.
- Para cocina inicial, busca ingredientes, preparación inicial o utensilios listos.
- Para orden/limpieza inicial, busca el escenario actual antes de intervenir.
- Responde SOLO JSON válido.

Formato:
{{
  "decision": "APPROVED" o "REJECTED",
  "approved": true/false,
  "confidence": 0.0,
  "reason": "motivo breve"
}}
"""


PROMPT_PAIR = """
Eres Vigía de Mástil. Compara dos fotos de una sesión doméstica tangible.

Actividad: {title}
Tipo: {activity_type}

Foto 1: inicio / antes.
Foto 2: final / después.

Reglas por tipo:
- cocina: la foto inicial debe mostrar ingredientes/preparación inicial y la final debe mostrar comida lista, plato servido, olla/sartén terminada o preparación claramente avanzada. No evalúes orden de cocina; evalúa transformación hacia comida.
- cambio_visible: compara el mismo escenario o uno equivalente y aprueba si hay mejora visible de orden/limpieza.
- acumulacion: aprueba si la acumulación bajó de forma visible: menos loza, ropa ordenada, basura fuera o zona despejada.
- mantenimiento: aprueba si hay evidencia razonable de avance físico.

No exijas perfección. Exige progreso real visible.
Responde SOLO JSON válido.

Formato:
{{
  "decision": "APPROVED" o "REJECTED",
  "approved": true/false,
  "progress_visible": true/false,
  "confidence": 0.0,
  "reason": "motivo breve"
}}
"""


def _extract_json(text: str) -> dict[str, Any]:
    """Los modelos suelen envolver el JSON en ```json. Sacarlo sin drama."""
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        text = text[start:end + 1]
    return json.loads(text)


def _error(reason: str, activity_type: str | None) -> dict[str, Any]:
    return {
        "decision": "TECHNICAL_ERROR",
        "approved": False,
        "confidence": 0.0,
        "reason": reason,
        "category": activity_type,
    }


class Vision:
    def __init__(self, api_key: str, model: str = "gemini-3.5-flash", timeout: int = 45):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    # ---------------------------------------------------------------- API

    def analyze_single(self, path: Path, context: dict[str, Any]) -> dict[str, Any]:
        prompt = PROMPT_SINGLE.format(
            title=context.get("title"),
            activity_type=context.get("activity_type"),
            stage=context.get("stage"),
            requirement=context.get("requirement"),
        )
        return self._call(prompt, [path], context)

    def analyze_pair(self, start_path: Path, end_path: Path,
                     context: dict[str, Any]) -> dict[str, Any]:
        prompt = PROMPT_PAIR.format(
            title=context.get("title"),
            activity_type=context.get("activity_type"),
        )
        return self._call(prompt, [start_path, end_path], context)

    def planificar(self, path: Path | None, prompt: str,
                   context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Estado actual + objetivo + estrategia -> siguiente bloque.

        Reusa `_call` entero: mismo endpoint, misma extracción de JSON y el
        mismo `TECHNICAL_ERROR` cuando algo falla. Lo único distinto es el
        prompt, porque la pregunta es otra — acá no se valida evidencia, se
        decide qué hacer ahora. El texto lo arma quien llama, para no meter
        `messages` dentro de una integración.
        """
        # Sin `path` la llamada va sin imagen: avanzar por la estrategia ya
        # conocida no necesita volver a mirar.
        return self._call(prompt, [path] if path else [], context or {})

    def evaluar_texto(self, prompt: str) -> dict[str, Any]:
        """Una consulta sin imágenes, que devuelve texto libre.

        No pasa por `_call` a propósito: aquél existe para juzgar evidencia y
        devuelve siempre el mismo diccionario con `decision`/`approved`, además
        de exigir JSON de vuelta. Acá lo que se quiere es una recomendación en
        prosa, y tocar `_call` para acomodar los dos casos pondría en riesgo a
        Vigía, que es lo único que hoy depende de él.

        Contrato: `{"ok": bool, "texto": str, "error": str}`.
        """
        if not self.enabled:
            return {"ok": False, "texto": "", "error": "Falta MASTIL_GEMINI_API_KEY"}

        body = json.dumps(
            {"contents": [{"parts": [{"text": prompt}]}]}
        ).encode("utf-8")
        request = urllib.request.Request(
            ENDPOINT.format(model=self.model, key=self.api_key),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            raw = urllib.request.urlopen(request, timeout=self.timeout).read().decode("utf-8")
            texto = json.loads(raw)["candidates"][0]["content"]["parts"][0]["text"]
            texto = texto.strip()
            if not texto:
                return {"ok": False, "texto": "", "error": "respuesta vacía"}
            return {"ok": True, "texto": texto, "error": ""}
        except urllib.error.HTTPError as exc:
            detalle = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "texto": "", "error": f"HTTP {exc.code}: {detalle[:300]}"}
        except Exception as exc:
            return {"ok": False, "texto": "", "error": str(exc)}

    # ------------------------------------------------------------ interno

    def _call(self, prompt: str, image_paths: list[Path],
              context: dict[str, Any]) -> dict[str, Any]:
        activity_type = context.get("activity_type")

        if not self.enabled:
            return _error("Falta MASTIL_GEMINI_API_KEY", activity_type)

        parts: list[dict[str, Any]] = [{"text": prompt}]
        for path in image_paths:
            path = Path(path)
            if not path.exists():
                return _error(f"No encontré la imagen {path.name}", activity_type)
            mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
            parts.append({
                "inline_data": {
                    "mime_type": mime,
                    "data": base64.b64encode(path.read_bytes()).decode("utf-8"),
                }
            })

        body = json.dumps({"contents": [{"parts": parts}]}).encode("utf-8")
        url = ENDPOINT.format(model=self.model, key=self.api_key)
        request = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            raw = urllib.request.urlopen(request, timeout=self.timeout).read().decode("utf-8")
            payload = json.loads(raw)
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            result = _extract_json(text)
            result.setdefault("category", activity_type)
            result.setdefault("reason", "")
            result.setdefault("approved", result.get("decision") == "APPROVED")
            return result
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return _error(f"Gemini HTTP {exc.code}: {detail[:700]}", activity_type)
        except Exception as exc:
            return _error(f"Gemini error: {exc}", activity_type)


def approved(result: dict[str, Any] | None) -> bool:
    """¿La evidencia pasa?

    Sin resultado se aprueba: eso ocurre cuando Vision está deshabilitada a
    propósito y no queremos dejar a nadie encerrado sin poder cerrar su bloque.

    OJO: un `TECHNICAL_ERROR` sí reprueba, igual que en el legacy. Si Gemini
    está caído, Vigía va a seguir pidiendo otra foto. Es fiel al comportamiento
    actual, pero es un punto que conviene revisar con calma.
    """
    if result is None:
        return True
    return bool(
        result.get("approved")
        or result.get("decision") == "APPROVED"
        or result.get("progress_visible") is True
    )


def note(result: dict[str, Any] | None) -> str:
    """Comentario humano y breve del modelo, si lo hay."""
    if not result:
        return ""
    text = result.get("comment") or result.get("motivo") or result.get("reason")
    return f"\n\n{text}" if text else ""
