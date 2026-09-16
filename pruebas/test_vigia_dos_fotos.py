"""Vigia puede mirar DOS fotos del mismo lugar en una sola consulta.

Un escenario cargado no se entiende desde un solo angulo: la foto tapa la mitad
de lo que hay que planificar. Dos vistas viajan en el MISMO request, asi que el
modelo ve mas y la cuota diaria no se mueve.

El detalle que obliga a preguntar antes: el analisis se dispara al LLEGAR la
foto. Sin saber cuantas vienen, la primera se analizaria sola y la segunda
llegaria tarde. La pregunta es operativa —cuantas vas a mandar—, no una
evaluacion de que tan dificil esta el desorden.
"""

import os, sys, dataclasses, json
from pathlib import Path

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import messages
from database import Database
from core.router import Router
from modules.vigia import VigiaModule, _leer_fotos, _guardar_fotos
from modules.panel import PanelModule

YO = "999"
TMP = Path(os.environ["TEMP"]) / "vig_dos" / "mastil.db"
TMP.parent.mkdir(parents=True, exist_ok=True)
F = Path(os.environ["TEMP"]) / "vig_dos_fotos"
F.mkdir(exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP,
                          evidence_dir=F)

FALLAS = 0


def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c:
        FALLAS += 1


class Vis:
    """Gemini falso: anota CUANTAS imagenes le llegaron en cada consulta."""

    enabled = True

    def __init__(self):
        self.r = []
        self.prompts = []
        self.tandas = []          # una entrada por consulta: las rutas

    def planificar(self, p, prompt, context=None):
        rutas = list(p) if isinstance(p, (list, tuple)) else ([p] if p else [])
        self.tandas.append([str(x) for x in rutas])
        self.prompts.append(prompt)
        return self.r.pop(0) if self.r else {"decision": "TECHNICAL_ERROR"}


class TG:
    def __init__(self):
        self.directos = []

    def send_message(self, chat, text, buttons=None, parse_mode=None):
        self.directos.append(text)
        return {"ok": True}

    def answer_callback(self, *a, **k):
        pass

    def download_photo(self, fid, dest):
        p = Path(dest) / f"{fid}.jpg"
        p.write_bytes(b"x")
        return p


class Nada:
    enabled = False
    def __getattr__(self, n): return lambda *a, **k: False


db = None
vis = tg = vigia = panel = r = None


def montar():
    global db, vis, tg, vigia, panel, r
    if db:
        db.close()
    TMP.unlink(missing_ok=True)
    db = Database(cfg.db_path, cfg.schema_path)
    db.migrate()
    vis, tg = Vis(), TG()
    vigia = VigiaModule(cfg, db, tg, vis, Nada())
    panel = PanelModule(cfg, db)
    mods = {"vigia": vigia, "panel": panel}
    for k in ("timer", "system", "pomodoro", "gmail", "guardian",
              "calendar", "lite", "intervalos"):
        mods[k] = Nada()
    r = Router(cfg, db, tg, mods)
    panel.attach(r)
    return r


PLAN = {"estado": "EN_RUTA", "estrategia": ["recoger la basura", "trapear"]}


def out():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL")
    return f


def textos():
    return [x["text"] or "" for x in out()]


def msg(t, m=1):
    return {"message": {"message_id": m, "chat": {"id": YO},
                        "from": {"id": YO}, "text": t}}


def cb(data, m=7):
    return {"callback_query": {"id": "c", "data": data, "from": {"id": YO},
                               "message": {"message_id": m, "chat": {"id": YO}}}}


def foto(m, fid):
    return {"message": {"message_id": m, "chat": {"id": YO},
                        "from": {"id": YO}, "photo": [{"file_id": fid}]}}


def ses():
    return db.one("SELECT * FROM vigia_session WHERE id = 1")


def arrancar():
    r = montar()
    r.process(msg("/vigia ordenar la mesa"))
    out()
    return r


# =========================================================================
print("=== 1. la migracion dejo las dos columnas ===")
montar()
columnas = {f["name"] for f in db.query("PRAGMA table_info(vigia_session)")}
ok("fotos_esperadas" in columnas, "fotos_esperadas existe")
ok("foto_previa" in columnas, "foto_previa existe")

