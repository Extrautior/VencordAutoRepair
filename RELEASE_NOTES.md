# VencordAutoRepair 0.4.0

VencordAutoRepair 0.4.0 modernizes the Windows experience while retaining the existing Vencord repair and NoiseToggle bridge behavior.

## Highlights

- Adds a lightweight Tkinter settings and status window. Launching `VencordAutoRepair.exe` with no arguments opens the GUI.
- Adds a silent `--run-once` mode, dry-run support, startup controls, and a JSON diagnostics command.
- Replaces the startup shortcut flow with a current-user Task Scheduler task, with a quoted `HKCU Run` fallback when registration is denied.
- Moves writable settings, state, logs, downloads, and results under `%LOCALAPPDATA%\VencordAutoRepair`, with XDG data paths on Linux.
- Uses a PyInstaller one-folder build and a per-user, lowest-privilege Inno Setup installer with a Start menu entry, an optional desktop shortcut, and an automatic GUI launch after a normal interactive installation finishes. Python is not installed for end users.
- Migrates valid adjacent settings and state conservatively and removes the legacy startup shortcut only after a new startup registration succeeds.

## Reliability

- Stable, PTB, and Canary are still detected and can be selected independently.
- NoiseToggle bridge repair remains optional and enabled by default; old bridge blocks are replaced without duplicates.
- Discord restart settings are preserved. A Discord installation that was closed stays closed, and an installation is restarted only when it was running and its restart option is enabled.
- An active Discord updater is allowed to settle. A timeout defers that branch instead of applying an unsafe patch.
- A per-user process lock prevents overlapping repair runs. Branch failures are isolated so the remaining branches can still be processed.

## Upgrade and portability

Upgrades retain user settings because runtime data now lives outside the installation directory. On first run, valid legacy `settings.json` and `state.json` files are copied only if the new destination does not already contain them. Existing files are never overwritten by migration.

The portable build requires the complete `VencordAutoRepair` folder. Its startup registration records an absolute path, so moving that folder requires running `VencordAutoRepair.exe --enable-startup` again from the new location.

The installer has no startup option and never enables startup. After installation or upgrade it runs `--refresh-startup`, preserving an enabled registration and leaving startup disabled when it was disabled. Silent installations do not launch the GUI. Uninstalling removes current-user startup registrations.

## Distribution

`.\build.ps1` builds from the repository's `.venv` and produces:

```text
dist\VencordAutoRepair\VencordAutoRepair.exe
dist\VencordAutoRepair-0.4.0-win64-portable.zip
dist\VencordAutoRepairSetup.exe
dist\SHA256SUMS.txt
```

The release targets Windows 10 or later on x64. The application has no tray mode, service, updater daemon, or resident Discord monitor.

Discord installations protected by administrator-controlled file permissions may require manual work by an account that already has the necessary access. VencordAutoRepair does not elevate itself, launch an elevated repair flow, or bypass UAC.

The separate experimental `streamboost-alpha` branch is outside this release and remains untouched.

## Validation

The Windows executable, portable package and installer were built successfully. The final suite passed 43 tests with one Linux-only test skipped. See [validation details and manual checks](docs/VALIDATION.md).
