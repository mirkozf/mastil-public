"""Reporte de Intervalos a Excel.

Exportador de sólo lectura. No decide nada, no guarda nada y no define ninguna
métrica: lee `interval_marks` y escribe el mismo cuadro que ya ves en Telegram,
un bloque por día.

Dos cosas que sostienen que esto no sea una segunda versión de Intervalos:

- **El formato de duración lo importa, no lo copia.** `formato_duracion` sigue
  viviendo en `modules/intervalos.py`; acá sólo se llama. Si algún día cambia
  ahí, el Excel cambia solo.
- **La aritmética es la de `_tabla`**: tramo = marca − anterior, total = marca −
  primera del bloque. No hay promedios, rachas ni porcentajes, porque Intervalos
  tampoco los tiene.

El `.xlsx` se escribe a mano con `zipfile` y XML de la librería estándar. Un
xlsx es un ZIP con unos pocos XML adentro, y escribirlos es más barato que
meter una dependencia: es el mismo criterio por el que la imagen del código de
4 dígitos se dibuja con `zlib` en vez de con Pillow.
"""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

import messages
from modules.intervalos import formato_duracion

# Un día ocupa exactamente estas tres columnas.
COLUMNAS_DIA = 3

# Días por bloque horizontal. El grupo siguiente continúa hacia la derecha, no
# hacia abajo: el hueco más ancho entre grupos es lo que los hace distinguibles.
DIAS_POR_BLOQUE = 3

# Columnas en blanco entre día y día, y entre un grupo de tres y el siguiente.
SEPARACION = 1
SEPARACION_BLOQUE = 2

# Ancho de las tres columnas del día. TRAMO y TOTAL tienen que dar para
# "10h 19m 13s" sin que Excel muestre ###.
ANCHOS_DIA = (5, 14, 14)

FORMATOS_FECHA = ("%d/%m/%Y", "%d/%m/%y", "%d/%m")


def parse_fecha(texto: str, hoy: datetime | None = None):
    """`01/08/2026` o `01/08` (año en curso). None si no se entiende."""
    limpio = (texto or "").strip()
    for formato in FORMATOS_FECHA:
        try:
            fecha = datetime.strptime(limpio, formato).date()
        except ValueError:
            continue
        if formato == "%d/%m":
            fecha = fecha.replace(year=(hoy or datetime.now()).year)
        return fecha
    return None


# ------------------------------------------------------------------ datos

def marcas_por_dia(db, user_id: str, desde: str, hasta: str) -> dict[str, list]:
    """Marcas del rango, agrupadas por su día local.

    `local_day` se guarda en zona local justamente para esto; usarlo evita
    convertir zonas acá y que el Excel discrepe con lo que viviste como martes.
    """
    filas = db.query(
        """
        SELECT local_day, marked_at_utc FROM interval_marks
        WHERE user_id = ? AND local_day BETWEEN ? AND ?
        ORDER BY local_day ASC, marked_at_utc ASC, id ASC
        """,
        (str(user_id), desde, hasta),
    )
    dias: dict[str, list] = {}
    for fila in filas:
        dias.setdefault(fila["local_day"], []).append(
            datetime.fromisoformat(fila["marked_at_utc"])
        )
    return dias


def tabla_del_dia(marcas: list) -> tuple[list[tuple[str, str, str]], str]:
    """Las filas `# / TRAMO / TOTAL` y el total del día.

    Misma aritmética que `IntervalosModule._tabla`: el total es contra la
    primera marca del bloque, no una suma acumulada aparte.
    """
    if not marcas:
        return [], ""
    primera = marcas[0]
    filas = []
    for indice, momento in enumerate(marcas):
        tramo = (
            messages.INTERVALOS_INICIO if indice == 0
            else formato_duracion((momento - marcas[indice - 1]).total_seconds())
        )
        filas.append((
            str(indice + 1), tramo,
            formato_duracion((momento - primera).total_seconds()),
        ))
    return filas, formato_duracion((marcas[-1] - primera).total_seconds())


def _dias_del_rango(desde, hasta) -> list[str]:
    from datetime import timedelta
    dias, actual = [], desde
    while actual <= hasta:
        dias.append(actual.strftime("%Y-%m-%d"))
        actual += timedelta(days=1)
    return dias


# ------------------------------------------------------- escritura del xlsx

