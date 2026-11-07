import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from ai_engine.live_corner_report import build_live_corner_report, main


class LiveCornerReportTests(unittest.TestCase):
    def test_missing_database_report_is_safe_and_informative(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "missing.sqlite3"
            report = build_live_corner_report(database)
            self.assertFalse(report["audit"]["available"])
            self.assertFalse(report["backtest"]["available"])
            self.assertEqual(report["safety"]["api_requests"], 0)
            self.assertTrue(report["safety"]["read_only"])
            self.assertFalse(database.exists())

    def test_cli_json_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(["--db", str(Path(folder) / "missing.sqlite3"), "--json"])
            self.assertEqual(exit_code, 0)
            report = json.loads(output.getvalue())
            self.assertIn("audit", report)
            self.assertIn("backtest", report)
            self.assertFalse(report["safety"]["betting_signals_enabled"])

    def test_cli_human_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(["--db", str(Path(folder) / "missing.sqlite3")])
            self.assertEqual(exit_code, 0)
            self.assertIn("INFORME DE CÓRNERS EN VIVO", output.getvalue())
            self.assertIn("Solicitudes API: 0", output.getvalue())


if __name__ == "__main__":
    unittest.main()
