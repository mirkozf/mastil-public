from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

import messages
from core.router import Router
from core.scheduler import now_local
from database import Database
from modules.intervalos import (
    CONTEXTO_PENDIENTE_KEY,
    ESPERA_MINUTOS,
    MOMENTOS_AVISO,
    IntervalosModule,
)
from modules.system import SystemModule


ROOT = Path(__file__).resolve().parents[1]


class IntervalosContextoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.log_path = ROOT / "tests" / "_intervalo_contexto.log"
        self.log_path.unlink(missing_ok=True)
        self.config = SimpleNamespace(owner_chat_id="100", db_path=ROOT / "mastil.db")
        self.db = Database(Path(":memory:"), ROOT / "schema.sql")
        self.db.migrate()
        self.intervalos = IntervalosModule(self.config, self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.log_path.unlink(missing_ok=True)

    def _ultima(self):
        return self.db.one("SELECT * FROM interval_marks ORDER BY id DESC LIMIT 1")

    def _crear_contextual(self, source: str) -> int:
        self.assertTrue(self.intervalos.handle("/marca_contexto", source, "/marca_contexto"))
        return int(self._ultima()["id"])

    def _elegir(self, categoria: str, mark_id: int) -> None:
        self.assertTrue(
            self.intervalos.handle(
                "/contexto", f"choice-{categoria}-{mark_id}",
                f"/contexto {categoria} {mark_id}",
            )
        )

    def test_marca_normal_permanece_rapida_y_sin_contexto(self) -> None:
        self.assertTrue(self.intervalos.handle("/marca", "normal-1", "/marca"))

        mark = self._ultima()
        self.assertIsNotNone(mark)
        self.assertIsNone(mark["context_category"])
        self.assertIsNone(mark["context_text"])
        self.assertIsNone(self.db.get_state(CONTEXTO_PENDIENTE_KEY))

    def test_marca_contextual_se_persiste_antes_de_elegir(self) -> None:
        mark_id = self._crear_contextual("contextual-1")

        mark = self._ultima()
        self.assertEqual(mark_id, mark["id"])
        self.assertIsNotNone(mark["marked_at_utc"])
        self.assertEqual(
            {"mark_id": mark_id, "mode": "eleccion"},
            self.db.get_state(CONTEXTO_PENDIENTE_KEY),
        )

    def test_cada_categoria_directa_se_guarda_en_la_marca_original(self) -> None:
        for categoria in (
            "estres",
            "urgencia",
            "sueno_cansancio",
            "aburrimiento",
            "senal",
        ):
            with self.subTest(categoria=categoria):
                mark_id = self._crear_contextual(f"directa-{categoria}")
                self._elegir(categoria, mark_id)
                mark = self.db.one("SELECT * FROM interval_marks WHERE id = ?", (mark_id,))
                self.assertEqual(categoria, mark["context_category"])
                self.assertIsNone(mark["context_text"])
                self.assertIsNone(self.db.get_state(CONTEXTO_PENDIENTE_KEY))

    def test_otro_guarda_texto_libre_y_no_otra_marca(self) -> None:
        primera = self._crear_contextual("otro-primera")
        self._elegir("otro", primera)
        self.assertTrue(self.intervalos.handle_text("Discusión al llegar a casa"))

        segunda = self._crear_contextual("otro-segunda")
        mark_primera = self.db.one("SELECT * FROM interval_marks WHERE id = ?", (primera,))
        mark_segunda = self.db.one("SELECT * FROM interval_marks WHERE id = ?", (segunda,))
        self.assertEqual("otro", mark_primera["context_category"])
        self.assertEqual("Discusión al llegar a casa", mark_primera["context_text"])
        self.assertIsNone(mark_segunda["context_category"])

    def test_sin_contexto_y_abandono_conservan_la_marca(self) -> None:
        sin_contexto = self._crear_contextual("sin-contexto")
        self._elegir("sin", sin_contexto)
        mark = self.db.one("SELECT * FROM interval_marks WHERE id = ?", (sin_contexto,))
        self.assertIsNone(mark["context_category"])

        abandonada = self._crear_contextual("abandono")
        self.intervalos.abandon_contexto()
        mark = self.db.one("SELECT * FROM interval_marks WHERE id = ?", (abandonada,))
        self.assertIsNotNone(mark)
        self.assertIsNone(mark["context_category"])

    def test_boton_viejo_no_puede_escribir_sobre_otra_marca(self) -> None:
        anterior = self._crear_contextual("anterior")
        actual = self._crear_contextual("actual")

        self._elegir("estres", anterior)
        self.assertIsNone(
            self.db.one("SELECT context_category FROM interval_marks WHERE id = ?", (anterior,))["context_category"]
        )
        self._elegir("urgencia", actual)
        self.assertEqual(
            "urgencia",
            self.db.one("SELECT context_category FROM interval_marks WHERE id = ?", (actual,))["context_category"],
        )

    def test_marcas_historicas_sin_contexto_siguen_siendo_validas(self) -> None:
        with self.db.transaction():
            self.db.execute(
                """
                INSERT INTO interval_marks(user_id, marked_at_utc, local_day, request_id)
                VALUES (?, ?, ?, ?)
                """,
                ("100", "2026-01-01T00:00:00+00:00", "2025-12-31", "historica"),
            )
        mark = self._ultima()
        self.assertIsNone(mark["context_category"])
        self.assertIsNone(mark["context_text"])

    def test_migracion_agrega_contexto_a_una_tabla_legacy_sin_tocar_su_marca(self) -> None:
        legacy = Database(Path(":memory:"), ROOT / "schema.sql")
        legacy.connection.executescript(
            """
            CREATE TABLE interval_marks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                marked_at_utc TEXT NOT NULL,
                local_day TEXT NOT NULL,
                request_id TEXT NOT NULL UNIQUE
            );
            INSERT INTO interval_marks(user_id, marked_at_utc, local_day, request_id)
            VALUES ('100', '2026-01-01T00:00:00+00:00', '2025-12-31', 'legacy-mark');
            """
        )
        try:
            legacy.migrate()
            mark = legacy.one("SELECT * FROM interval_marks WHERE request_id = ?", ("legacy-mark",))
            self.assertIsNotNone(mark)
            self.assertIsNone(mark["context_category"])
            self.assertIsNone(mark["context_text"])
        finally:
            legacy.close()

    def test_cierre_diario_solo_anota_total_de_contextos(self) -> None:
        primero = self._crear_contextual("diario-1")
        self._elegir("estres", primero)
        segundo = self._crear_contextual("diario-2")
        self._elegir("otro", segundo)
        self.assertTrue(self.intervalos.handle_text("Casa"))

        system = SystemModule(self.config, self.db, privacy=None)
        system._registro_ruta = lambda: self.log_path
        system._anotar(now_local().strftime("%d/%m/%Y"), [[0, ESPERA_MINUTOS]])

        texto = self.log_path.read_text(encoding="utf-8")
        self.assertIn("--------------------------------", texto)
        self.assertIn("contextos voluntarios: 2", texto)
        self.assertNotIn("estres", texto)
        self.assertNotIn("Casa", texto)

    def test_router_abandona_otro_antes_de_procesar_un_slash(self) -> None:
        mark_id = self._crear_contextual("router")
        self._elegir("otro", mark_id)

        class Stub:
            def handle_command(self, *_args):
                return False

        class PanelStub(Stub):
            def olvidar_todo(self):
                pass

        class RouterConfig:
            def is_owner(self, chat_id):
                return chat_id == "100"

            def lite_user(self, _chat_id):
                return None

        modules = {
            "panel": PanelStub(),
            "intervalos": self.intervalos,
            "vigia": Stub(),
            "timer": Stub(),
            "system": Stub(),
            "pomodoro": Stub(),
            "gmail": Stub(),
            "guardian": Stub(),
        }
        router = Router(RouterConfig(), self.db, telegram=Stub(), modules=modules)
        router._process_message(
            {"chat": {"id": "100"}, "from": {"id": "100"}, "text": "/estado"}
        )
        self.assertIsNone(self.db.get_state(CONTEXTO_PENDIENTE_KEY))

    def test_no_cambia_el_aviso_y_el_modulo_no_usa_ia(self) -> None:
        self.assertEqual((0, 150, 180, 420), MOMENTOS_AVISO)
        source = (ROOT / "modules" / "intervalos.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("gemini", source)
        self.assertNotIn("vision", source)
        self.assertIn("/marca_contexto", " ".join(data for row in messages.PANEL_INTERVALOS_BOTONES for _, data in row))


if __name__ == "__main__":
    unittest.main()
