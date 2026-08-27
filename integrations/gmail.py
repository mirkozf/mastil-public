"""Cliente del puente de Gmail (Google Apps Script).

Consulta bajo demanda. No es un monitor: Mástil nunca avisa que llegó un correo,
porque una notificación de correo no solicitada es exactamente el tipo de
interrupción que el resto del sistema intenta evitar.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any


class GmailBridge:
    def __init__(self, webapp_url: str, token: str, timeout: int = 30):
        self.webapp_url = webapp_url
        self.token = token
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.webapp_url and self.token)

    def call(self, action: str, **payload: Any) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("El puente de Gmail no está configurado.")

        body = dict(payload)
        body["action"] = action
        body["token"] = self.token

        request = urllib.request.Request(
            self.webapp_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        raw = urllib.request.urlopen(request, timeout=self.timeout).read().decode("utf-8")
        data = json.loads(raw)
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "bridge_error"))
        return data

    def count_unread(self) -> int:
        return int(self.call("count_unread").get("count", 0))

    def list_unread(self, limit: int = 10) -> list[dict[str, Any]]:
        return self.call("list_unread", limit=limit).get("items", []) or []

    def get_content(self, message_id: str, max_chars: int = 60000) -> dict[str, Any]:
        return self.call("get_content", id=message_id, max_chars=max_chars)
