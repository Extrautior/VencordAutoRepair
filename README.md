# VencordAutoRepair

VencordAutoRepair watches your installed Discord branches, waits for Discord's updater to settle, installs Vencord automatically if it is missing, and runs the official `VencordInstallerCli.exe --repair` flow when a Discord update replaces the patched app files.

## What it does

- Detects installed Discord Stable, PTB, and Canary builds from `%LOCALAPPDATA%`
- Detects common Linux Discord install paths too, including Arch-friendly locations like `/opt/discord` and `/usr/share/discord`
- Tracks the newest `app-*` version seen for each branch
- Waits for Discord updater activity to settle when an update is already in progress
- Waits for updater activity to stop before patching
- Verifies whether Vencord still appears patched
- Uses the official Vencord CLI installer to install or repair the install
- Can restart Discord after an install or repair

## Files

- `main.py`: main watcher/repair script
- `startup_manager.py`: add or remove the script from Windows startup or Linux desktop autostart
- `settings.json`: runtime settings, created on first run
- `state.json`: last seen Discord versions, created on first run
- `VencordInstallerCli.exe`: downloaded automatically on first run unless you point `settings.json` at your own copy

The current behavior is intentionally conservative:

- If Discord's updater is already running, the tool waits for it to finish
- If Discord is closed, the tool does not force-launch it anymore
- If Discord is running and an install or repair is needed, the tool closes it, applies the action, and can restart it afterward
- If Discord is unpatched and looks like a plain install, the tool installs Vencord automatically
- If Discord was updated and the patch is gone, the tool repairs Vencord automatically

## Install for Python use

1. Install Python 3.11+ on Windows.
2. In this folder run `python -m pip install -r requirements.txt`
3. Run `python main.py`
4. Optional: run `python startup_manager.py` and choose `Add to startup`
5. Optional validation: run `python main.py --dry-run`

## Linux use

This project also supports Linux desktop Discord installs and is aimed to work for common Arch-style locations.

1. Install Python 3.11+ and `pip`
2. Run `python3 -m pip install -r requirements.txt`
3. Run `python3 main.py --dry-run`
4. Run `python3 main.py` for the real install/repair flow
5. Optional: run `python3 startup_manager.py` and choose `Add to startup`

Shell wrappers are included too:

- `./main.sh`
- `./startup_manager.sh`

## Build an EXE

1. Run `python -m pip install -r requirements.txt`
2. Run `python setup.py build`
3. Open the generated `build` folder
4. Run `main.exe`
5. Optional: run `startup_manager.exe` and choose `Add to startup`
6. Optional validation: run `main.exe --dry-run`

## Download a release

If you are using a published GitHub release:

1. Download the latest Windows zip from the Releases page
2. Extract it anywhere
3. Run `main.exe`
4. Run `startup_manager.exe` if you want automatic startup

Linux users can download the Linux tarball release, extract it, run `python3 -m pip install -r requirements.txt`, then use `python3 main.py` or `./main.sh`.

## Settings

The script writes a `settings.json` file the first time it runs.

Example:

```json
{
  "installer_path": "C:\\path\\to\\VencordInstallerCli.exe",
  "download_installer_if_missing": true,
  "restart_discord_after_repair": true,
  "restart_discord_after_install": true,
  "watched_branches": [
    "stable",
    "ptb",
    "canary"
  ]
}
```

## Notes

- This targets Windows desktop installs and common Linux desktop Discord installs
- It intentionally delegates the actual patching to the official Vencord installer instead of reimplementing Vencord's patch format
- Vencord is a Discord client modification; use it at your own risk
