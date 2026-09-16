"""Reporte de Intervalos a Excel. Sin sleeps, sin bot real, sin produccion."""

import os, sys, dataclasses, zipfile, re
from pathlib import Path
from datetime import datetime, timedelta, timezone, date

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.update(MASTIL_TELEGRAM_BOT_TOKEN="0:t", MASTIL_OWNER_CHAT_ID="999",
                  MASTIL_ICAL_URL="https://x.invalid/a.ics")

import config as cm
import messages
from database import Database
from core.router import Router
from modules.panel import PanelModule
from modules import reporte
from modules.intervalos import formato_duracion

YO = "999"
TMP = Path(os.environ["TEMP"]) / "reporte_test.db"
SALIDA = Path(os.environ["TEMP"]) / "reporte_salida"
SALIDA.mkdir(exist_ok=True)
cfg = dataclasses.replace(cm.load(), owner_chat_id=YO, db_path=TMP)

FALLAS = 0
def ok(c, t):
    global FALLAS
    print(f"  {'ok  ' if c else 'MAL '} {t}")
    if not c: FALLAS += 1

db = None
def limpiar():
    global db
    if db: db.close()
    TMP.unlink(missing_ok=True)
    db = Database(cfg.db_path, cfg.schema_path); db.migrate()

def marca(dia: str, hora: str, minuto: int = 0, seg: int = 0):
    """Inserta una marca. `dia` local, hora UTC explicita para no depender de tz."""
    t = datetime.fromisoformat(f"{dia}T{hora}:00+00:00")
    db.execute(
        "INSERT INTO interval_marks(user_id, marked_at_utc, local_day, request_id) "
        "VALUES (?,?,?,?)",
        (YO, t.isoformat(), dia, f"r-{dia}-{hora}-{os.urandom(4).hex()}"),
    )

def hoja(path):
    with zipfile.ZipFile(path) as zf:
        return zf.read("xl/worksheets/sheet1.xml").decode("utf-8"), zf.namelist()

def celdas(xml):
    """{'A1': 'texto'} a partir del sheet XML."""
    out = {}
    for m in re.finditer(r'<c r="([A-Z]+\d+)"[^>]*>(?:<is><t[^>]*>(.*?)</t></is>)?</c>', xml):
        out[m.group(1)] = m.group(2) or ""
    return out


print("=== 1. rango de un solo dia ===")
limpiar()
marca("2026-08-11", "10:00"); marca("2026-08-11", "11:52"); marca("2026-08-11", "13:19")
f = SALIDA / "uno.xlsx"
hay = reporte.generar(db, YO, date(2026, 8, 11), date(2026, 8, 11), f)
ok(hay is True, "genera")
xml, nombres = hoja(f)
c = celdas(xml)
ok(c.get("A4") == "📅 11/08/2026", f"cabecera del dia en A4 ({c.get('A4')})")
ok((c.get("A5"), c.get("B5"), c.get("C5")) == ("#", "TRAMO", "TOTAL"), "encabezados")
ok(c.get("B6") == "Inicio", f"primer tramo = Inicio ({c.get('B6')})")
ok(c.get("C6") == "00m 00s", f"primer total = 00m 00s ({c.get('C6')})")
ok(c.get("B7") == "1h 52m 00s", f"tramo 2 ({c.get('B7')})")
ok(c.get("C8") == "3h 19m 00s", f"total 3 ({c.get('C8')})")

print("\n=== 2. rango de 3 dias, bloques horizontales ===")
limpiar()
for d in ("2026-08-11", "2026-08-12", "2026-08-13"):
    marca(d, "10:00"); marca(d, "11:00")
f = SALIDA / "tres.xlsx"
reporte.generar(db, YO, date(2026, 8, 11), date(2026, 8, 13), f)
xml, nombres = hoja(f)
c = celdas(xml)
ok(c.get("A4") == "📅 11/08/2026", "dia 1 en A")
ok(c.get("E4") == "📅 12/08/2026", f"dia 2 en E ({c.get('E4')})")
ok(c.get("I4") == "📅 13/08/2026", f"dia 3 en I ({c.get('I4')})")
ok("</sheetData>" in xml and xml.count("<sheetData>") == 1, "una sola hoja de datos")

