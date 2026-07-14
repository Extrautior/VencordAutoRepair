import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class NoiseToggleBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.patcher = self.root / "patcher.js"
        self.settings = self.root / "settings.json"
        self.settings.write_text("{}", encoding="utf-8")

    def bridge_patches(self):
        return (
            patch.object(main, "vencord_patcher_path", return_value=self.patcher),
            patch.object(main, "noise_toggle_settings_path", return_value=self.settings),
        )

    def test_current_bridge_is_detected_exactly(self):
        self.patcher.write_text(
            "vencord();\n\n" + main.NOISETOGGLE_VENCORD_PATCH_SOURCE.strip() + "\n",
            encoding="utf-8",
        )
        patcher_patch, settings_patch = self.bridge_patches()
        with patcher_patch, settings_patch:
            self.assertTrue(main.is_noise_toggle_bridge_installed())

    def test_outdated_or_duplicate_bridge_is_not_current(self):
        old_bridge = main.NOISETOGGLE_VENCORD_PATCH_SOURCE.replace(
            main.NOISETOGGLE_BRIDGE_VERSION,
            "/* NoiseToggleBridge VERSION 1 */",
        ).strip()
        self.patcher.write_text(old_bridge + "\n" + old_bridge + "\n", encoding="utf-8")
        patcher_patch, settings_patch = self.bridge_patches()
        with patcher_patch, settings_patch:
            self.assertFalse(main.is_noise_toggle_bridge_installed())

    def test_install_replaces_all_old_blocks_and_preserves_clean_backup(self):
        old_bridge = main.NOISETOGGLE_VENCORD_PATCH_SOURCE.replace(
            main.NOISETOGGLE_BRIDGE_VERSION,
            "/* NoiseToggleBridge VERSION 1 */",
        ).strip()
        self.patcher.write_text(
            "vencordStart();\n" + old_bridge + "\nvencordEnd();\n" + old_bridge + "\n",
            encoding="utf-8",
        )
        patcher_patch, settings_patch = self.bridge_patches()
        with patcher_patch, settings_patch:
            self.assertTrue(main.install_noise_toggle_bridge())
            self.assertTrue(main.is_noise_toggle_bridge_installed())

        content = self.patcher.read_text(encoding="utf-8")
        self.assertEqual(content.count(main.NOISETOGGLE_BRIDGE_BEGIN), 1)
        self.assertEqual(content.count(main.NOISETOGGLE_BRIDGE_END), 1)
        backup = self.patcher.with_suffix(".js.noisetoggle.bak")
        backup_content = backup.read_text(encoding="utf-8")
        self.assertNotIn(main.NOISETOGGLE_BRIDGE_BEGIN, backup_content)
        self.assertIn("vencordStart();", backup_content)
        self.assertIn("vencordEnd();", backup_content)


class StreamBoostRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.assets = self.root / "assets" / "streamboost"
        self.asset_dist = self.assets / "dist"
        self.target_root = self.root / "installed-streamboost"
        self.target_dist = self.root / "installed-dist"
        self.asset_dist.mkdir(parents=True)
        self.target_root.mkdir(parents=True)
        self.target_dist.mkdir(parents=True)

        (self.assets / "streamboost_hook.node").write_bytes(b"native-addon-v1")
        for name in main.STREAMBOOST_DIST_FILES:
            (self.asset_dist / name).write_text(f"streamboost-{name}\n", encoding="utf-8")

    def streamboost_patches(self):
        return (
            patch.object(main, "base_dir", return_value=self.root),
            patch.object(main, "vencord_dist_path", return_value=self.target_dist),
            patch.object(main, "streamboost_target_path", return_value=self.target_root),
        )

    def test_current_bundle_allows_noise_toggle_block_in_patcher(self):
        (self.target_root / "streamboost_hook.node").write_bytes(b"native-addon-v1")
        for name in main.STREAMBOOST_DIST_FILES:
            source = (self.asset_dist / name).read_text(encoding="utf-8")
            if name == "patcher.js":
                source += "\n" + main.NOISETOGGLE_VENCORD_PATCH_SOURCE.strip() + "\n"
            (self.target_dist / name).write_text(source, encoding="utf-8")

        base_patch, dist_patch, target_patch = self.streamboost_patches()
        with base_patch, dist_patch, target_patch:
            self.assertTrue(main.is_streamboost_direct_installed())

    def test_install_replaces_stale_bundle_and_creates_clean_backup(self):
        for name in main.STREAMBOOST_DIST_FILES:
            (self.target_dist / name).write_text("old\n", encoding="utf-8")

        base_patch, dist_patch, target_patch = self.streamboost_patches()
        with base_patch, dist_patch, target_patch:
            self.assertTrue(main.install_streamboost_direct())
            self.assertTrue(main.is_streamboost_direct_installed())

        self.assertEqual((self.target_root / "streamboost_hook.node").read_bytes(), b"native-addon-v1")
        self.assertEqual(
            (self.target_root / "backup" / "dist" / "preload.js").read_text(encoding="utf-8"),
            "old\n",
        )


class RuntimeBehaviorTests(unittest.TestCase):
    def test_noise_toggle_repair_is_optional_and_enabled_by_default(self):
        settings = main.default_settings()
        self.assertTrue(settings["repair_noise_toggle_bridge"])
        self.assertTrue(settings["restart_discord_after_noise_toggle_bridge"])
        self.assertTrue(settings["repair_streamboost_direct"])
        self.assertTrue(settings["restart_discord_after_streamboost_direct"])

    def test_updater_completion_messages_are_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "discord_updater_rCURRENT.log"
            log_path.write_text("Already up to date. Nothing to do\n", encoding="utf-8")
            self.assertTrue(main.updater_log_signals_done(log_path))

            log_path.write_text("Checking for updates\n", encoding="utf-8")
            self.assertFalse(main.updater_log_signals_done(log_path))

    def test_linux_install_roots_include_regular_and_flatpak_layouts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            regular = root / "discord"
            (regular / "resources").mkdir(parents=True)
            self.assertEqual(main.resolve_linux_discord_root(regular), regular)

            flatpak = root / "com.discordapp.Discord"
            resolved = flatpak / "current" / "active" / "files" / "discord"
            (resolved / "resources").mkdir(parents=True)
            self.assertEqual(main.resolve_linux_discord_root(flatpak), resolved)


if __name__ == "__main__":
    unittest.main()
