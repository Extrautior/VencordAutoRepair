"""A concurrent GUI save must survive completion of an older repair pass."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import main


class SettingsPreservationTests(unittest.TestCase):
    def test_repair_does_not_overwrite_settings_saved_during_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            state = Path(directory) / "state.json"
            settings.write_text(json.dumps({"watched_branches": ["stable"]}))
            updated = {"watched_branches": ["canary"], "repair_noise_toggle_bridge": False}
            def gui_save(*_args):
                settings.write_text(json.dumps(updated))
                return False
            with (patch.object(main, "settings_path", return_value=settings),
                  patch.object(main, "state_path", return_value=state),
                  patch.object(main, "discover_installs", return_value=[Mock(branch="stable")]),
                  patch.object(main, "process_install", side_effect=gui_save),
                  patch.object(main.sys, "argv", ["main.py"])):
                self.assertEqual(main.main(), 0)
            self.assertEqual(json.loads(settings.read_text()), updated)