print("\n=== 9. NO hay una hoja por dia ===")
hojas = [n for n in nombres if n.startswith("xl/worksheets/")]
ok(hojas == ["xl/worksheets/sheet1.xml"], f"una sola worksheet: {hojas}")
with zipfile.ZipFile(f) as zf:
    wb = zf.read("xl/workbook.xml").decode("utf-8")
ok(wb.count("<sheet ") == 1, "el workbook declara una sola hoja")

print("\n=== 10. el cuarto dia abre un bloque nuevo a la derecha ===")
limpiar()
for i in range(7):
    d = (date(2026, 8, 11) + timedelta(days=i)).strftime("%Y-%m-%d")
    marca(d, "10:00"); marca(d, "12:30")
f = SALIDA / "siete.xlsx"
reporte.generar(db, YO, date(2026, 8, 11), date(2026, 8, 17), f)
xml, _ = hoja(f)
c = celdas(xml)
fechas = {v: k for k, v in c.items() if v.startswith("📅")}
ok(len(fechas) == 7, f"siete cabeceras de dia ({len(fechas)})")
ok(fechas.get("📅 11/08/2026") == "A4", "dia 1 -> A")
ok(fechas.get("📅 13/08/2026") == "I4", "dia 3 -> I (fin del bloque 1)")
ok(fechas.get("📅 14/08/2026") == "O4", f"dia 4 -> O, con el hueco de bloque ({fechas.get('📅 14/08/2026')})")
ok(fechas.get("📅 17/08/2026") == "AC4", f"dia 7 -> AC ({fechas.get('📅 17/08/2026')})")
ok(all(v.endswith("4") for v in fechas.values()), "todas las cabeceras en la misma fila: horizontal")

print("\n=== 3/4. rango de 7 dias con dias sin datos ===")
limpiar()
marca("2026-08-11", "10:00"); marca("2026-08-11", "11:00")
marca("2026-08-14", "09:00"); marca("2026-08-14", "10:30")
f = SALIDA / "huecos.xlsx"
reporte.generar(db, YO, date(2026, 8, 11), date(2026, 8, 17), f)
xml, _ = hoja(f)
c = celdas(xml)
ok(c.get("A5") == "#", "el dia con datos tiene su tabla")
ok(c.get("E5") == "Sin datos", f"12/08 sin datos ({c.get('E5')})")
ok(c.get("I5") == "Sin datos", "13/08 sin datos")
ok(c.get("O5") == "#", "14/08 vuelve a tener tabla")
sin = [v for v in c.values() if v == "Sin datos"]
ok(len(sin) == 5, f"cinco dias vacios ({len(sin)})")
ok(not any(v == "Inicio" for k, v in c.items() if k.startswith("E")),
   "no inventa filas en los dias vacios")

print("\n=== 5. rango completamente sin datos ===")
f = SALIDA / "vacio.xlsx"
f.unlink(missing_ok=True)
hay = reporte.generar(db, YO, date(2026, 9, 1), date(2026, 9, 5), f)
ok(hay is False, "devuelve False")
ok(not f.exists(), "y NO escribe un Excel vacio")

print("\n=== 7. los tramos son EXACTAMENTE los de Intervalos ===")
limpiar()
horas = ["10:00", "11:52", "13:19", "15:36", "17:05", "18:40", "20:19"]
for h in horas: marca("2026-08-11", h)
f = SALIDA / "exacto.xlsx"
reporte.generar(db, YO, date(2026, 8, 11), date(2026, 8, 11), f)
c = celdas(hoja(f)[0])

# Lo mismo, calculado con el modulo real de Intervalos.
from modules.intervalos import IntervalosModule
mods = IntervalosModule(cfg, db)
marcas_db = db.query("SELECT * FROM interval_marks ORDER BY marked_at_utc")
tiempos = [datetime.fromisoformat(m["marked_at_utc"]) for m in marcas_db]
esperado_tramo = ["Inicio"] + [
    formato_duracion((tiempos[i] - tiempos[i - 1]).total_seconds())
    for i in range(1, len(tiempos))
]
esperado_total = [formato_duracion((t - tiempos[0]).total_seconds()) for t in tiempos]
salida_tramo = [c.get(f"B{6 + i}") for i in range(len(horas))]
salida_total = [c.get(f"C{6 + i}") for i in range(len(horas))]
ok(salida_tramo == esperado_tramo, f"tramos identicos\n       excel: {salida_tramo}\n       modulo: {esperado_tramo}")
ok(salida_total == esperado_total, "totales identicos")