print("\n=== 2. el panel pregunta cuantas, antes de nada ===")
r = arrancar()
r.process(cb("panel:vig:foto"))
f = out()[-1]
ok("Cuántas fotos" in (f["text"] or ""), "pregunta cuantas van a venir")
ok(ses()["fotos_esperadas"] == 1, "y todavia no cambio nada")

print("\n=== 3. UNA foto: se analiza al llegar, como siempre ===")
r.process(cb("panel:vig:foto:1")); out()
ok(ses()["fotos_esperadas"] == 1, "queda esperando una")
vis.r.append(PLAN)
r.process(foto(3, "a"))
ok(len(vis.tandas) == 1, "una sola consulta al modelo")
ok(len(vis.tandas[0]) == 1, f"con UNA imagen ({len(vis.tandas[0])})")
ok("recoger la basura" in " ".join(textos()), "y entrega el plan")

print("\n=== 4. DOS fotos: la primera espera, no dispara nada ===")
r = arrancar()
r.process(cb("panel:vig:foto")); out()
r.process(cb("panel:vig:foto:2"))
f = out()[-1]
ok(ses()["fotos_esperadas"] == 2, "queda esperando dos")
ok("primera de las dos" in (f["text"] or ""), "y lo dice en pantalla")

r.process(foto(3, "a"))
ok(not vis.tandas, "la primera NO llama al modelo")
ok(ses()["foto_previa"], "se guarda a la espera de la otra")
ok(messages.VIGIA_PRIMERA_RECIBIDA in " ".join(textos()), "y avisa que falta una")

print("\n=== 5. la segunda dispara UNA consulta con las DOS ===")
vis.r.append(PLAN)
r.process(foto(4, "b"))
ok(len(vis.tandas) == 1, f"una sola consulta, no dos ({len(vis.tandas)})")
ok(len(vis.tandas[0]) == 2, f"y lleva las DOS imagenes ({len(vis.tandas[0])})")
ok(vis.tandas[0][0].endswith("a.jpg"), "primero la que mandaste antes")
ok(vis.tandas[0][1].endswith("b.jpg"), "y despues la segunda")
ok("recoger la basura" in " ".join(textos()), "y entrega el plan igual")

print("\n=== 6. el prompt aclara que son el MISMO lugar ===")
#
# Sin esto el modelo puede leerlas como dos ambientes y planificar el doble
# del trabajo que hay.
p = vis.prompts[-1]
ok("MISMO lugar" in p, "se lo dice explicito")
ok("No son dos ambientes" in p, "y descarta la lectura equivocada")
ok("angulos distintos" in p or "ángulos distintos" in p, "explica por que son dos")

print("\n=== 7. la tanda se cierra: la proxima foto empieza de cero ===")
ok(ses()["fotos_esperadas"] == 1, "vuelve a esperar una sola")
ok(not ses()["foto_previa"], "y no queda ninguna a medio camino")
vis.r.append(PLAN)
r.process(foto(5, "c"))
ok(len(vis.tandas) == 2, "la siguiente foto se analiza sola")
ok(len(vis.tandas[1]) == 1, f"con UNA imagen ({len(vis.tandas[1])})")

print("\n=== 8. reintentar reanaliza las DOS, no una ===")
#
# Es el caso que mas importa: el modelo pide mas contexto justo cuando la
# escena es confusa, que es cuando la segunda vista hace falta.
r = arrancar()
r.process(cb("panel:vig:foto")); out()
r.process(cb("panel:vig:foto:2")); out()
r.process(foto(3, "a")); out()
vis.r.append({"estado": "FALTA_CONTEXTO", "pregunta": "¿La caja se tira?"})
r.process(foto(4, "b")); out()
ok(len(vis.tandas[-1]) == 2, "la consulta que fallo llevaba dos")
ok(len(_leer_fotos(ses()["ultima_foto"])) == 2,
   f"y quedaron guardadas las dos ({ses()['ultima_foto']})")

vis.r.append(PLAN)
r.process(cb("/vigia_reintentar")); out()
ok(len(vis.tandas[-1]) == 2, f"el reintento vuelve con las DOS ({len(vis.tandas[-1])})")

