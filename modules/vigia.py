"""Vigía: andamio de planificación y ejecución secuencial.

No vigila cuánto rato llevas trabajando. Sostiene que una tarea larga mantenga
una **cadena de ejecución lógica**:

    objetivo -> contexto -> foto -> PLAN completo -> ejecutas bloque a bloque
      -> foto nueva cuando algo cambió -> plan corregido -> ... -> listo

El problema que ataca no es la falta de esfuerzo. Es que una tarea difusa
produce una secuencia ineficiente: sacar basura, ordenar ropa, volver a la
basura, ordenar una caja, volver a la ropa. Cada salto cuesta un
desplazamiento, un cambio de contexto y una decisión.

Tres decisiones que sostienen el módulo y que no hay que revertir:

- **La continuidad es semántica, no temporal.** No hay duración, ni cuenta
  regresiva, ni pings de presencia, ni "¿sigues ahí?". Puedes parar media
  hora, cerrar el computador y volver al día siguiente: el objetivo sigue
  donde estaba. Una pausa no es un fallo porque el tiempo no es la unidad.
- **La foto es el punto de reentrada, no un control de asistencia.** Sólo se
  analiza cuando tú mandas una; Vigía nunca la pide sola.
- **Un bloque a la vez en pantalla, el plan entero en la base.** La foto
  produce todos los bloques ya redactados; avanzar sólo mueve un índice y no
  llama al modelo. Ver los veinte pasos de golpe obliga a planificar otra vez
  antes de empezar; pedírselos de a uno gastaba una consulta por paso.

El tiempo puede aparecer como estimación, pero no manda: no abre plazos, no
decide cuándo observar y no determina si vas atrasado.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import messages
from core.scheduler import from_iso, iso, now_local

# Etapas. Ninguna depende del reloj. `CERRANDO` es el único paso que se agrega:
# el objetivo ya está cumplido y la sesión sigue viva sólo por si quieres dejar
# registrado el resultado. No hay plazo para decidirlo.
ESPERANDO_FOTO = "esperando_foto"
TRABAJANDO = "trabajando"
CERRANDO = "cerrando"

# Etiqueta de la foto de cierre en `vigia_evidence`: la distingue de las que se
# miraron para planificar, que es lo que esa columna venía guardando.
EVIDENCIA_FINAL = "final"

# Hasta cuándo la cuota de Gemini está agotada. La API dice cuántos segundos
# faltan; guardarlo evita gastar consultas que ya se sabe que van a fallar.
CUOTA_KEY = "vigia_cuota_hasta"
CUOTA_LIMITE_KEY = "vigia_cuota_limite"

COMANDOS = ("/vigia", "/vigia_trabado", "/vigia_cancelar", "/vigia_stop",
            "/vigia_bloque_ok", "/vigia_otra_foto", "/vigia_reintentar",
            "/vigia_bloque", "/vigia_siguiente", "/vigia_registrar",
            "/vigia_cerrar")


def _espera_de_cuota(reason) -> int | None:
    """Segundos que la API pide esperar tras un 429, o None si no fue eso.

    Un 429 es cuota agotada, no saturación: reintentar enseguida gasta otra
    consulta del mismo minuto y alarga el encierro.
    """
    crudo = str(reason or "")
    if "HTTP 429" not in crudo:
        return None
    encontrado = re.search(r"retry in ([0-9.]+)s", crudo)
    return int(float(encontrado.group(1))) + 1 if encontrado else 60


def _leer_lista(crudo) -> list:
    try:
        datos = json.loads(crudo) if crudo else []
    except (TypeError, ValueError):
        return []
    return datos if isinstance(datos, list) else []


def _contexto_nuevo(session) -> dict:
    """Los campos del contexto que cambiaron desde la última foto analizada.

    No es todo el contexto: es sólo lo que el modelo todavía no vio. Editar
    el contexto a mitad de tarea debería pesar como motivo propio, y mezclado
    dentro de "CONTEXTO DADO POR LA PERSONA" se diluía entre lo que ya sabía.
    """
    anterior = session.contexto_analizado or {}
    return {
        campo: valor
        for campo, valor in (session.contexto or {}).items()
        if campo in CAMPOS_CONTEXTO and str(valor or "").strip()
        and str(valor or "").strip() != str(anterior.get(campo, "") or "").strip()
    }


def _restantes(session) -> list:
    """Los bloques que de verdad quedan: del que está en curso hacia adelante.

    Antes se le mandaba el plan **entero** bajo la etiqueta "bloques que
    quedaban por hacer", incluidos los ya declarados. Con la foto mostrando
    lo contrario, la contradicción volvía de dos formas: el mismo primer
    bloque otra vez —porque la regla le pide mantener el plan— y una DERIVA
    falsa, que acusaba de desviarse justo después de haber avanzado.

    El índice es `len(declarados)`: lo declarado desde la última foto.
    """
    plan = _leer_lista(session.estrategia)
    if not plan:
        return []
    return plan[len(session.declarados or []):]


def _leer_contexto(crudo) -> dict:
    """El contexto es JSON. Un texto suelto de una versión anterior no se
    pierde: entra como `extra`, que es donde va lo que se escribe libre."""
    if not crudo:
        return {}
    try:
        datos = json.loads(crudo)
    except (TypeError, ValueError):
        return {"extra": str(crudo)}
    return datos if isinstance(datos, dict) else {"extra": str(crudo)}

# Campos del contexto mínimo. Todos opcionales: si el objetivo y la foto
# alcanzan, no se toca ninguno. Viven como JSON en una sola columna para no
# multiplicar columnas por un formulario.
CAMPOS_CONTEXTO = ("alcance", "prioridad", "elementos", "restricciones", "extra")


@dataclass
class Session:
    event_id: str
    objetivo: str
    stage: str
    contexto: dict
    estrategia: str = ""
    bloque: str = ""
    trabado: bool = False
    ultima_foto: str = ""
    declarados: list = None
    contexto_analizado: dict = None


class VigiaModule:
    def __init__(self, config, db, telegram, vision, privacy):
        self.config = config
        self.db = db
        self.telegram = telegram
        self.vision = vision
        # Se conserva por compatibilidad con el arranque, pero Vigía ya no
        # ofusca el calendario: una sesión puede durar días, y dejar los
        # títulos ofuscados días es exactamente el incidente que no se repite.
        self.privacy = privacy

    # ---------------------------------------------------------------- datos

    def _row(self):
        return self.db.one("SELECT * FROM vigia_session WHERE id = 1")

    def _session(self) -> Session | None:
        row = self._row()
        if not row or not row["active"]:
            return None
        return Session(
            event_id=row["event_id"],
            objetivo=row["title"] or "",
            stage=row["stage"] or ESPERANDO_FOTO,
            contexto=_leer_contexto(row["contexto"]),
            estrategia=row["estrategia"] or "",
            bloque=row["bloque"] or "",
            trabado=bool(row["trabado"]),
            ultima_foto=row["ultima_foto"] or "",
            declarados=_leer_lista(row["declarados"]),
            contexto_analizado=_leer_contexto(row["contexto_analizado"]),
        )

    # --------------------------------------------------- contexto (lo usa Panel)

    def sesion_activa(self):
        return self._session()

    def contexto_actual(self) -> dict:
        session = self._session()
        return dict(session.contexto) if session else {}

    def guardar_contexto(self, campo: str, valor: str) -> bool:
        """Un campo del contexto mínimo. Devuelve False si no hay tarea."""
        session = self._session()
        if not session or campo not in CAMPOS_CONTEXTO:
            return False
        contexto = dict(session.contexto)
        contexto[campo] = (valor or "").strip()
        with self.db.transaction():
            self._update(contexto=json.dumps(contexto, ensure_ascii=False))
        return True

    def _update(self, **fields) -> None:
        if not fields:
            return
        columns = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(
            f"UPDATE vigia_session SET {columns}, updated_at = ? WHERE id = 1",
            (*fields.values(), iso(now_local())),
        )

    def _close(self) -> None:
        self._update(
            active=0, event_id=None, raw_title=None, title=None, activity_type=None,
            stage=None, created_at=None, start_photo_ref=None,
            contexto=None, estrategia=None, bloque=None, trabado=0,
            ultima_foto=None, declarados=None, contexto_analizado=None,
        )

    def _say(self, text: str, buttons=None) -> None:
        self.db.enqueue(self.config.owner_chat_id, text,
                        buttons=buttons, parse_mode="HTML")

    def _cuota_diaria(self, reason: str = "") -> int:
        """El límite que reporta el propio 429, o el último que se vio."""
        encontrado = re.search(r"limit:\s*(\d+)", str(reason or ""))
        if encontrado:
            self.db.set_state(CUOTA_LIMITE_KEY, int(encontrado.group(1)))
            return int(encontrado.group(1))
        return int(self.db.get_state(CUOTA_LIMITE_KEY, 20) or 20)

    def _cuota_restante(self) -> int:
        """Segundos que faltan para que la cuota vuelva. 0 si ya está libre."""
        hasta = from_iso(self.db.get_state(CUOTA_KEY))
        if not hasta:
            return 0
        return max(0, int((hasta - now_local()).total_seconds()))

    def _directo(self, text: str, buttons=None) -> None:
        """Sale ya, sin pasar por la outbox.

        La llamada a Gemini es síncrona y bloquea el ciclo entero hasta 90
        segundos. Todo lo que se encole antes de ella se queda esperando a que
        termine, así que un "manda la foto" llegaría *después* del análisis que
        no pediste. Estos mensajes no acompañan ningún cambio de estado, así
        que saltarse la outbox no rompe la garantía de escribir estado y
        mensaje juntos.
        """
        try:
            self.telegram.send_message(
                self.config.owner_chat_id, text, buttons, "HTML"
            )
        except Exception as exc:
            print(f"[vigia] envío directo falló: {exc}", flush=True)
            with self.db.transaction():
                self._say(text, buttons=buttons)

    # -------------------------------------------------------------- comandos

    def handle_command(self, command: str, raw_text: str) -> bool:
        if command not in COMANDOS:
            return False

        if command in ("/vigia_cancelar", "/vigia_stop"):
            self.stop(command)
            return True

        if command == "/vigia_trabado":
            return self._trabado()

        if command in ("/vigia_bloque_ok", "/vigia_otra_foto"):
            return self._pedir_foto(command)

        if command == "/vigia_reintentar":
            return self.reanalizar()

        if command == "/vigia_bloque":
            return self._reanudar()

        if command == "/vigia_siguiente":
            return self._siguiente()

        if command == "/vigia_registrar":
            return self._registrar()

        if command == "/vigia_cerrar":
            return self._cerrar(messages.VIGIA_CERRADO, command)

        objetivo = raw_text.replace("/vigia", "", 1).strip()
        if not objetivo:
            with self.db.transaction():
                self._say(messages.VIGIA_USO, buttons=messages.VIGIA_BOTONES_CIERRE)
            return True

        if self._session():
            with self.db.transaction():
                self._say(messages.VIGIA_YA_ACTIVA, buttons=messages.VIGIA_BOTONES_CIERRE)
            return True

        ahora = now_local()
        with self.db.transaction():
            self._update(
                active=1,
                event_id=f"vigia:{ahora.isoformat()}",
                title=objetivo, raw_title=objetivo,
                stage=ESPERANDO_FOTO, created_at=iso(ahora),
                contexto="", estrategia="", bloque="", trabado=0,
                start_photo_ref=None, contexto_analizado=None,
            )
            self._say(
                f"{messages.vigia_objetivo(objetivo)}\n\n{messages.VIGIA_PIDE_FOTO}",
                buttons=messages.VIGIA_BOTONES_INICIO,
            )
            self.db.audit("vigia", "objetivo")
        return True

    def _trabado(self) -> bool:
        """No es un fracaso ni reinicia nada: pide otra observación."""
        session = self._session()
        if not session:
            with self.db.transaction():
                self._say(messages.VIGIA_SIN_OBJETIVO,
                          buttons=messages.VIGIA_BOTONES_CIERRE)
            return True
        with self.db.transaction():
            self._update(trabado=1)
            self._say(messages.VIGIA_TRABADO_PIDE_FOTO,
                      buttons=messages.VIGIA_BOTONES_TRABADO)
            self.db.audit("vigia", "trabado")
        return True

    def _reanudar(self) -> bool:
        """Vuelve a mostrar el bloque en curso, con sus botones.

        No llama al modelo ni pide una foto: el estado ya está en la base. Es
        para cuando volviste dos días después y el mensaje quedó mil líneas
        más arriba en el chat.
        """
        session = self._session()
        if not session:
            with self.db.transaction():
                self._say(messages.VIGIA_SIN_OBJETIVO,
                          buttons=messages.VIGIA_BOTONES_CIERRE)
            return True

        if not session.bloque:
            with self.db.transaction():
                self._say(
                    f"{messages.vigia_objetivo(session.objetivo)}\n\n"
                    f"{messages.VIGIA_SIN_BLOQUE}",
                    buttons=messages.VIGIA_BOTONES_INICIO,
                )
            return True

        with self.db.transaction():
            if session.trabado:
                # Volver al bloque es la salida de ME TRABÉ sin foto: se sigue
                # con lo que había, así que el trabado deja de estar puesto.
                self._update(trabado=0)
            self._say(
                messages.vigia_reanudar(session.objetivo, session.bloque),
                buttons=messages.VIGIA_BOTONES,
            )
        return True

    def _siguiente(self) -> bool:
        """Avanza al bloque siguiente del plan. **No llama al modelo.**

        El plan entero lo escribió Gemini al ver la primera foto: son bloques
        ya redactados para ejecutarse tal cual. Recorrerlos es mover un índice,
        no una decisión — preguntarle otra vez lo que ya dijo gastaba una
        consulta por paso y podía devolver el bloque anterior.

        Gemini queda para lo único que exige mirar: las fotos.
        """
        session = self._session()
        if not session:
            with self.db.transaction():
                self._say(messages.VIGIA_SIN_OBJETIVO,
                          buttons=messages.VIGIA_BOTONES_CIERRE)
            return True

        if session.stage == CERRANDO:
            # El objetivo ya se dio por cumplido: no hay bloque siguiente que
            # dar, sólo queda registrar o cerrar.
            with self.db.transaction():
                self._say(messages.vigia_completado(session.objetivo),
                          buttons=messages.VIGIA_BOTONES_FINAL)
            return True

        if session.trabado:
            # Avanzar declara hecho el bloque actual, y el actual es justo el
            # que no se pudo hacer. Recalibrar exige mirar primero.
            with self.db.transaction():
                self._say(messages.VIGIA_TRABADO_EXIGE_FOTO,
                          buttons=messages.VIGIA_BOTONES_TRABADO)
            return True

        plan = _leer_lista(session.estrategia)
        if not session.bloque or not plan:
            with self.db.transaction():
                self._say(
                    f"{messages.vigia_objetivo(session.objetivo)}\n\n"
                    f"{messages.VIGIA_SIN_BLOQUE if not session.bloque else messages.VIGIA_SIN_PLAN}",
                    buttons=messages.VIGIA_BOTONES_INICIO,
                )
            return True

        # El índice es cuántos bloques se dieron por hechos desde la última
        # foto. No hace falta guardarlo aparte.
        declarados = list(session.declarados or []) + [session.bloque]
        indice = len(declarados)

        if indice >= len(plan):
            # Se acabó el plan. La foto puede confirmar el objetivo o mostrar
            # lo que falta, pero cerrar sin ella también es un final válido.
            with self.db.transaction():
                self._update(declarados=json.dumps(declarados, ensure_ascii=False))
                self._say(messages.VIGIA_PLAN_TERMINADO,
                          buttons=messages.VIGIA_BOTONES_PLAN_TERMINADO)
                self.db.audit("vigia", "plan_terminado")
            return True

        with self.db.transaction():
            self._update(
                bloque=plan[indice], trabado=0,
                declarados=json.dumps(declarados, ensure_ascii=False),
            )
            self._say(
                messages.vigia_bloque_numerado(plan[indice], indice + 1, len(plan)),
                buttons=messages.VIGIA_BOTONES,
            )
            self.db.audit("vigia", "siguiente")
        return True

    def _pedir_foto(self, command: str) -> bool:
        """"Bloque terminado" y "otra foto" hacen lo mismo: piden la entrada.

        Ninguno de los dos avanza el estado por su cuenta — el que decide qué
        sigue es el análisis de la foto, no el botón.
        """
        if not self._session():
            with self.db.transaction():
                self._say(messages.VIGIA_SIN_OBJETIVO,
                          buttons=messages.VIGIA_BOTONES_CIERRE)
            return True
        texto = (messages.VIGIA_BLOQUE_OK if command == "/vigia_bloque_ok"
                 else messages.VIGIA_OTRA_FOTO)
        # Directo: pedir una foto tiene que verse en el acto, no detrás de un
        # análisis que puede tardar un minuto y medio.
        self._directo(texto, messages.VIGIA_BOTONES_ESPERA)
        return True

    def _registrar(self) -> bool:
        """Pide la foto del resultado. Es documentación, no una prueba.

        No hay forma de "reprobar" acá: la foto se guarda y se cierra. Mirarla
        para replanificar reabriría una tarea que ya se dio por terminada.
        """
        session = self._session()
        if not session:
            with self.db.transaction():
                self._say(messages.VIGIA_SIN_OBJETIVO,
                          buttons=messages.VIGIA_BOTONES_CIERRE)
            return True
        with self.db.transaction():
            self._update(stage=CERRANDO, trabado=0)
            self._say(messages.VIGIA_REGISTRO_PIDE_FOTO,
                      buttons=messages.VIGIA_BOTONES_REGISTRO)
        return True

    def _cerrar(self, texto: str, reason: str = "") -> bool:
        """Cierra la tarea como cumplida. No exige foto de ningún tipo."""
        session = self._session()
        if not session:
            with self.db.transaction():
                self._say(messages.VIGIA_SIN_OBJETIVO,
                          buttons=messages.VIGIA_BOTONES_CIERRE)
            return True
        with self.db.transaction():
            self.db.execute(
                "INSERT OR REPLACE INTO vigia_completed_events(event_id, completed_at) "
                "VALUES (?, ?)",
                (session.event_id, iso(now_local())),
            )
            self._close()
            self._say(texto, buttons=messages.VIGIA_BOTONES_CIERRE)
            self.db.audit("vigia", "cerrado", reason)
        return True

    def stop(self, reason: str = "") -> None:
        session = self._session()
        with self.db.transaction():
            if not session:
                self._say(messages.VIGIA_SIN_OBJETIVO,
                          buttons=messages.VIGIA_BOTONES_CIERRE)
                return
            self.db.execute(
                "INSERT OR REPLACE INTO vigia_completed_events(event_id, completed_at) "
                "VALUES (?, ?)",
                (session.event_id, iso(now_local())),
            )
            self._close()
            self._say(messages.VIGIA_CANCELADO, buttons=messages.VIGIA_BOTONES_CIERRE)
            self.db.audit("vigia", "cancelado", reason)

    # ----------------------------------------------------------------- texto

    def handle_text(self, text: str) -> bool:
        """Contexto escrito antes de la primera foto. Nada más.

        Se deja pasar el texto de sólo cuatro dígitos: es el código de
        Guardian, que se atiende después en la cadena del router.
        """
        limpio = (text or "").strip()
        if not limpio or limpio.isdigit() and len(limpio) == 4:
            return False

        session = self._session()
        if not session or session.stage != ESPERANDO_FOTO:
            return False

        extra = f"{session.contexto.get('extra', '')}\n{limpio}".strip()
        self.guardar_contexto("extra", extra)
        with self.db.transaction():
            self._say(messages.VIGIA_CONTEXTO_OK, buttons=messages.VIGIA_BOTONES_INICIO)
        return True

    # ----------------------------------------------------------------- fotos

    def handle_photo(self, message) -> bool:
        session = self._session()
        if not session:
            return False
        fotos = message.get("photo") or []
        if not fotos:
            return False

        # Acuse inmediato y directo: si esperara al ciclo llegaría junto con
        # el análisis, que es justo cuando ya no sirve. Con la cuota agotada no
        # hay análisis que esperar, así que no se promete uno.
        if session.stage != CERRANDO and not self._cuota_restante():
            try:
                self.telegram.send_message(
                    self.config.owner_chat_id, messages.VIGIA_FOTO_RECIBIDA
                )
            except Exception:
                pass

        try:
            ruta = self.telegram.download_photo(
                fotos[-1]["file_id"], self.config.evidence_dir
            )
        except Exception as exc:
            print(f"[vigia] no pude bajar la foto: {exc}", flush=True)
            return True

        # La foto de después es registro: se guarda y cierra, sin analizarla.
        # Pasarla por el modelo sería buscarle defectos a algo ya terminado.
        if session.stage == CERRANDO:
            self._registrar_final(session, ruta)
            return True

        self._analizar(session, ruta)
        return True

    def _analizar(self, session: Session, ruta) -> None:
        """Foto + objetivo + plan vigente -> plan completo de lo que queda.

        Es la única llamada al modelo que queda. Devuelve la lista entera de
        bloques restantes, ya redactados, y el primero es el de ahora. Avanzar
        por esa lista después no cuesta nada.
        """
        if self._cuota_restante():
            with self.db.transaction():
                self._say(messages.vigia_cuota(self._cuota_diaria()),
                          buttons=messages.VIGIA_BOTONES_REINTENTO)
            return

        prompt = messages.VIGIA_PROMPT_PLAN.format(
            objetivo=session.objetivo,
            contexto=messages.vigia_contexto_prompt(session.contexto),
            estrategia=messages.vigia_pendientes(_restantes(session))
                       if session.estrategia else "(todavía no hay plan)",
            contexto_nuevo=messages.vigia_contexto_nuevo(_contexto_nuevo(session)),
            bloque=session.bloque or "(todavía no hay bloque asignado)",
            trabado="sí" if session.trabado else "no",
            declarados=messages.vigia_declarados(session.declarados or []),
        )

        resultado = {}
        if self.vision and self.vision.enabled:
            try:
                resultado = self.vision.planificar(ruta, prompt) or {}
            except Exception as exc:
                print(f"[vigia] análisis fallido: {exc}", flush=True)

        estado = str(resultado.get("estado") or "").upper()
        plan = resultado.get("estrategia") or []
        if isinstance(plan, str):
            plan = [plan]
        plan = [str(b).strip() for b in plan if str(b).strip()]

        # El modelo puede decir que no le alcanza. Se guarda la foto para
        # reanalizarla con la respuesta, sin pedir otra.
        if estado == "FALTA_CONTEXTO":
            pregunta = str(resultado.get("pregunta") or "").strip()
            if pregunta:
                with self.db.transaction():
                    self._update(ultima_foto=str(ruta))
                    self._say(messages.vigia_falta_contexto(pregunta),
                              buttons=messages.VIGIA_BOTONES_FALTA)
                    self.db.audit("vigia", "falta_contexto")
                return

        if estado != "COMPLETADO" and (
                resultado.get("decision") == "TECHNICAL_ERROR" or not plan):
            # Que falle el análisis no pierde la tarea: objetivo, plan y bloque
            # siguen donde estaban.
            razon = resultado.get("reason", "")
            print(f"[vigia] sin plan: {razon}", flush=True)
            cuota = _espera_de_cuota(razon)
            with self.db.transaction():
                self._update(ultima_foto=str(ruta))
                if cuota:
                    # Es una cuota DIARIA: la ventana corta sólo evita que un
                    # reintento inmediato gaste otra consulta al pedo.
                    self.db.set_state(
                        CUOTA_KEY, iso(now_local() + timedelta(seconds=cuota))
                    )
                self._say(
                    messages.vigia_cuota(self._cuota_diaria(razon)) if cuota
                    else messages.vigia_fallo(razon),
                    buttons=messages.VIGIA_BOTONES_REINTENTO,
                )
            return

        with self.db.transaction():
            self.db.execute(
                """
                INSERT INTO vigia_evidence
                    (event_id, stage, path, sha256, approved, decision,
                     reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.event_id, session.stage, str(ruta),
                    hashlib.sha256(ruta.read_bytes()).hexdigest(),
                    1, estado or "EN_RUTA",
                    (plan[0] if plan else "")[:300], iso(now_local()),
                ),
            )
            # El análisis tuvo éxito: lo que se le mandó como contexto ya no
            # es "nuevo" para la próxima foto. Se guarda acá y no antes, porque
            # un TECHNICAL_ERROR o un FALTA_CONTEXTO no llegan a este punto: en
            # esos casos el cambio sigue sin verse y debe reenviarse igual.
            self._update(contexto_analizado=json.dumps(
                session.contexto, ensure_ascii=False))

        if estado == "COMPLETADO":
            self._completar(session)
            return

        # La foto comprueba lo que había: los declarados se vacían y el plan
        # empieza de nuevo desde su primer bloque.
        with self.db.transaction():
            campos = dict(
                stage=TRABAJANDO, bloque=plan[0], trabado=0,
                estrategia=json.dumps(plan, ensure_ascii=False),
                declarados=json.dumps([], ensure_ascii=False),
                ultima_foto=str(ruta),
            )
            if not session.bloque:
                campos["start_photo_ref"] = str(ruta)
            self._update(**campos)
            if estado == "DERIVA":
                self._say(
                    messages.vigia_deriva(str(resultado.get("nota") or ""), plan[0]),
                    buttons=messages.VIGIA_BOTONES,
                )
            else:
                self._say(
                    messages.vigia_bloque_numerado(
                        plan[0], 1, len(plan),
                        str(resultado.get("estimacion") or ""),
                    ),
                    buttons=messages.VIGIA_BOTONES,
                )
            self.db.audit("vigia", (estado or "en_ruta").lower())

    def reanalizar(self) -> bool:
        """Vuelve a analizar la última foto, ya con la aclaración escrita.

        Pedir otra foto sólo porque faltaba un dato sería cobrarle a la
        persona un viaje que no hace falta: la imagen no cambió.
        """
        session = self._session()
        if not session or not session.ultima_foto:
            with self.db.transaction():
                self._say(messages.VIGIA_OTRA_FOTO,
                          buttons=messages.VIGIA_BOTONES_ESPERA)
            return True
        ruta = Path(session.ultima_foto)
        if not ruta.exists():
            with self.db.transaction():
                self._say(messages.VIGIA_OTRA_FOTO,
                          buttons=messages.VIGIA_BOTONES_ESPERA)
            return True
        if not self._cuota_restante():
            self._directo(messages.VIGIA_PENSANDO)
        self._analizar(session, ruta)
        return True

    def _completar(self, session: Session) -> None:
        """El objetivo está cumplido. La sesión queda abierta un paso más.

        Ese paso no es un requisito: es la oferta de dejar registrado el
        resultado. Cerrar sin foto termina la tarea igual de bien, y no hay
        plazo para elegir —la sesión aguanta días, como siempre.
        """
        with self.db.transaction():
            self._update(stage=CERRANDO, trabado=0)
            self._say(messages.vigia_completado(session.objetivo),
                      buttons=messages.VIGIA_BOTONES_FINAL)
            self.db.audit("vigia", "completado")

    def _registrar_final(self, session: Session, ruta) -> None:
        """Guarda la foto de cierre y cierra. **No llama al modelo.**

        Se marca con su propia etapa para no confundirla nunca con las que se
        miraron para planificar: ésta no aprobó ni reprobó nada.
        """
        with self.db.transaction():
            self.db.execute(
                """
                INSERT INTO vigia_evidence
                    (event_id, stage, path, sha256, approved, decision,
                     reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.event_id, EVIDENCIA_FINAL, str(ruta),
                    hashlib.sha256(ruta.read_bytes()).hexdigest(),
                    1, "REGISTRO", "", iso(now_local()),
                ),
            )
        self._cerrar(messages.VIGIA_REGISTRO_OK, "registro")

    # ------------------------------------------------------------------ tick

    def tick(self, events) -> None:
        """Vigía ya no tiene nada que hacer en el ciclo.

        No hay plazos que vencer ni mensajes periódicos que emitir: la tarea
        avanza sólo cuando llega una observación. Se conserva el método porque
        el runtime lo llama en cada vuelta, y la firma porque recibe los
        eventos del ICS aunque ya no los use.
        """
        return
