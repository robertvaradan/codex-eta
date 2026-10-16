import contextlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "eta"
sys.path.insert(0, str(PLUGIN / "src"))
sys.path.insert(0, str(PLUGIN / "hooks"))
from eta_core import EtaStore, require_event
import eta_hook


def event(turn_id="t", kind="UserPromptSubmit", model="test-model"):
    return {"hook_event_name": kind, "session_id": "s", "turn_id": turn_id,
            "model": model, "prompt": "Implement the request"}


class EtaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.store = EtaStore(self.folder / "eta.sqlite3")

    def test_no_agent_estimate_means_explicit_waiting(self):
        self.store.start(event(), now=1000)
        current = self.store.current(now=1100)
        self.assertEqual(current["status"], "waiting")
        self.assertIsNone(current["remaining"])

    def test_agent_revisions_replace_remaining_time_from_now(self):
        self.store.start(event(), now=1000)
        self.store.set_estimate("s", "t", 120, "code", now=1020)
        self.assertEqual(self.store.current(now=1050)["remaining"], 90)
        self.store.set_estimate("s", "t", 300, "code", now=1060)
        self.assertEqual(self.store.current(now=1070)["remaining"], 290)
        self.store.finish(event(kind="Stop"), "completed", now=1300)
        self.assertIsNone(self.store.current(now=1301))

    def test_expired_estimate_requires_agent_revision(self):
        self.store.start(event(), now=1000)
        self.store.set_estimate("s", "t", 20, "quick", now=1001)
        current = self.store.current(now=1040)
        self.assertEqual(current["status"], "overdue")
        self.assertEqual(current["remaining"], 0)
        self.store.set_estimate("s", "t", 30, "quick", now=1040)
        self.assertEqual(self.store.current(now=1041)["status"], "estimated")

    def test_calibration_pairs_actual_time_with_agent_prediction(self):
        self.store.start(event(), now=1000)
        self.store.set_estimate("s", "t", 100, "code", now=1010)
        self.store.finish(event(kind="Stop"), "completed", now=1210)
        self.store.start(event("next"), now=1300)
        result = self.store.set_estimate("s", "next", 100, "code", now=1310)
        self.assertEqual(result["samples"], 1)
        self.assertAlmostEqual(result["calibration_factor"], 2 ** (1 / 5))
        self.assertGreater(result["display_seconds"], 100)

    def test_revisions_do_not_give_one_turn_multiple_learning_votes(self):
        self.store.start(event(), now=1000)
        self.store.set_estimate("s", "t", 100, "code", now=1010)
        self.store.set_estimate("s", "t", 5, "code", now=1050)
        self.store.set_estimate("s", "t", 5, "code", now=1100)
        self.store.finish(event(kind="Stop"), "completed", now=1210)
        self.store.start(event("next"), now=1300)
        result = self.store.set_estimate("s", "next", 100, "code", now=1310)
        self.assertEqual(result["samples"], 1)
        self.assertAlmostEqual(result["calibration_factor"], 2 ** (1 / 5))

    def test_interrupts_do_not_train_calibration(self):
        self.store.start(event(), now=1000)
        self.store.set_estimate("s", "t", 100, "code", now=1010)
        self.store.finish(event(kind="Interrupt"), "interrupted", now=1210)
        self.store.start(event("next"), now=1300)
        result = self.store.set_estimate("s", "next", 100, "code", now=1310)
        self.assertEqual(result["samples"], 0)
        self.assertEqual(result["display_seconds"], 100)

    def test_calibration_does_not_mix_models_or_categories(self):
        self.store.start(event(), now=1000)
        self.store.set_estimate("s", "t", 100, "code", now=1010)
        self.store.finish(event(kind="Stop"), "completed", now=1210)
        self.store.start(event("other-model", model="other"), now=1300)
        result = self.store.set_estimate("s", "other-model", 100, "code", now=1310)
        self.assertEqual(result["samples"], 0)
        self.store.start(event("other-category"), now=1400)
        result = self.store.set_estimate("s", "other-category", 100, "research", now=1410)
        self.assertEqual(result["samples"], 0)

    def test_old_duration_only_history_cannot_invent_agent_predictions(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO turns VALUES ('s','old','test-model','code',1,5000,'completed')")
        self.store = EtaStore(self.store.path)
        self.store.start(event(), now=6000)
        result = self.store.set_estimate("s", "t", 90, "code", now=6010)
        self.assertEqual(result["display_seconds"], 90)
        self.assertEqual(result["samples"], 0)

    def test_missing_or_finished_turn_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "No active"):
            self.store.set_estimate("wrong", "t", 100, "code", now=1000)
        self.store.start(event(), now=1000)
        self.store.finish(event(kind="Stop"), "completed", now=1100)
        with self.assertRaisesRegex(ValueError, "No active"):
            self.store.set_estimate("s", "t", 100, "code", now=1200)

    def test_bad_estimates_are_rejected(self):
        self.store.start(event(), now=1000)
        for value in (0, -1, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.set_estimate("s", "t", value, "code", now=1010)
        with self.assertRaisesRegex(ValueError, "Category"):
            self.store.set_estimate("s", "t", 10, "unknown", now=1010)

    def test_reminders_are_throttled_and_fresh_reports_suppress_them(self):
        self.store.start(event(), now=1000)
        self.assertFalse(self.store.reminder_due("s", "t", now=1050))
        self.assertTrue(self.store.reminder_due("s", "t", now=1060))
        self.assertFalse(self.store.reminder_due("s", "t", now=1061))
        self.store.set_estimate("s", "t", 100, "code", now=1110)
        self.assertFalse(self.store.reminder_due("s", "t", now=1120))
        self.assertTrue(self.store.reminder_due("s", "t", now=1170))

    def test_hook_supplies_primary_agent_reporting_contract(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"PLUGIN_DATA": str(self.folder)}), \
             patch("sys.stdin", io.StringIO(json.dumps(event()))), \
             patch.object(eta_hook, "launch_window") as launch, contextlib.redirect_stdout(output):
            eta_hook.main()
        launch.assert_called_once_with(self.folder)
        payload = json.loads(output.getvalue())["hookSpecificOutput"]
        self.assertEqual(payload["hookEventName"], "UserPromptSubmit")
        self.assertIn("The primary agent determines the ETA", payload["additionalContext"])
        self.assertIn("eta_report.py", payload["additionalContext"])
        self.assertIn("--session-id 's' --turn-id 't'", payload["additionalContext"])

    def test_report_command_writes_a_real_estimate(self):
        self.store.start(event())
        result = subprocess.run([
            sys.executable, str(PLUGIN / "src" / "eta_report.py"),
            "--data-dir", str(self.folder), "--session-id", "s", "--turn-id", "t",
            "--remaining-seconds", "180", "--category", "code",
        ], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["agent_seconds"], 180)
        self.assertEqual(self.store.current()["status"], "estimated")

    def test_invalid_hook_input_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "turn_id"):
            require_event({"hook_event_name": "Stop", "session_id": "s", "model": "m"})


if __name__ == "__main__":
    unittest.main()
