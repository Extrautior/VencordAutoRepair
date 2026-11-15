from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import startup_manager


class TaskDefinitionTests(unittest.TestCase):
    def test_com_dispatch_error_uses_nested_task_scheduler_hresult(self):
        error = RuntimeError(
            -2147352567,
            "Exception occurred.",
            (0, "System", "The system cannot find the file specified.", None, 0, -2147024894),
            None,
        )
        self.assertEqual(startup_manager._com_error_code(error), 0x80070002)

    @unittest.skipUnless(os.name == "nt", "Windows scheduled task XML is Windows-specific")
    def test_task_is_per_user_interactive_least_privilege_and_bounded(self):
        command = [r"C:\Program Files\App\app.exe", "--run-once", "--startup"]
        working_directory = Path(r"C:\Program Files\App")
        xml = startup_manager._task_xml(
            command,
            working_directory,
            user_id="S-1-5-21-1000",
            name="VencordAutoRepair-S-1-5-21-1000",
        )

        self.assertIn("<URI>\\VencordAutoRepair-S-1-5-21-1000</URI>", xml)
        self.assertIn("<LogonType>InteractiveToken</LogonType>", xml)
        self.assertIn("<RunLevel>LeastPrivilege</RunLevel>", xml)
        self.assertIn("<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>", xml)
        self.assertIn("<Delay>PT30S</Delay>", xml)
        self.assertIn("<ExecutionTimeLimit>PT20M</ExecutionTimeLimit>", xml)
        self.assertIn(
            "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>", xml
        )
        self.assertIn("<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>", xml)
        self.assertIn("--run-once --startup", xml)
        self.assertNotIn("HighestAvailable", xml)
        self.assertNotIn("--refresh-startup", xml)

    @unittest.skipUnless(os.name == "nt", "Task Scheduler names are Windows-specific")
    def test_task_name_contains_current_user_sid(self):
        with patch.object(
            startup_manager,
            "_current_user_identifier",
            return_value="S-1-5-21-2000",
        ):
            self.assertEqual(
                startup_manager.task_name(),
                "VencordAutoRepair-S-1-5-21-2000",
            )

    def test_source_startup_command_is_a_bounded_one_shot(self):
        with patch.object(sys, "frozen", False, create=True):
            command, working_directory = startup_manager.startup_command()
        self.assertEqual(command[-2:], ["--run-once", "--startup"])
        self.assertTrue(any(str(part).endswith("app.py") for part in command))
        self.assertEqual(working_directory, Path(startup_manager.__file__).resolve().parent)
        self.assertNotIn("--enable-startup", command)
        self.assertNotIn("--refresh-startup", command)

    def test_linux_desktop_entry_quotes_paths_and_uses_one_shot(self):
        working_directory = Path("/opt/Vencord Auto Repair")
        entry = startup_manager._desktop_entry(
            [
                "/opt/Vencord Auto Repair/python3",
                "/opt/Vencord Auto Repair/app.py",
                "--run-once",
                "--startup",
            ],
            working_directory,
        )
        self.assertIn('Exec="/opt/Vencord Auto Repair/python3"', entry)
        self.assertIn('"/opt/Vencord Auto Repair/app.py" "--run-once" "--startup"', entry)
        self.assertIn(f"Path={working_directory}", entry)
        self.assertIn("X-GNOME-Autostart-enabled=true", entry)

    @unittest.skipUnless(os.name == "nt", "Frozen executable layout is Windows-specific")
    def test_frozen_manager_targets_sibling_app_executable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            app_exe = root / "app.exe"
            manager_exe = root / "startup_manager.exe"
            app_exe.write_bytes(b"")
            manager_exe.write_bytes(b"")
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(manager_exe)),
            ):
                command, working_directory = startup_manager.startup_command()
        self.assertEqual(command, [str(app_exe.resolve()), "--run-once", "--startup"])
        self.assertEqual(working_directory, root)


