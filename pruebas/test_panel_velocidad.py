"""El acuse de un botón nunca retrasa la respuesta visible del panel."""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(
    MASTIL_TELEGRAM_BOT_TOKEN="0:t",
    MASTIL_OWNER_CHAT_ID="999",
    MASTIL_ICAL_URL="https://x.invalid/a.ics",
)

from integrations.telegram import Telegram

FALLAS = 0


def ok(condicion, texto):
    global FALLAS
    print(f"  {'ok  ' if condicion else 'MAL '} {texto}")
    if not condicion:
        FALLAS += 1


class TelegramLento(Telegram):
    def __init__(self):
        super().__init__("0:t")
        self.llamadas = []
        self.termino = threading.Event()

    def api(self, method, payload=None):
        time.sleep(0.25)
        self.llamadas.append((method, dict(payload or {})))
        self.termino.set()
        return {"ok": True, "result": True}


print("=== el acuse no bloquea el panel ===")
telegram = TelegramLento()
inicio = time.monotonic()
telegram.answer_callback("callback-1", "Listo", show_alert=True)
demora = time.monotonic() - inicio

ok(demora < 0.10, f"answer_callback vuelve de inmediato ({demora:.3f}s)")
ok(telegram.termino.wait(1.0), "el acuse sí se envía en segundo plano")
ok(telegram.llamadas == [(
    "answerCallbackQuery",
    {
        "callback_query_id": "callback-1",
        "text": "Listo",
        "show_alert": "true",
    },
)], "conserva método y contenido exactos")

print("\n=== los acuses conservan su orden ===")
telegram = TelegramLento()
for numero in range(3):
    telegram.answer_callback(f"callback-{numero}")

limite = time.monotonic() + 2.0
while len(telegram.llamadas) < 3 and time.monotonic() < limite:
    time.sleep(0.02)

ok(
    [payload["callback_query_id"] for _, payload in telegram.llamadas]
    == ["callback-0", "callback-1", "callback-2"],
    "un único worker respeta el orden de pulsación",
)

print("\nFALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
