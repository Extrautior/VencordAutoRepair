# VencordAutoRepair 0.4.0

VencordAutoRepair performs a single install or repair pass for selected Discord Stable, PTB, and Canary installations. It uses Vencord's official installer CLI, preserves the NoiseToggle bridge, and provides a small Tkinter configuration window on Windows.

## Download

- [Download VencordAutoRepairSetup.exe](https://github.com/Extrautior/VencordAutoRepair/releases/latest/download/VencordAutoRepairSetup.exe) for the per-user Windows installer.
- [Download VencordAutoRepair-0.4.0-win64-portable.zip](https://github.com/Extrautior/VencordAutoRepair/releases/download/v0.4.0/VencordAutoRepair-0.4.0-win64-portable.zip) from the version-specific `v0.4.0` release tag.

## Install and use

1. Run `VencordAutoRepairSetup.exe`.
2. Optionally select the desktop shortcut. Setup places a Start menu entry in place by default.
3. After a normal interactive installation, Setup opens the configuration GUI after Finish. Configure Startup in that GUI if you want it enabled; Setup itself never enables startup.

The installer is per user, requests the lowest privileges, and installs under `%LOCALAPPDATA%\Programs\VencordAutoRepair`. It does not install Python for the user. Silent installations complete without launching the GUI.

Launching `VencordAutoRepair.exe` with no arguments opens the GUI. Use the GUI to choose Discord branches, set restart behavior, configure startup, run one repair, and open the log folder. The installer does not offer a startup option.

The uncompressed portable build must remain intact. Run `VencordAutoRepair.exe` from inside the complete `VencordAutoRepair` folder; a lone executable is not sufficient. Startup stores the absolute executable path. If the folder moves, rerun `VencordAutoRepair.exe --enable-startup` from the new location.

## Command line

```text
VencordAutoRepair.exe                         Open the GUI
VencordAutoRepair.exe --run-once              Run one silent repair pass
VencordAutoRepair.exe --run-once --dry-run    Show planned work without changes
VencordAutoRepair.exe --enable-startup        Enable sign-in startup
VencordAutoRepair.exe --disable-startup       Remove all startup registrations
VencordAutoRepair.exe --refresh-startup       Refresh startup only if enabled
VencordAutoRepair.exe --diagnostics           Write diagnostics.json
```

`--run-once` does not open the GUI or keep a process resident. Startup uses `--run-once --startup` internally; the extra `--startup` argument adds a bounded delay for Discord's own delayed startup. Control flags cannot be combined with repair flags.

## Runtime data

User data is separate from the application folder. On Windows it is stored under `%LOCALAPPDATA%\VencordAutoRepair`:

- `settings.json` and `state.json`: configuration and observed branch state
- `VencordAutoRepair.log` and rotating backups: diagnostics
- `last-result.json`, `diagnostics.json`, and `startup-result.json`: recent results
- `downloads\VencordInstallerCli.exe`: the official installer downloaded when needed

Linux uses `$XDG_DATA_HOME/VencordAutoRepair`, or `~/.local/share/VencordAutoRepair` when `XDG_DATA_HOME` is unset. Linux autostart uses `$XDG_CONFIG_HOME/autostart`, with `~/.config/autostart` as the fallback.

The Windows application lock prevents two repair passes from running at once. A duplicate invocation exits without changing Discord and logs that the duplicate was skipped.

## Repair behavior

- Stable, PTB, and Canary discovery and selection remain supported.
- A closed Discord installation stays closed. Discord is restarted only when it was running before a required change and the matching restart option is enabled.
- If Discord's updater is active, VencordAutoRepair waits for it to settle. If the wait times out, repair for that branch is deferred until a later run; the tool does not patch over an active update.
- NoiseToggle bridge repair remains optional and enabled by default. Missing or older bridge blocks are replaced without stacking duplicates.
- Failures in one branch do not prevent the remaining branches from being processed.
- Actual patch and repair work is delegated to the official Vencord installer CLI.

## Startup and upgrades

Windows startup uses a current-user Task Scheduler task with an interactive token, least privilege, and a 30-second logon delay. If that registration is rejected, the tool falls back to a quoted per-user `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` entry. Disabling startup removes the task, the fallback entry, and the legacy shortcut.

On first run, valid legacy `settings.json` and `state.json` files adjacent to the old executable are copied into the new data directory only when the destination files do not exist. Legacy files are left in place. The installer upgrades in place, retains existing settings, and runs `--refresh-startup` after installation. This preserves an enabled startup registration and leaves startup disabled when it was disabled. The old `VencordAutoRepair.lnk` startup shortcut is removed only after a new registration succeeds.

## Linux source use

Python source use remains available on Linux with Python 3.11 or later and the dependencies in `requirements.txt`. The optional GUI also needs your distribution's Tkinter package:

```bash
python3 -m pip install -r requirements.txt
python3 app.py
python3 app.py --run-once
```

Common native and Flatpak Discord layouts are discovered. Installation under administrator-protected locations may require manual remediation with an account that already has the required access. VencordAutoRepair never self-elevates or attempts to bypass UAC.

## Build

The Windows build uses a PyInstaller one-folder application with a windowed executable, so normal GUI and one-shot launches do not open a console. Use PowerShell 7 or later. Create the local build environment and run the script from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build.ps1
```

`build.ps1` uses `.venv`, verifies the pinned dependencies, runs the repository tests, builds the application and portable ZIP, compiles the per-user Inno Setup installer, and writes checksums. Current release targets are:

```text
dist\VencordAutoRepair\VencordAutoRepair.exe
dist\VencordAutoRepair-0.4.0-win64-portable.zip
dist\VencordAutoRepairSetup.exe
dist\SHA256SUMS.txt
```

See the [validation report](docs/VALIDATION.md) for completed checks and remaining manual verification, and [delegation evidence](docs/DELEGATION.md) for the verified DeepSeek route.

## Project boundaries

This release keeps the existing NoiseToggle and Discord branch functionality. It does not add a tray application, Windows service, or background Discord monitor. The separate experimental `streamboost-alpha` branch is outside this release and remains untouched.
