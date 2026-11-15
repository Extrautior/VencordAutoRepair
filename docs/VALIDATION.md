# VencordAutoRepair 0.4.0 validation

Date: November 15, 2026. Local development branch: `dev/windows-modernization`.
The stable and experimental branches were not modified, merged, or published.

## Build and environment

Both the application and installer were successfully built on Windows 11 Pro
x64, build 26300. The local Python runtime was 3.12.15; CI is configured for the
official Windows Python 3.12.10 distribution. Build dependencies and transitives
are pinned in `requirements-build.txt`; PowerShell 7 and Inno Setup 7.1.1 are used.
The compiler download is checked against a pinned SHA-256 and Authenticode signer.
The application and setup artifacts themselves are unsigned.

The build is repeatable from source with the documented tools. Byte identity
across Python versions, machines, or installer timestamps is not claimed. The
portable ZIP uses deterministic ordering and timestamps for a fixed payload.

## Completed checks

| Check | Observed result |
| --- | --- |
| Original repository tests | All six passed before implementation |
| Final test suite | 44 tests: 43 passed, one Linux-only test skipped |
| Full build script | Tests, dependency checks, PyInstaller, portable ZIP, Inno compilation and checksums completed |
| Executable metadata | Windows GUI subsystem; `asInvoker`; version 0.4.0 and application icon embedded |
| Frozen app diagnostics | Uses bundled Python; data paths honor isolated Local AppData |
| One-shot failure path | No installed Discord produces exit 1 and a persisted failed result |
| Duplicate execution | A second process exits 0 without another repair; active result is retained; lock is released when owner exits |
| Official Vencord installation | Compiled app installed Vencord into an isolated Canary filesystem fixture |
| Official repair after update | New `app-1.0.1` fixture was repaired; original ASAR backup and previous version were preserved |
| Per-user installation | Real installer installed into a path containing spaces without elevation |
| Legacy migration | Real synthetic shortcut target settings were migrated and obsolete fixture shortcut removed |
| Startup registration | Real current-user Task Scheduler registration succeeded with interactive token and least privilege |
| Scheduled execution | Actual Task Scheduler launch of packaged app in dry-run mode completed with exit 0 |
| Upgrade/reinstall | Settings and enabled startup survived replacement; disabled startup remained disabled |
| Uninstall | Installed application and new startup registration removed; settings retained |
| Original user startup | Existing real legacy shortcut retained byte-for-byte after tests |
| Source GUI | Window launched and was visually inspected; configuration and child-process contract smokes were also exercised |

The installer-version transition used a test-only 0.3.9 installer header with
the same application payload, followed by the actual 0.4.0 installer. This tests
Inno's upgrade identity and preservation mechanics, not every historical binary.
Legacy 0.3.1 migration is separately covered by synthetic old settings/shortcut
fixtures and unit tests.

The official CLI used for the fixture was `v1.4.2 (fe6e041)`, downloaded from the
official Vencord GitHub release endpoint. Its SHA-256 was
`15268aba25625797bf562187dd87ddadf42882e079c7b6192880ad3e83353ef5`.
The fixture contained synthetic ASAR data; it did not run a real Discord client.
Canary execution was refused if an existing DiscordCanary process was detected.
The user's live Discord Stable was only inspected in dry-run mode.

NoiseToggle token/bridge content was preserved from the existing engine and its
automated tests passed. A live NoiseToggle/Krisp toggle was not exercised.

## Remaining manual verification

- Actual sign-out/sign-in and reboot, including Windows Startup Apps policy and
  the roughly 60-second Scheduler delay (30 seconds for the registry fallback).
- A clean machine without any Python installation, a separate standard-user account and an elevated administrator session. This
  host used a non-elevated, UAC-filtered token: elevation 0, elevation type 3.
  Earlier progress wording calling it a standard-user account was imprecise.
- Actual scheduler rejection/HKCU fallback under restrictive policy. Fallback,
  cleanup ordering and failure reporting were tested using controlled mocks.
- Final packaged GUI and interactive installer wizard visual checks, high DPI,
  accessibility, desktop shortcut selection and live manual GUI repair. Source
  GUI inspection completed before desktop interaction was stopped with Escape.
  No further desktop interaction was performed afterward.
- Live Discord update/restart behavior on Stable, PTB and Canary, live
  NoiseToggle/Krisp integration, and protected installation permissions.
- Linux execution and desktop autostart on a Linux host. A Linux CI test job is
  included, but GitHub Actions has not been remotely run or published here.
- Historical upgrade variants and moving a portable folder. A moved portable
  installation must explicitly refresh startup from its new location.

## Reproduce

From the repository root, using the build virtual environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
.\build.ps1
.\.venv\Scripts\python.exe scripts/windows_smoke.py --real-repair --keep
.\.venv\Scripts\python.exe scripts/installer_smoke.py dist/VencordAutoRepairSetup.exe
```

The real-repair option requires network access and uses isolated temporary
Canary data. The installer smoke refuses an existing installation or new-style
startup registration; use a clean test account. Its temporary Start Menu group
and startup registration are removed by uninstall, while fixture logs/settings
are retained for inspection. Never run these lifecycle checks concurrently with
a repair or scheduled-task test: the per-user mutex deliberately spans fixtures.

Final build, test, installer, scheduler and binary-smoke logs accompany the
deliverables. Checksums identify the delivered files.
