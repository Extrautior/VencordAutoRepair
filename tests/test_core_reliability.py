import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import main


class UpdaterReliabilityTests(unittest.TestCase):
    def test_updater_wait_raises_when_timeout_expires(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            install = main.DiscordInstall(branch="stable", root_path=Path(temp_dir))
            with (
                patch.object(main.time, "time", side_effect=[0.0, 0.0, 1.0]),
                patch.object(main.time, "sleep"),
                patch.object(main, "is_update_exe_running", return_value=False),
                patch.object(main, "updater_log_signals_done", return_value=False),
            ):
                with self.assertRaisesRegex(TimeoutError, "did not settle"):
                    main.wait_for_update_completion(install, timeout_seconds=0.5)

    def test_updater_timeout_prevents_installer_and_patching(self):
        install = Mock(branch="stable", root_path=Path("C:/Discord"))
        install.latest_version.return_value = "app-1.0.0"
        install.is_vencord_patched.return_value = False
        install.has_plain_app_asar.return_value = False
        settings = {
            "repair_noise_toggle_bridge": False,
            "restart_discord_after_repair": True,
        }
        state = {"last_seen_versions": {}, "last_action": {}}

        with (
            patch.object(main, "is_update_exe_running", return_value=True),
            patch.object(
                main,
                "wait_for_update_completion",
                side_effect=TimeoutError("updater timeout"),
            ),
            patch.object(main, "ensure_installer") as ensure_installer,
            patch.object(main, "run_vencord_install") as run_install,
            patch.object(main, "run_vencord_repair") as run_repair,
        ):
            with self.assertRaisesRegex(TimeoutError, "updater timeout"):
                main.process_install(
                    install, settings, state, force=False, dry_run=False
                )

        ensure_installer.assert_not_called()
        run_install.assert_not_called()
        run_repair.assert_not_called()


class InstallerReliabilityTests(unittest.TestCase):
    def test_installer_commands_are_hidden_and_propagate_failure(self):
        install = Mock(branch="stable", root_path=Path("C:/Discord"))
        installer = Path("VencordInstallerCli.exe")
        completed = Mock(returncode=7, stdout=b"installer failed")
        expected_creationflags = (
            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )

        for function_name in ("run_vencord_repair", "run_vencord_install"):
            with self.subTest(function=function_name):
                with patch.object(main.subprocess, "run", return_value=completed) as run:
                    with self.assertRaisesRegex(RuntimeError, "code 7"):
                        getattr(main, function_name)(installer, install)

                _, kwargs = run.call_args
                self.assertEqual(kwargs["timeout"], 180)
                self.assertEqual(kwargs["stdout"], subprocess.PIPE)
                self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
                self.assertEqual(kwargs["creationflags"], expected_creationflags)
                if os.name == "nt":
                    self.assertNotEqual(kwargs["creationflags"], 0)


class DownloadReliabilityTests(unittest.TestCase):
    def test_download_replaces_target_without_leaving_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "downloads" / "VencordInstallerCli.exe"
            target.parent.mkdir(parents=True)
            response = Mock(content=b"complete installer")

            with patch.object(main.requests, "get", return_value=response):
                main.download_installer(target)

            self.assertEqual(target.read_bytes(), b"complete installer")
            self.assertEqual(list(target.parent.glob("*.download")), [])

    def test_download_error_keeps_old_target_and_removes_partial_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "downloads" / "VencordInstallerCli.exe"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"previous installer")
            temporary = target.with_suffix(target.suffix + ".download")
            response = Mock(content=b"partial installer")

            with (
                patch.object(main.requests, "get", return_value=response),
                patch.object(Path, "replace", side_effect=OSError("replace failed")),
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    main.download_installer(target)

            self.assertEqual(target.read_bytes(), b"previous installer")
            self.assertFalse(temporary.exists())
            self.assertEqual(list(target.parent.glob("*.download")), [])


class RepairOrchestrationTests(unittest.TestCase):
    def test_failure_in_any_branch_does_not_block_the_others(self):
        branches = ["stable", "ptb", "canary"]
        installs = [
            main.DiscordInstall(branch=branch, root_path=Path(branch))
            for branch in branches
        ]
        settings = main.default_settings()

        for failing_branch in branches:
            with self.subTest(failing_branch=failing_branch):
                processed = []

                def process(install, *_args, **_kwargs):
                    processed.append(install.branch)
                    if install.branch == failing_branch:
                        raise RuntimeError(f"simulated failure for {install.branch}")
                    return False

                with (
                    patch.object(main, "discover_installs", return_value=installs),
                    patch.object(main, "load_json", return_value=settings.copy()),
                    patch.object(
                        main,
                        "load_state",
                        return_value={"last_seen_versions": {}, "last_action": {}},
                    ),
                    patch.object(main, "save_json"),
                    patch.object(main.sys, "argv", ["main.py"]),
                    patch.object(main, "process_install", side_effect=process),
                    patch.object(main.logger, "exception") as log_exception,
                ):
                    result = main.main()

                self.assertEqual(result, 1)
                self.assertEqual(processed, branches)
                log_exception.assert_called_once()

    def test_restart_requires_discord_running_and_enabled_setting(self):
        cases = [
            ("repair", True, True, True),
            ("repair", False, True, False),
            ("repair", True, False, False),
            ("install", True, True, True),
            ("install", False, True, False),
            ("install", True, False, False),
        ]

        for action, was_running, restart_allowed, expected_restart in cases:
            with self.subTest(
                action=action,
                was_running=was_running,
                restart_allowed=restart_allowed,
            ):
                install = Mock(branch="stable", root_path=Path("C:/Discord"))
                install.latest_version.return_value = "app-1.0.0"
                install.is_vencord_patched.side_effect = [False, True]
                install.has_plain_app_asar.return_value = action == "install"
                settings = {
                    "repair_noise_toggle_bridge": False,
                    "restart_discord_after_repair": (
                        restart_allowed if action == "repair" else False
                    ),
                    "restart_discord_after_install": (
                        restart_allowed if action == "install" else False
                    ),
                    "restart_discord_after_noise_toggle_bridge": True,
                }
                state = {"last_seen_versions": {}, "last_action": {}}
                action_patch = (
                    patch.object(main, "run_vencord_install")
                    if action == "install"
                    else patch.object(main, "run_vencord_repair")
                )

                with (
                    patch.object(main, "maybe_prepare_update"),
                    patch.object(main, "ensure_installer", return_value=Path("installer.exe")),
                    patch.object(main, "is_running", return_value=was_running),
                    patch.object(main, "kill_discord"),
                    patch.object(main, "start_discord") as start_discord,
                    patch.object(main, "install_noise_toggle_bridge", return_value=False),
                    action_patch,
                ):
                    changed = main.process_install(
                        install, settings, state, force=False, dry_run=False
                    )

                self.assertTrue(changed)
                if expected_restart:
                    start_discord.assert_called_once_with(install)
                else:
                    start_discord.assert_not_called()


if __name__ == "__main__":
    unittest.main()
