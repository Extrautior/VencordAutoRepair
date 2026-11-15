from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import app_runtime


class RuntimePathTests(unittest.TestCase):
    def test_windows_data_dir_uses_local_appdata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            expected = Path(temp_dir) / "VencordAutoRepair"
            self.assertEqual(
                app_runtime.data_dir(
                    platform_name="win32",
                    environ={"LOCALAPPDATA": temp_dir},
                ),
                expected,
            )

    def test_linux_data_dir_honors_xdg_data_home(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(
                app_runtime.data_dir(
                    platform_name="linux",
                    environ={"XDG_DATA_HOME": temp_dir},
                ),
                Path(temp_dir) / "VencordAutoRepair",
            )

    def test_linux_data_dir_uses_xdg_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(
                app_runtime.data_dir(
                    platform_name="linux",
                    environ={"HOME": temp_dir},
                ),
                Path(temp_dir) / ".local" / "share" / "VencordAutoRepair",
            )


class AtomicJsonTests(unittest.TestCase):
    def test_atomic_write_json_replaces_complete_file_without_temp_leftovers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "nested" / "settings.json"
            app_runtime.atomic_write_json(path, {"branches": ["stable"], "ok": True})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"branches": ["stable"], "ok": True},
            )
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_serialization_failure_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            path.write_text('{"old": true}\n', encoding="utf-8")
            with self.assertRaises(TypeError):
                app_runtime.atomic_write_json(path, {"bad": object()})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"old": True})
            self.assertEqual(list(path.parent.glob("*.tmp")), [])


