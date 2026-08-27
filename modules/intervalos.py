"""Intervalos: cronómetro de vueltas.

Es el mismo gesto que apretar "Vuelta" en el cronómetro del teléfono. Cada
`/marca` guarda una hora; la tabla muestra cuánto pasó desde la marca anterior
(tramo) y desde la primera del ciclo (total).

Un ciclo termina cuando lo cerrás con `/reset` o cuando pasan cuatro horas sin
marcas. Nunca por el reloj de pared: la medianoche no significa nada para un
cronómetro, y cortar ahí partía al medio cualquier ciclo en curso a las 23:58.

Tres decisiones que sostienen el módulo:

- **Sin opinión.** No hay rachas, récords ni comparaciones. El aviso sólo
  informa que terminó la espera; el cronómetro sigue siendo un instrumento,
  no un juez.
- **Sin acoplamiento.** No comparte estado con nadie. Que dos
  módulos hablen del mismo tema no significa que deban tocarse.
- **Sólo se guardan hechos.** La base almacena horas. El tramo y el total se
  calculan al mostrarlos, así que nunca pueden discrepar con el dato real.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import core.scheduler as sched
import messages

# Más de esto y la tabla deja de leerse de un vistazo en el teléfono.
MAX_FILAS = 10

# Momento del último /reset. No hace falta una columna: el corte es un punto
# en el tiempo, y las marcas anteriores siguen intactas donde estaban.
RESET_KEY = "intervalos_reset_at"

# Qué marca ya usó su consulta libre de `/tiempo`.
#
# Guarda el `id` de esa marca, no un contador: el id ES la identidad del
# intervalo, así que marcar de nuevo devuelve la consulta libre sin resetear
# nada. Tampoco hace falta contar las repeticiones — todas caen en la misma
# fricción, y contarlas sólo serviría para ponerles un tope que no queremos.
# Va en `system_state` por lo mismo que RESET_KEY —sobrevive al reinicio y no
# obliga a una columna nueva— y no toca ni el cálculo ni el historial.
TIEMPO_USADO_KEY = "intervalos_tiempo_usado"

# Cuánto dura la espera a ciegas desde una marca hasta el aviso.
ESPERA_MINUTOS = 76

# Secuencia finita del aviso, en segundos desde que se cumple el intervalo.
#
#   ráfaga 1   1 mensaje                                    0
#   pausa      2 minutos y medio
#   ráfaga 2   2 mensajes cada 30s                    150, 180
#   pausa      4 minutos
#   ráfaga 3   1 mensaje                                   420
#
# Después del cuarto mensaje la marca queda cerrada y no vuelve a avisar.
MOMENTOS_AVISO = (0, 150, 180, 420)


def momento_del_aviso(numero: int) -> int | None:
    """Segundo del aviso; devuelve None cuando la secuencia ya terminó."""
    if numero < 1 or numero > len(MOMENTOS_AVISO):
        return None
    return MOMENTOS_AVISO[numero - 1]


# Un hueco de esta duración cierra el ciclo solo.
#
# Antes el corte era la medianoche, y eso partía al medio cualquier ciclo que
# estuviera en curso a las 23:58. La hora del reloj no significa nada para un
# cronómetro: lo que marca el fin de un ciclo es dejar de usarlo.
HORAS_CIERRE = 4


def formato_duracion(segundos: float) -> str:
    """`00m 00s`, `56m 44s`, `2h 07m 14s`."""
    total = max(0, int(segundos))
    horas, resto = divmod(total, 3600)
    minutos, segs = divmod(resto, 60)
    if horas:
        return f"{horas}h {minutos:02d}m {segs:02d}s"
    return f"{minutos:02d}m {segs:02d}s"


class IntervalosModule:
    def __init__(self, config, db):
        self.config = config
        self.db = db

    # ------------------------------------------------------------- básicos

    def _user(self) -> str:
        return str(self.config.owner_chat_id)

    def _zona(self):
        """La zona se resuelve UNA vez, en el scheduler, y de ahí sale.

        Construirla acá con `ZoneInfo` revienta en Windows, que no trae la base
        de zonas IANA. Y peor que reventar sería que no reventara: cada módulo
        interpretando la zona por su cuenta puede terminar agrupando días en
        una zona distinta de la que el resto del sistema usa para las horas.

        Esto NO cambia ningún tiempo de Intervalos: el intervalo, la secuencia
        de avisos y el cierre del ciclo siguen exactamente donde estaban. Sólo
        cambia de dónde sale el objeto de zona para calcular el día local.
        """
        return sched.timezone_actual() or datetime.now().astimezone().tzinfo

    def _hoy(self) -> str:
        """Día local de la marca. No decide nada: es para agrupar después.

        El ciclo ya no se corta por fecha, pero guardar el día en zona local
        (y no en UTC) es lo que permitirá que un historial futuro diga "el
        martes" y coincida con lo que la persona vivió como martes.
        """
        return datetime.now(self._zona()).strftime("%Y-%m-%d")

    def _marcas_del_ciclo(self):
        """Las marcas del ciclo en curso.

        Un ciclo se cierra de dos maneras: con `/reset`, o solo cuando pasan
        más de `HORAS_CIERRE` sin una marca nueva. Ninguna de las dos borra
        nada: el límite se deduce de los datos, y todo lo anterior sigue
        entero en la base.
        """
        filas = self.db.query(
            """
            SELECT * FROM interval_marks
            WHERE user_id = ? AND marked_at_utc > ?
            ORDER BY marked_at_utc ASC, id ASC
            """,
            (self._user(), self.db.get_state(RESET_KEY, "") or ""),
        )
        if not filas:
            return []

        horas = [datetime.fromisoformat(f["marked_at_utc"]) for f in filas]
        hueco = HORAS_CIERRE * 3600

        # Si ya pasaron más de 4 horas desde la última, el ciclo se cerró solo.
        if (datetime.now(timezone.utc) - horas[-1]).total_seconds() > hueco:
            return []

        # El ciclo empieza después del último hueco largo.
        inicio = 0
        for i in range(1, len(horas)):
            if (horas[i] - horas[i - 1]).total_seconds() > hueco:
                inicio = i
        return filas[inicio:]

    def _say(self, text: str, buttons=None) -> None:
        self.db.enqueue(
            self._user(), text,
            buttons=messages.INTERVALOS_BOTONES if buttons is None else buttons,
            parse_mode="HTML",
        )

    def _ultima_marca(self):
        """Sólo la marca más reciente tiene aviso pendiente.

        Marcar de nuevo reinicia la cuenta: si no esperaste el intervalo
        completo, no corresponde decirte que lo respetaste.
        """
        return self.db.one(
            """
            SELECT * FROM interval_marks WHERE user_id = ?
            ORDER BY marked_at_utc DESC, id DESC LIMIT 1
            """,
            (self._user(),),
        )

    # -------------------------------------------------- aviso del intervalo

    def tick(self) -> None:
        marca = self._ultima_marca()
        if not marca or marca["alert_ack"]:
            return

        cumple = (datetime.fromisoformat(marca["marked_at_utc"])
                  + timedelta(minutes=ESPERA_MINUTOS))
        ahora = datetime.now(timezone.utc)
        if ahora < cumple:
            return

        enviados = marca["alerts_sent"] or 0
        momento = momento_del_aviso(enviados + 1)
        if momento is None:
            with self.db.transaction():
                self.db.execute(
                    "UPDATE interval_marks SET alert_ack = 1 WHERE id = ?",
                    (marca["id"],),
                )
            return

        toca = cumple + timedelta(seconds=momento)
        if ahora < toca:
            return

        siguiente = enviados + 1
        terminado = siguiente == len(MOMENTOS_AVISO)
        with self.db.transaction():
            self.db.execute(
                """
                UPDATE interval_marks
                SET alerts_sent = ?, alert_ack = ?
                WHERE id = ?
                """,
                (siguiente, 1 if terminado else 0, marca["id"]),
            )
            self._say(messages.INTERVALOS_AVISO, buttons=[])

    # ------------------------------------------------------------ comandos

    def handle(self, command: str, source_id: object = None) -> bool:
        if command == "/marca":
            return self._marcar(source_id)
        if command == "/tiempo":
            return self._tiempo()
        if command == "/tiempo_mostrar":
            return self._tiempo_mostrar()
        if command == "/tiempo_dejarlo":
            return self._tiempo_dejarlo()
        if command == "/reset":
            return self._reset()
        return False

    def _reset(self) -> bool:
        """Cierra el ciclo en curso. No borra: mueve el punto de partida."""
        marcas = self._marcas_del_ciclo()
        with self.db.transaction():
            if not marcas:
                self._say(messages.INTERVALOS_SIN_CICLO)
                return True

            primera = datetime.fromisoformat(marcas[0]["marked_at_utc"])
            ultima = datetime.fromisoformat(marcas[-1]["marked_at_utc"])
            total = formato_duracion((ultima - primera).total_seconds())

            self.db.set_state(RESET_KEY, datetime.now(timezone.utc).isoformat())
            # Cerrar el ciclo a mano también apaga el aviso pendiente: no
            # tiene sentido avisar del final de una espera que interrumpiste.
            self.db.execute(
                "UPDATE interval_marks SET alert_ack = 1 WHERE id = ?",
                (marcas[-1]["id"],),
            )
            self._say(messages.intervalos_ciclo_cerrado(len(marcas), total))
            self.db.audit("intervalos", "reset", f"{len(marcas)} marcas")
        return True

    def _marcar(self, source_id: object) -> bool:
        ahora = datetime.now(timezone.utc)
        # Un mismo mensaje reintentado no puede generar dos marcas. Si no hay
        # identificador, el segundo cae de vuelta al segundo exacto.
        token = source_id if source_id is not None else ahora.strftime("%Y%m%dT%H%M%S")
        request_id = f"intervalo:{self._user()}:{token}"

        ya = self.db.one(
            "SELECT id FROM interval_marks WHERE request_id = ?", (request_id,)
        )
        if not ya:
            with self.db.transaction():
                self.db.execute(
                    """
                    INSERT INTO interval_marks
                        (user_id, marked_at_utc, local_day, request_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (self._user(), ahora.isoformat(), self._hoy(), request_id),
                )

        marcas = self._marcas_del_ciclo()
        with self.db.transaction():
            self._say(
                self._tabla(marcas) + "\n"
                + messages.intervalos_registrada(len(marcas), self._ultimo_tramo(marcas))
            )
        return True

    def _ultimo_tramo(self, marcas) -> str | None:
        """Cuánto pasó entre las dos últimas marcas. En la #1 no hay tramo."""
        if len(marcas) < 2:
            return None
        ultima = datetime.fromisoformat(marcas[-1]["marked_at_utc"])
        previa = datetime.fromisoformat(marcas[-2]["marked_at_utc"])
        return formato_duracion((ultima - previa).total_seconds())

    def _tiempo(self) -> bool:
        """Sólo lectura. La primera del intervalo es libre; las demás, con
        una decisión delante.

        Mirar el reloj cada dos minutos no acorta la espera: la alarga, porque
        cada consulta reinstala la espera en la cabeza. Pero orientarse a veces
        hace falta de verdad, así que no se prohíbe — se interrumpe el
        automatismo y se decide.
        """
        marcas = self._marcas_del_ciclo()
        if not marcas:
            with self.db.transaction():
                self._say(messages.INTERVALOS_SIN_MARCAS)
            return True

        # El intervalo es la última marca. Guardar su id es lo que hace que
        # marcar de nuevo devuelva la consulta libre, sin contadores.
        actual = int(marcas[-1]["id"])
        if self.db.get_state(TIEMPO_USADO_KEY) == actual:
            with self.db.transaction():
                self._say(messages.INTERVALOS_TIEMPO_FRICCION,
                          buttons=messages.INTERVALOS_TIEMPO_BOTONES)
            return True

        with self.db.transaction():
            self.db.set_state(TIEMPO_USADO_KEY, actual)
            self._decir_tiempo(marcas)
        return True

    def _decir_tiempo(self, marcas) -> None:
        """El cálculo, en un solo lugar: lo usan la consulta libre y MOSTRAR."""
        ultima = datetime.fromisoformat(marcas[-1]["marked_at_utc"])
        transcurrido = (datetime.now(timezone.utc) - ultima).total_seconds()
        self._say(messages.intervalos_desde_ultima(
            formato_duracion(transcurrido), len(marcas)
        ))

    def _tiempo_mostrar(self) -> bool:
        """Pasó la fricción. Se muestra, y la próxima vuelve a preguntarlo:
        el estado no cambia, así que la decisión no se compra una sola vez."""
        marcas = self._marcas_del_ciclo()
        with self.db.transaction():
            if not marcas:
                self._say(messages.INTERVALOS_SIN_MARCAS)
                return True
            self._decir_tiempo(marcas)
        return True

    def _tiempo_dejarlo(self) -> bool:
        with self.db.transaction():
            self._say(messages.INTERVALOS_TIEMPO_DEJADO, buttons=[])
        return True

    # -------------------------------------------------------------- tabla

    def _tabla(self, marcas) -> str:
        if not marcas:
            return f"{messages.INTERVALOS_TITULO}\n\n{messages.INTERVALOS_SIN_MARCAS}"

        horas = [datetime.fromisoformat(m["marked_at_utc"]) for m in marcas]
        primera = horas[0]

        filas = []
        for indice, momento in enumerate(horas):
            if indice == 0:
                tramo = messages.INTERVALOS_INICIO
            else:
                tramo = formato_duracion((momento - horas[indice - 1]).total_seconds())
            total = formato_duracion((momento - primera).total_seconds())
            filas.append((str(indice + 1), tramo, total))

        # Con muchas marcas se conserva el origen y las últimas: el medio es
        # justamente lo que ya no se está mirando.
        ocultas = 0
        if len(filas) > MAX_FILAS:
            ocultas = len(filas) - MAX_FILAS
            filas = [filas[0]] + filas[-(MAX_FILAS - 1):]

        cabecera = ("#", "TRAMO", "TOTAL")
        # Anchos mínimos: dan aire al cuadro para que no quede apretado en el
        # teléfono aunque las duraciones sean cortas.
        minimos = (2, 12, 11)
        anchos = [
            max(minimos[i], max(len(f[i]) for f in [cabecera] + filas))
            for i in range(3)
        ]

        # El marcador es ASCII a propósito: una flecha bonita puede no ocupar
        # exactamente un carácter y desalinea toda la tabla.
        MARCA, HUECO = ">  ", "   "

        lineas = [
            f"{HUECO}{cabecera[0]:<{anchos[0]}}  "
            f"{cabecera[1]:<{anchos[1]}}  {cabecera[2]}"
        ]
        for indice, (numero, tramo, total) in enumerate(filas):
            puntero = MARCA if indice == len(filas) - 1 else HUECO
            lineas.append(
                f"{puntero}{numero:<{anchos[0]}}  "
                f"{tramo:<{anchos[1]}}  {total}"
            )
        if ocultas:
            lineas.append("")
            lineas.append(messages.intervalos_ocultas(ocultas))

        # No se escapa nada: cada carácter de la tabla lo genera este módulo
        # (dígitos, letras y espacios). Escapar el conjunto convertiría el
        # marcador ">" en "&gt;" y ensuciaría el cuadro.
        return f"{messages.INTERVALOS_TITULO}\n\n<pre>{chr(10).join(lineas)}</pre>"
