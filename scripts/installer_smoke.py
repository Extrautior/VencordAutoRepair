"""Exercise the real per-user installer without replacing an existing installation.

Uses isolated data paths and a temporary installation. Refuses existing new-style
startup registrations/product installations; leaves the user's legacy shortcut alone.
Run with the build venv: python scripts/installer_smoke.py path/to/Setup.exe
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import winreg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import startup_manager as startup

PRODUCT_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{6F8B064C-4278-4E7F-9BC8-CA0E05C8A551}_is1"


def run(command, env, expected=0):
    result = subprocess.run([str(x) for x in command], env=env, timeout=120,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            stdin=subprocess.DEVNULL, capture_output=True)
    assert result.returncode == expected, (command, result.returncode, result.stderr)


def main():
    setup = Path(sys.argv[1]).resolve()
    previous_setup = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else setup
    assert setup.is_file()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PRODUCT_KEY):
            raise RuntimeError("Existing installation: use a clean test account")
    except FileNotFoundError:
        pass
    assert startup._scheduled_task_state() is False, "Existing task: use clean account"
    assert startup._run_entry_present() is False, "Existing Run entry: use clean account"
    original_legacy = startup.legacy_shortcut_path()
    original_bytes = original_legacy.read_bytes() if original_legacy.exists() else None
    root = Path(tempfile.mkdtemp(prefix="vencord-installer-qa-"))
    env = dict(os.environ, LOCALAPPDATA=str(root / "local"), APPDATA=str(root / "roaming"))
    appdir = root / "Installed App With Spaces"
    exe = appdir / "VencordAutoRepair.exe"
    data = root / "local" / "VencordAutoRepair"
    flags = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
             f"/DIR={appdir}", "/GROUP=VencordAutoRepair QA"]
    try:
        run([previous_setup, *flags, "/TASKS=", f"/LOG={root / 'install.log'}"], env)
        assert exe.is_file()
        assert not startup._scheduled_task_state() and not startup._run_entry_present()
        print("PASS fresh per-user installation; startup stays disabled")
        legacy_dir = root / "Legacy App With Spaces"
        legacy_dir.mkdir()
        settings = {"watched_branches": ["canary"], "restart_discord_after_repair": False,
                    "repair_noise_toggle_bridge": False, "qa_preserved": "retained"}
        (legacy_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        legacy = root / "roaming/Microsoft/Windows/Start Menu/Programs/Startup/VencordAutoRepair.lnk"
        legacy.parent.mkdir(parents=True)
        import win32com.client
        link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(legacy))
        link.TargetPath = str(legacy_dir / "main.exe")
        link.Save()
        del link
        run([exe, "--enable-startup"], env)
        status = json.loads((data / "startup-result.json").read_text())
        assert status["success"] and status["enabled"], status
        assert not legacy.exists()
        assert json.loads((data / "settings.json").read_text()) == settings
        print("PASS legacy settings migration and shortcut cleanup; backend=" + status["backend"])
        run([setup, *flags, "/TASKS=", f"/LOG={root / 'upgrade.log'}"], env)
        assert json.loads((data / "settings.json").read_text()) == settings
        assert startup._scheduled_task_state() or startup._run_entry_present()
        status = json.loads((data / "startup-result.json").read_text())
        assert status["success"] and status["refreshed"]
        assert Path(status["command"][0]).samefile(exe)
        print("PASS in-place upgrade/reinstall preserves settings and enabled startup target")
        run([exe, "--disable-startup"], env)
        run([setup, *flags, "/TASKS=", f"/LOG={root / 'disabled-upgrade.log'}"], env)
        assert not startup._scheduled_task_state() and not startup._run_entry_present()
        print("PASS disabled startup remains disabled on reinstall")
        run([exe, "--enable-startup"], env)
        run([appdir / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
             f"/LOG={root / 'uninstall.log'}"], env)
        assert not exe.exists()
        assert not startup._scheduled_task_state() and not startup._run_entry_present()
        assert json.loads((data / "settings.json").read_text()) == settings
        print("PASS uninstall removes application and startup; settings preserved")
    finally:
        # Never leave a temporary startup target behind after a failed assertion.
        if exe.exists():
            run([exe, "--disable-startup"], env)
        assert (original_legacy.read_bytes() if original_legacy.exists() else None) == original_bytes
        print("Original user legacy shortcut unchanged; fixture: " + str(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