def _col(indice: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letras = ""
    indice += 1
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


class _Hoja:
    """Rejilla dispersa: (fila, columna) -> (texto, negrita)."""

    def __init__(self):
        self.celdas: dict[tuple[int, int], tuple[str, bool]] = {}
        self.anchos: dict[int, int] = {}
        self.ancho = 0

    def poner(self, fila: int, columna: int, texto, negrita: bool = False) -> None:
        self.celdas[(fila, columna)] = (str(texto), negrita)
        self.ancho = max(self.ancho, columna + 1)

    def ancho_de(self, columna: int, medida: int) -> None:
        """El ancho lo fija quien arma el layout: es el que sabe qué es cada
        columna. Deducirlo acá con un módulo se rompe al cambiar la separación."""
        self.anchos[columna] = max(self.anchos.get(columna, 0), medida)

    def xml(self) -> str:
        filas: dict[int, list] = {}
        for (fila, columna), valor in self.celdas.items():
            filas.setdefault(fila, []).append((columna, valor))

        partes = []
        for numero in sorted(filas):
            celdas = []
            for columna, (texto, negrita) in sorted(filas[numero]):
                estilo = ' s="1"' if negrita else ""
                celdas.append(
                    f'<c r="{_col(columna)}{numero + 1}" t="inlineStr"{estilo}>'
                    f"<is><t xml:space=\"preserve\">{escape(texto)}</t></is></c>"
                )
            partes.append(f'<row r="{numero + 1}">{"".join(celdas)}</row>')

        cols = []
        for columna in range(self.ancho):
            # Las que nadie declaró son los huecos de separación: angostas.
            ancho = self.anchos.get(columna, 3)
            cols.append(
                f'<col min="{columna + 1}" max="{columna + 1}" '
                f'width="{ancho}" customWidth="1"/>'
            )

        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<cols>{"".join(cols)}</cols>'
            f'<sheetData>{"".join(partes)}</sheetData>'
            "</worksheet>"
        )


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    "</Types>"
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    "</Relationships>"
)

_WORKBOOK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets><sheet name="Intervalos" sheetId="1" r:id="rId1"/></sheets>'
    "</workbook>"
)

_WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    "</Relationships>"
)

# Dos estilos y nada más: normal y negrita. El índice 1 es el que usa `poner`.
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border/></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
    "</styleSheet>"
)


def _escribir(destino, hoja: _Hoja) -> None:
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("xl/workbook.xml", _WORKBOOK)
        zf.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        zf.writestr("xl/styles.xml", _STYLES)
        zf.writestr("xl/worksheets/sheet1.xml", hoja.xml())


# ---------------------------------------------------------------- reporte

def nombre_archivo(desde, hasta) -> str:
    return f"intervalos_{desde:%Y-%m-%d}_a_{hasta:%Y-%m-%d}.xlsx"


def generar(db, user_id: str, desde, hasta, destino) -> bool:
    """Escribe el xlsx. False si no hay ninguna marca en el rango."""
    dias = marcas_por_dia(
        db, user_id, desde.strftime("%Y-%m-%d"), hasta.strftime("%Y-%m-%d")
    )
    if not dias:
        return False

    hoja = _Hoja()
    hoja.poner(0, 0, messages.REPORTE_XLSX_TITULO, negrita=True)
    hoja.poner(1, 0, f"Período: {desde:%d/%m/%Y} → {hasta:%d/%m/%Y}")

    fila_base = 3
    paso = COLUMNAS_DIA + SEPARACION

    for indice, dia in enumerate(_dias_del_rango(desde, hasta)):
        # Todos los días van hacia la derecha; cada tres se abre un hueco más
        # ancho, que es lo que dibuja el "bloque".
        columna = indice * paso + (indice // DIAS_POR_BLOQUE) * SEPARACION_BLOQUE
        for desplazamiento, medida in enumerate(ANCHOS_DIA):
            hoja.ancho_de(columna + desplazamiento, medida)

        fecha = datetime.strptime(dia, "%Y-%m-%d")
        hoja.poner(fila_base, columna, f"📅 {fecha:%d/%m/%Y}", negrita=True)

        marcas = dias.get(dia, [])
        if not marcas:
            hoja.poner(fila_base + 1, columna, messages.REPORTE_SIN_DATOS_DIA)
            continue

        for desplazamiento, encabezado in enumerate(("#", "TRAMO", "TOTAL")):
            hoja.poner(fila_base + 1, columna + desplazamiento,
                       encabezado, negrita=True)

        filas, total = tabla_del_dia(marcas)
        for numero, (indice_txt, tramo, acumulado) in enumerate(filas):
            for desplazamiento, valor in enumerate((indice_txt, tramo, acumulado)):
                hoja.poner(fila_base + 2 + numero, columna + desplazamiento, valor)

        hoja.poner(fila_base + 2 + len(filas) + 1, columna,
                   f"TOTAL DEL DÍA: {total}", negrita=True)

    _escribir(destino, hoja)
    return True