print("\n=== 8. TOTAL DEL DIA coincide ===")
total_fila = [v for v in c.values() if v.startswith("TOTAL DEL DÍA")]
ok(len(total_fila) == 1, f"un solo total del dia ({len(total_fila)})")
ok(total_fila[0] == f"TOTAL DEL DÍA: {esperado_total[-1]}",
   f"{total_fila[0]} vs esperado {esperado_total[-1]}")

print("\n=== 11. el .xlsx es valido y legible ===")
with zipfile.ZipFile(f) as zf:
    ok(zf.testzip() is None, "el ZIP no esta corrupto")
    faltan = {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
              "xl/_rels/workbook.xml.rels", "xl/styles.xml",
              "xl/worksheets/sheet1.xml"} - set(zf.namelist())
    ok(not faltan, f"estan todas las partes obligatorias (faltan: {faltan})")
import xml.dom.minidom as md
for parte in ("xl/worksheets/sheet1.xml", "xl/workbook.xml", "xl/styles.xml"):
    with zipfile.ZipFile(f) as zf:
        try:
            md.parseString(zf.read(parte)); bien = True
        except Exception as e:
            bien = False; print("     ", parte, e)
    ok(bien, f"{parte} es XML valido")
ok("<cols>" in hoja(f)[0] and 'width="14"' in hoja(f)[0], "tiene anchos de columna")

print("\n=== duraciones en formato humano, no segundos ===")
ok(not any(re.fullmatch(r"\d+(\.\d+)?", v or "") for k, v in c.items() if k.startswith(("B", "C")) and k != "B5"),
   "ninguna duracion quedo como numero crudo")

print("\n=== 6/12/13/14. flujo por Panel y Router ===")
limpiar()
for d in ("2026-08-11", "2026-08-12"):
    marca(d, "10:00"); marca(d, "11:30")

class TG:
    def __init__(self): self.docs = []; self.answered = []
    def answer_callback(self, cid, text="", show_alert=False): self.answered.append(cid)
    def send_message(self, *a, **k): return {"ok": True}
    def send_document(self, chat_id, path, caption="", parse_mode=None):
        self.docs.append((str(chat_id), Path(path).name, Path(path).read_bytes(), caption))
        return {"ok": True}

class Nada:
    # Desde `ff1f2cb` el router lo llama en cada mensaje.
    def abandon_contexto(self, *a, **k): pass
    def handle_command(self, *a, **k): return False
    def stop(self, *a, **k): pass
    def restore_calendar(self, *a, **k): pass
    def matches(self, *a, **k): return False
    def handle_message(self, *a, **k): return False
    def handle_text(self, *a, **k): return False
    def handle_photo(self, *a, **k): return False
    def handle(self, *a, **k): return True

def montar():
    db.execute("DELETE FROM outbox")
    panel = PanelModule(cfg, db)
    mods = {"panel": panel, "intervalos": Nada(), "timer": Nada(),
            "system": Nada(), "pomodoro": Nada(), "gmail": Nada(), "guardian": Nada(),
            "calendar": Nada(), "lite": Nada(), "vigia": Nada()}
    tg = TG(); r = Router(cfg, db, tg, mods); panel.attach(r)
    return r, panel, tg

def out():
    f = db.query("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id")
    db.execute("UPDATE outbox SET sent_at='x' WHERE sent_at IS NULL")
    return f

def cbq(data, mid=7, chat=YO):
    return {"callback_query": {"id": "c1", "data": data, "from": {"id": chat},
                               "message": {"message_id": mid, "chat": {"id": chat}}}}
def msg(t, mid=1, chat=YO):
    return {"message": {"message_id": mid, "chat": {"id": chat}, "from": {"id": chat}, "text": t}}

def datos_de(fila):
    import json
    t = json.loads(fila["buttons"]) if fila and fila["buttons"] else []
    return [b[1] for g in t for b in g]

r, panel, tg = montar()
r.process(cbq("panel:intervalos"))
f = out()[-1]
ok("panel:int:reporte" in datos_de(f), f"REPORTE esta en el menu ({datos_de(f)})")
ok(datos_de(f) == ["/marca", "/marca_contexto", "/tiempo",
                   "panel:int:reset", "panel:int:reporte", "panel:home"],
   "y no se agrego ningun otro boton")