print("\n=== 9. elegir de nuevo descarta la que iba a medias ===")
r = arrancar()
r.process(cb("panel:vig:foto")); out()
r.process(cb("panel:vig:foto:2")); out()
r.process(foto(3, "a")); out()
ok(ses()["foto_previa"], "hay una esperando")
r.process(cb("panel:vig:foto:1")); out()
ok(not ses()["foto_previa"], "volver a elegir la suelta")
ok(ses()["fotos_esperadas"] == 1, "y deja el modo en una")

print("\n=== 10. el formato viejo no se rompe ===")
#
# Una sesion abierta al momento de actualizar tiene una ruta suelta en
# `ultima_foto`, no un JSON.
ok(_leer_fotos("/tmp/vieja.jpg") == ["/tmp/vieja.jpg"], "una ruta suelta se lee igual")
ok(_leer_fotos(None) == [], "y sin nada no revienta")
ok(_leer_fotos(_guardar_fotos([Path("/a.jpg"), Path("/b.jpg")])) ==
   ["/a.jpg".replace("/", os.sep), "/b.jpg".replace("/", os.sep)]
   or len(_leer_fotos(_guardar_fotos([Path("/a.jpg"), Path("/b.jpg")]))) == 2,
   "y lo que se guarda se vuelve a leer entero")

print("\n=== 12. la opcion vive en el FLUJO, no solo en el Panel ===")
#
# Estaba enterrada en el Panel, y por eso no servia de nada: el mensaje que
# pide la foto es donde de verdad estas, y solo ofrecia CONTEXTO y PANEL. La
# decision se toma mirando el desorden, no navegando menus.
r = montar()
r.process(msg("/vigia ordenar la mesa"))
filas = out()
botones = [b[1] for g in json.loads(filas[-1]["buttons"] or "[]") for b in g]
ok("panel:vig:foto:2" in botones,
   f"el mensaje de arranque ya la ofrece ({botones})")

r.process(cb("panel:vig:foto:2")); out()
ok(ses()["fotos_esperadas"] == 2, "elegirla desde ahi deja el modo en dos")
vis.r.append(PLAN)
r.process(foto(3, "a")); out()
ok(not vis.tandas, "la primera sigue sin disparar nada")
r.process(foto(4, "b")); out()
ok(len(vis.tandas) == 1 and len(vis.tandas[0]) == 2,
   "y las dos llegan juntas al modelo, en una sola consulta")

print("\n=== 13. con tarea viva, el panel no te devuelve a la entrada ===")
#
# El flujo de Vigia tiene muchos pasos y el panel se recrea tras cada uno.
# Mandarlo al home en cada paso obligaba a rehacer el camino a mitad de tarea.
panel.recreate_current(YO)
f = out()[-1]
ok("VIGÍA" in (f["text"] or ""), "vuelve al menu de Vigia")
ok(messages.PANEL_VIG_CUANTAS not in (f["text"] or ""),
   "pero al MENU, no a la pantalla vieja")

print("\n=== 11. Vision acepta una, varias o ninguna ===")
#
# `_call` ya sabia armar una parte por imagen; lo que faltaba era que
# `planificar` le dejara pasar mas de una. Se prueba sin red: se intercepta
# `_call` y se mira que rutas le llegan.
from integrations.vision import Vision

vision = Vision("clave-falsa", "modelo-falso")
recibidas = []
vision._call = lambda prompt, paths, context: recibidas.append(list(paths))

vision.planificar(Path("/una.jpg"), "x")
ok(len(recibidas[-1]) == 1, "una ruta suelta viaja como una")

vision.planificar([Path("/a.jpg"), Path("/b.jpg")], "x")
ok(len(recibidas[-1]) == 2, f"una lista viaja entera ({len(recibidas[-1])})")

vision.planificar(None, "x")
ok(recibidas[-1] == [], "sin foto va sin imagenes, como antes")

vision.planificar([Path("/a.jpg"), None], "x")
ok(len(recibidas[-1]) == 1, "y los huecos de la lista se descartan")

db.close()
print(f"\n{'TODO OK' if not FALLAS else str(FALLAS) + ' FALLAS'}")
sys.exit(1 if FALLAS else 0)