@unittest.skipUnless(os.name == "nt", "Windows registration tests")
class WindowsRegistrationTests(unittest.TestCase):
    def test_scheduler_success_removes_legacy_only_after_registration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy = root / "VencordAutoRepair.lnk"
            legacy.write_bytes(b"legacy")

            with (
                patch.object(
                    startup_manager,
                    "startup_command",
                    return_value=([r"C:\App\app.exe", "--run-once", "--startup"], root),
                ),
                patch.object(
                    startup_manager,
                    "_current_user_identifier",
                    return_value="S-1-5-21-3000",
                ),
                patch.object(startup_manager, "legacy_shortcut_path", return_value=legacy),
                patch("app_runtime.migrate_legacy") as migrate,
                patch.object(startup_manager, "_register_scheduled_task") as register,
                patch.object(startup_manager, "_delete_run_entry") as delete_run,
            ):
                result = startup_manager.add_to_startup()

            self.assertTrue(result["success"])
            self.assertEqual(result["backend"], "task_scheduler")
            self.assertEqual(result["task_name"], "VencordAutoRepair-S-1-5-21-3000")
            self.assertTrue(result["legacy_removed"])
            self.assertFalse(legacy.exists())
            migrate.assert_called_once_with()
            register.assert_called_once()
            delete_run.assert_called_once_with()

    def test_scheduler_rejection_falls_back_to_hkcu_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy = root / "VencordAutoRepair.lnk"
            legacy.write_bytes(b"legacy")
            with (
                patch.object(
                    startup_manager,
                    "startup_command",
                    return_value=([r"C:\App\app.exe", "--run-once", "--startup"], root),
                ),
                patch.object(
                    startup_manager,
                    "_current_user_identifier",
                    return_value="S-1-5-21-3000",
                ),
                patch.object(startup_manager, "legacy_shortcut_path", return_value=legacy),
                patch("app_runtime.migrate_legacy"),
                patch.object(
                    startup_manager,
                    "_register_scheduled_task",
                    side_effect=PermissionError("scheduler denied"),
                ),
                patch.object(startup_manager, "_register_run_entry") as register_run,
            ):
                result = startup_manager.add_to_startup()
            self.assertEqual(result["backend"], "registry")
            self.assertEqual(result["run_value"], "VencordAutoRepair")
            self.assertIn("scheduler denied", result["scheduler_error"])
            self.assertFalse(legacy.exists())
            register_run.assert_called_once()

    def test_failed_backends_preserve_legacy_shortcut(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy = root / "VencordAutoRepair.lnk"
            legacy.write_bytes(b"legacy")
            with (
                patch.object(
                    startup_manager,
                    "startup_command",
                    return_value=([r"C:\App\app.exe", "--run-once", "--startup"], root),
                ),
                patch.object(
                    startup_manager,
                    "_current_user_identifier",
                    return_value="S-1-5-21-3000",
                ),
                patch.object(startup_manager, "legacy_shortcut_path", return_value=legacy),
                patch("app_runtime.migrate_legacy"),
                patch.object(
                    startup_manager,
                    "_register_scheduled_task",
                    side_effect=PermissionError("scheduler denied"),
                ),
                patch.object(
                    startup_manager,
                    "_register_run_entry",
                    side_effect=PermissionError("registry denied"),
                ),
            ):
                with self.assertRaises(startup_manager.StartupRegistrationError):
                    startup_manager.add_to_startup()
            self.assertTrue(legacy.exists())


class RefreshTests(unittest.TestCase):
    def test_refresh_is_noop_when_startup_is_disabled(self):
        with (
            patch.object(
                startup_manager,
                "startup_status",
                return_value={"enabled": False, "backend": "none"},
            ),
            patch.object(startup_manager, "add_to_startup") as add,
        ):
            result = startup_manager.refresh_startup()
        self.assertFalse(result["refreshed"])
        add.assert_not_called()

    def test_refresh_re_registers_enabled_legacy_startup(self):
        with (
            patch.object(
                startup_manager,
                "startup_status",
                return_value={"enabled": True, "backend": "legacy_shortcut"},
            ),
            patch.object(
                startup_manager,
                "add_to_startup",
                return_value={"success": True, "backend": "task_scheduler"},
            ) as add,
        ):
            result = startup_manager.refresh_startup()
        self.assertTrue(result["refreshed"])
        self.assertEqual(result["previous_backend"], "legacy_shortcut")
        add.assert_called_once_with()

    def test_removal_is_clean_when_scheduler_task_is_already_absent(self):
        if os.name != "nt":
            self.skipTest("Windows registration cleanup test")
        with (
            patch.object(startup_manager, "_delete_scheduled_task", return_value=False),
            patch.object(startup_manager, "_delete_run_entry", return_value=False),
            patch.object(startup_manager, "_remove_legacy_shortcut", return_value=False),
            patch.object(startup_manager, "is_enabled", return_value=False),
        ):
            result = startup_manager.remove_from_startup()
        self.assertTrue(result["success"])
        self.assertFalse(result["enabled"])


@unittest.skipIf(os.name == "nt", "Linux desktop autostart tests")
class LinuxAutostartTests(unittest.TestCase):
    def test_desktop_entry_round_trips_only_in_temp_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "autostart" / "vencord-auto-repair.desktop"
            with patch.object(startup_manager, "_autostart_path", return_value=path):
                result = startup_manager.add_to_startup()
                self.assertEqual(result["backend"], "desktop")
                self.assertTrue(startup_manager.is_enabled())
                content = path.read_text(encoding="utf-8")
                self.assertIn("X-GNOME-Autostart-enabled=true", content)
                self.assertIn('"--run-once" "--startup"', content)
                startup_manager.remove_from_startup()
                self.assertFalse(startup_manager.is_enabled())


if __name__ == "__main__":
    unittest.main()