class MigrationTests(unittest.TestCase):
    def test_migrates_settings_state_and_rewrites_only_default_installer_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy = root / "legacy"
            target = root / "data"
            legacy.mkdir()
            app_runtime.atomic_write_json(
                legacy / "settings.json",
                {
                    "installer_path": str(legacy / "VencordInstallerCli.exe"),
                    "watched_branches": ["stable"],
                },
            )
            app_runtime.atomic_write_json(
                legacy / "state.json",
                {"last_seen_versions": {"stable": "app-1.0.0"}},
            )

            migrated = app_runtime.migrate_legacy([legacy], destination=target)

            self.assertEqual(len(migrated), 2)
            settings = json.loads((target / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(
                settings["installer_path"],
                str(target / "downloads" / "VencordInstallerCli.exe"),
            )
            self.assertEqual(settings["watched_branches"], ["stable"])
            self.assertTrue((legacy / "settings.json").exists())
            self.assertTrue((legacy / "state.json").exists())

    def test_custom_installer_path_and_newer_target_file_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy = root / "legacy"
            target = root / "data"
            legacy.mkdir()
            target.mkdir()
            custom = root / "tools" / "VencordInstallerCli.exe"
            app_runtime.atomic_write_json(
                legacy / "settings.json",
                {"installer_path": str(custom), "watched_branches": ["ptb"]},
            )
            app_runtime.atomic_write_json(
                legacy / "state.json",
                {"last_seen_versions": {"stable": "old"}},
            )
            app_runtime.atomic_write_json(
                target / "state.json",
                {"last_seen_versions": {"stable": "new"}},
            )

            app_runtime.migrate_legacy([legacy], destination=target)

            settings = json.loads((target / "settings.json").read_text(encoding="utf-8"))
            state = json.loads((target / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(settings["installer_path"], str(custom))
            self.assertEqual(state["last_seen_versions"]["stable"], "new")

    @unittest.skipUnless(os.name == "nt", "WScript.Shell shortcut discovery is Windows-only")
    def test_legacy_shortcut_target_directory_is_discovered(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_app = root / "old-app"
            old_app.mkdir()
            (old_app / "settings.json").write_text("{}", encoding="utf-8")
            shortcut = root / "VencordAutoRepair.lnk"
            shortcut.write_bytes(b"test")

            link = types.SimpleNamespace(
                TargetPath=sys.executable,
                Arguments=f'"{old_app / "main.py"}"',
            )
            shell = types.SimpleNamespace(CreateShortcut=lambda _path: link)
            pythoncom = types.ModuleType("pythoncom")
            pythoncom.CoInitialize = lambda: None
            pythoncom.CoUninitialize = lambda: None
            win32com = types.ModuleType("win32com")
            win32client = types.ModuleType("win32com.client")
            win32client.Dispatch = lambda _name: shell
            win32com.client = win32client

            with (
                patch.object(app_runtime, "_legacy_shortcut_path", return_value=shortcut),
                patch.dict(
                    sys.modules,
                    {
                        "pythoncom": pythoncom,
                        "win32com": win32com,
                        "win32com.client": win32client,
                    },
                ),
            ):
                directories = app_runtime._shortcut_application_dirs()

            self.assertEqual(directories, [old_app.resolve()])


class ProcessLockTests(unittest.TestCase):
    def test_lock_is_exclusive_across_processes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            environment = os.environ.copy()
            environment["XDG_DATA_HOME"] = temp_dir
            code = (
                "import time, app_runtime; "
                "lock = app_runtime.process_lock(); lock.__enter__(); "
                "print('locked', flush=True); time.sleep(10)"
            )
            child = subprocess.Popen(
                [sys.executable, "-c", code],
                cwd=str(Path(__file__).resolve().parents[1]),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                assert child.stdout is not None
                ready = child.stdout.readline().strip()
                self.assertEqual(ready, "locked")
                with patch.dict(os.environ, {"XDG_DATA_HOME": temp_dir}):
                    with self.assertRaises(app_runtime.ProcessLockBusy):
                        with app_runtime.process_lock():
                            pass
            finally:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
                if child.stdout is not None:
                    child.stdout.close()
                if child.stderr is not None:
                    child.stderr.close()


class ResultAndLoggingTests(unittest.TestCase):
    def test_last_result_round_trips_and_invalid_json_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            with patch.object(app_runtime, "data_dir", return_value=data_dir):
                stored = app_runtime.write_result({"status": "success", "success": True})
                self.assertEqual(app_runtime.read_result(), stored)
                app_runtime.result_path().write_text("{", encoding="utf-8")
                self.assertIsNone(app_runtime.read_result())

    def test_configure_logging_installs_rotating_file_handler(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(app_runtime, "data_dir", return_value=Path(temp_dir)):
                path = app_runtime.configure_logging(console=False)
                root_handlers = __import__("logging").getLogger().handlers
                runtime_handlers = [
                    handler
                    for handler in root_handlers
                    if getattr(handler, "_vencord_runtime_handler", False)
                ]
                self.assertTrue(path.parent.exists())
                self.assertEqual(len(runtime_handlers), 1)
                self.assertTrue(hasattr(runtime_handlers[0], "doRollover"))
                for handler in runtime_handlers:
                    __import__("logging").getLogger().removeHandler(handler)
                    handler.close()


class AppEntryTests(unittest.TestCase):
    def test_default_entry_uses_gui(self):
        with (
            patch.object(app_runtime, "configure_logging"),
            patch.object(app, "_show_gui", return_value=0) as show_gui,
            patch.object(app, "_run_repair") as run_repair,
        ):
            self.assertEqual(app.main([]), 0)
        show_gui.assert_called_once_with()
        run_repair.assert_not_called()

    def test_run_once_passes_only_sanitized_repair_flags_and_records_success(self):
        observed: list[list[str]] = []

        def repair_main() -> int:
            observed.append(list(sys.argv))
            return 0

        fake_main = types.SimpleNamespace(main=repair_main, SCRIPT_VERSION="0.4.0")
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(app_runtime, "data_dir", return_value=Path(temp_dir)),
                patch.object(app_runtime, "configure_logging"),
                patch.object(app_runtime, "process_lock", return_value=contextlib.nullcontext()),
                patch.object(app_runtime, "migrate_legacy") as migrate,
                patch.dict(sys.modules, {"main": fake_main}),
                patch.object(sys, "stdout", io.StringIO()),
                patch.object(sys, "stderr", io.StringIO()),
            ):
                self.assertEqual(
                    app._run_repair(
                        ["--run-once", "--startup", "--gui-only", "--force", "--startup"]
                    ),
                    0,
                )
                self.assertEqual(sys.stdout.getvalue(), "")
                self.assertEqual(sys.stderr.getvalue(), "")
                result = app_runtime.read_result()

        migrate.assert_called_once_with()
        self.assertEqual(observed[0][1:], ["--run-once", "--startup", "--force"])
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["success"])
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["message"], "Repair completed successfully.")

    def test_lock_busy_does_not_overwrite_active_result(self):
        @contextlib.contextmanager
        def busy():
            raise app_runtime.ProcessLockBusy("busy")
            yield

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(app_runtime, "data_dir", return_value=Path(temp_dir)),
                patch.object(app_runtime, "configure_logging"),
                patch.object(app_runtime, "process_lock", side_effect=busy),
            ):
                active = app_runtime.write_result(
                    {
                        "status": "running",
                        "success": None,
                        "message": "The first process is still repairing.",
                    }
                )
                self.assertEqual(app._run_repair(["--run-once"]), 0)
                result = app_runtime.read_result()
        self.assertEqual(result, active)

    def test_gui_migrates_before_gui_module_reads_settings(self):
        order: list[str] = []
        fake_gui = types.ModuleType("gui")

        def show_gui() -> int:
            order.append("gui")
            return 0

        fake_gui.show_gui = show_gui

        def migrate() -> list[Path]:
            order.append("migrate")
            return []

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(app_runtime, "data_dir", return_value=Path(temp_dir)),
                patch.object(app_runtime, "process_lock", return_value=contextlib.nullcontext()),
                patch.object(app_runtime, "migrate_legacy", side_effect=migrate),
                patch.dict(sys.modules, {"gui": fake_gui}),
            ):
                self.assertEqual(app._show_gui(), 0)
        self.assertEqual(order, ["migrate", "gui"])

    def test_diagnostics_are_written_even_without_stdout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(app_runtime, "data_dir", return_value=Path(temp_dir)),
                patch.object(app, "_version", return_value="0.4.0"),
                patch.object(
                    app,
                    "_diagnostics_payload",
                    return_value={"version": "0.4.0", "safe": True},
                ),
                patch.object(sys, "stdout", None),
            ):
                self.assertEqual(app.main(["--diagnostics"]), 0)
            written = json.loads((Path(temp_dir) / "diagnostics.json").read_text(encoding="utf-8"))
        self.assertEqual(written, {"version": "0.4.0", "safe": True})

    def test_startup_control_writes_result_without_stdout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(app_runtime, "data_dir", return_value=Path(temp_dir)),
                patch.object(
                    app,
                    "_startup_action",
                    return_value={"success": True, "backend": "task_scheduler"},
                ),
                patch.object(sys, "stdout", None),
            ):
                self.assertEqual(app.main(["--refresh-startup"]), 0)
            written = json.loads(
                (Path(temp_dir) / "startup-result.json").read_text(encoding="utf-8")
            )
        self.assertEqual(written["backend"], "task_scheduler")


if __name__ == "__main__":
    unittest.main()
