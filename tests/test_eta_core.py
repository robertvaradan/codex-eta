import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "eta" / "src"))
from eta_core import EtaStore, category, remaining_seconds, require_event


class EtaTests(unittest.TestCase):
    def test_turn_lifecycle_and_learning(self):
        with tempfile.TemporaryDirectory() as folder:
            store = EtaStore(Path(folder) / "eta.sqlite3")
            event = {"hook_event_name": "UserPromptSubmit", "session_id": "s", "turn_id": "t",
                     "model": "test-model", "prompt": "Fix a bug"}
            store.start(require_event(event), now=1000)
            first = store.current(now=1020)
            self.assertEqual(first["category"], "code")
            self.assertEqual(first["samples"], 0)
            self.assertGreater(first["remaining"], 0)
            store.finish({**event, "hook_event_name": "Stop"}, "completed", now=1100)
            self.assertIsNone(store.current(now=1101))
            store.start({**event, "turn_id": "t2"}, now=1200)
            second = store.current(now=1201)
            self.assertEqual(second["samples"], 1)
            self.assertLess(second["remaining"], first["remaining"])

    def test_censored_estimate_updates_live(self):
        initial = remaining_seconds(0, [], 75)
        late = remaining_seconds(500, [], 75)
        self.assertEqual(round(initial), 75)
        self.assertGreater(late, 0)

    def test_invalid_hook_input_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "turn_id"):
            require_event({"hook_event_name": "Stop", "session_id": "s", "model": "m"})

    def test_categories(self):
        self.assertEqual(category("Publish the whole project"), "large")
        self.assertEqual(category("Research options"), "research")


if __name__ == "__main__":
    unittest.main()

