"""Reusar la conexion con Telegram, sin los riesgos de compartirla.

Abrir el canal cuesta ~115 ms de saludo (TCP mas TLS) antes de mandar un byte
util. Reusarlo los ahorra en cada llamada menos la primera.

Los tres riesgos de compartir una conexion, y como se evitan:

  1. el long polling la ocuparia hasta un minuto  -> va por conexion suelta
  2. dos hilos se pisarian las respuestas         -> una conexion POR HILO
  3. el otro lado puede cerrarla mientras espera  -> se reintenta suelta

Sin red: el cliente HTTP y `urlopen` son dobles.
"""

import os, sys, json, threading

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import integrations.telegram as T
from integrations.telegram import Telegram, TelegramError

FALLAS = 0


def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c:
        FALLAS += 1


class Respuesta:
    def __init__(self, status=200, cuerpo=None):
        self.status = status
        self._cuerpo = json.dumps(cuerpo or {"ok": True}).encode("utf-8")

    def read(self):
        return self._cuerpo


class Conexion:
    """Cliente HTTP doble. Cuenta cuantas veces se abrio de verdad."""

    abiertas = 0
    viva = None

    def __init__(self, host, timeout=None, context=None):
        Conexion.abiertas += 1
        Conexion.viva = self
        self.host = host
        self.rutas = []
        self.cerrada = False
        self.romper = False
        self.status = 200
        self.hilo = threading.current_thread().name

    def request(self, metodo, ruta, body=None, headers=None):
        if self.romper:
            raise OSError("el otro lado cerro la conexion")
        self.rutas.append(ruta)

    def getresponse(self):
        return Respuesta(self.status,
                         {"ok": True, "result": [], "via": "reusada"})

    def close(self):
        self.cerrada = True


class Sueltas:
    """Doble de `urlopen`: la via de siempre, una conexion por llamada."""

    def __init__(self):
        self.llamadas = 0

    def __call__(self, request, timeout=None):
        self.llamadas += 1
        cuerpo = json.dumps({"ok": True, "result": [], "via": "suelta"})

        class Ctx:
            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False

            def read(self_):
                return cuerpo.encode("utf-8")

        return Ctx()


def montar():
    Conexion.abiertas = 0
    Conexion.viva = None
    T.http.client.HTTPSConnection = Conexion
    sueltas = Sueltas()
    T.urllib.request.urlopen = sueltas
    return Telegram("0:t"), sueltas


# =========================================================================
print("=== 1. la conexion se reusa entre llamadas ===")
tg, sueltas = montar()
for _ in range(5):
    tg.api("sendMessage", {"chat_id": "1", "text": "x"})
ok(Conexion.abiertas == 1, f"cinco llamadas, una sola apertura ({Conexion.abiertas})")
ok(len(Conexion.viva.rutas) == 5, "las cinco fueron por ahi")
ok(sueltas.llamadas == 0, "y ninguna abrio conexion suelta")

print("\n=== 2. el long polling NO usa la compartida ===")
#
# Es el riesgo principal: se queda colgado hasta un minuto esperando, y
# ocuparla dejaria cada boton esperando a que ese poll termine.
tg, sueltas = montar()
tg.get_updates(offset=0, timeout=25)
ok(Conexion.abiertas == 0, "el poll no toca la conexion compartida")
ok(sueltas.llamadas == 1, "va por la suya")

tg.api("sendMessage", {"chat_id": "1", "text": "x"})
ok(Conexion.abiertas == 1, "y los envios siguen usando la compartida")

print("\n=== 3. una conexion POR HILO ===")
#
# El worker de los acuses corre en otro hilo. Dos hilos sobre una misma
# conexion HTTP se pisan las respuestas entre si.
tg, sueltas = montar()
tg.api("sendMessage", {"chat_id": "1", "text": "principal"})
vistas = []


def desde_otro_hilo():
    tg.api("sendMessage", {"chat_id": "1", "text": "worker"})
    vistas.append(Conexion.viva.hilo)


h = threading.Thread(target=desde_otro_hilo, name="worker")
h.start()
h.join()
ok(Conexion.abiertas == 2, "cada hilo abrio la suya")
ok(vistas and vistas[0] == "worker", "y la del worker es del worker")

print("\n=== 4. si la conexion se cayo, el mensaje NO se pierde ===")
tg, sueltas = montar()
tg.api("sendMessage", {"chat_id": "1", "text": "primera"})
ok(Conexion.abiertas == 1, "hay una conexion viva")

Conexion.viva.romper = True
resultado = tg.api("sendMessage", {"chat_id": "1", "text": "segunda"})
ok(resultado.get("via") == "suelta", "se reintenta por la via de siempre")
ok(sueltas.llamadas == 1, "y llega igual")

resultado = tg.api("sendMessage", {"chat_id": "1", "text": "tercera"})
ok(Conexion.abiertas == 2, "la siguiente abre una conexion nueva")
ok(resultado.get("via") == "reusada", "y vuelve a reusarse")

print("\n=== 5. un rechazo de Telegram NO se reintenta ===")
#
# Un 400 es la peticion, no el canal: reintentarla seria mandar dos veces lo
# mismo. Duplicar un aviso de Guardian es una falla conductual, no tecnica.
tg, sueltas = montar()
tg.api("sendMessage", {"chat_id": "1", "text": "x"})
Conexion.viva.status = 400
try:
    tg.api("sendMessage", {"chat_id": "1", "text": "y"})
    ok(False, "deberia haber fallado")
except TelegramError as exc:
    ok("400" in str(exc), "avisa el rechazo")
ok(sueltas.llamadas == 0, "y NO lo reintenta por otra via")

print("\n=== 6. el contrato de siempre no cambio ===")
tg, sueltas = montar()
r = tg.api("getMe")
ok(isinstance(r, dict) and r.get("ok") is True, "devuelve el dict de siempre")
ok(Conexion.viva.rutas[0].startswith("/bot0:t/"),
   f"con la ruta del bot ({Conexion.viva.rutas[0]})")
ok(Conexion.viva.host == "api.telegram.org", "contra el host de Telegram")

print("\n=== 7. los envios de fotos siguen como estaban ===")
#
# No se tocaron: van por su propia conexion, con su timeout largo.
import inspect

fuente = inspect.getsource(Telegram.send_photo)
ok("urlopen" in fuente, "sendPhoto sigue usando urlopen")
ok("_api_reusando" not in fuente, "y no pasa por la conexion compartida")

print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