r.process(cbq("panel:int:reporte"))
f = out()[-1]
ok(f["text"] == messages.REPORTE_TITULO and f["kind"] == "edit", "abre el reporte editando")
ok(datos_de(f) == ["panel:rep:desde", "panel:rep:hasta", "panel:rep:exportar", "panel:home"],
   f"tres opciones + PANEL ({datos_de(f)})")

r.process(cbq("panel:rep:exportar"))
ok(messages.REPORTE_FALTA_RANGO in (out()[-1]["text"] or ""), "sin rango avisa")

r.process(cbq("panel:rep:desde")); out()
r.process(msg("12/08/2026", 2)); out()
r.process(cbq("panel:rep:hasta")); out()
r.process(msg("11/08/2026", 3)); out()
r.process(cbq("panel:rep:exportar"))
ok(messages.REPORTE_RANGO_INVERTIDO in (out()[-1]["text"] or ""), "desde > hasta da error")
ok(not tg.docs, "y no manda ningun archivo")

r.process(cbq("panel:rep:desde")); out()
r.process(msg("11/08/2026", 4)); out()
r.process(cbq("panel:rep:hasta")); out()
r.process(msg("12/08/2026", 5))
f = out()[-1]
import json
etiquetas = [b[0] for g in json.loads(f["buttons"]) for b in g]
ok(any("11/08/2026" in e for e in etiquetas) and any("12/08/2026" in e for e in etiquetas),
   f"las fechas elegidas se ven en los botones: {etiquetas[:2]}")

r.process(cbq("panel:rep:exportar"))
ok(len(tg.docs) == 1, f"UN solo documento enviado ({len(tg.docs)})")
chat, nombre, contenido, caption = tg.docs[0]
ok(chat == YO, "a tu chat")
ok(nombre == "intervalos_2026-08-11_a_2026-08-12.xlsx", f"nombre correcto: {nombre}")
ok("Reporte de Intervalos generado" in caption, "con el texto de confirmacion")
ok("11/08/2026 → 12/08/2026" in caption, "y el periodo")
ok(contenido[:2] == b"PK", "el contenido es un ZIP (xlsx)")
ok(len(out()) <= 1, "no manda un mensaje por dia")

print("\n=== fecha mal escrita ===")
r.process(cbq("panel:rep:desde")); out()
r.process(msg("no-es-fecha", 6))
ok(messages.REPORTE_FECHA_INVALIDA in (out()[-1]["text"] or ""), "avisa el formato")

print("\n=== 13. un comando cancela el formulario y se ejecuta ===")
r.process(cbq("panel:rep:desde")); out()
r.process(msg("/panel", 7))
ok(any((x["text"] or "") == "⚓ MÁSTIL" for x in out()), "/panel se ejecuta normal")
ok(not panel._pendientes and not panel._reportes, "y descarta formulario y rango")

print("\n=== 14/15. Panel e Intervalos intactos ===")
from modules.intervalos import MOMENTOS_AVISO, ESPERA_MINUTOS, HORAS_CIERRE, MAX_FILAS
ok(MOMENTOS_AVISO == (0, 150, 180, 420), "constantes de Intervalos")
ok(isinstance(ESPERA_MINUTOS, int) and ESPERA_MINUTOS > 0,
   f"ESPERA_MINUTOS lo fija el usuario a mano: {ESPERA_MINUTOS} min")
ok(HORAS_CIERRE == 4 and MAX_FILAS == 10, "y las otras dos")
ok(messages.INTERVALOS_AVISO == "⏱ Intervalo cumplido.", "su aviso")
ok(messages.INTERVALOS_TITULO == "📊 MARCAS DEL CICLO", "su titulo")

r, panel, tg = montar()
r.process(msg("/panel", 8))
ok(any((x["text"] or "") == "⚓ MÁSTIL" for x in out()), "/panel sigue andando")
r.process(cbq("panel:timer"))
# La pantalla del timer ya no es un titulo fijo: se arma segun lo que corra.
ok((out()[-1]["text"] or "").startswith("⏲️ TIMER"), "el resto del Panel sigue andando")

db.close(); TMP.unlink(missing_ok=True)
for x in SALIDA.glob("*.xlsx"): x.unlink(missing_ok=True)
print("\n" + "=" * 52)
print("FALLAS:", FALLAS)
sys.exit(1 if FALLAS else 0)
