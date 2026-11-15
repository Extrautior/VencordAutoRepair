# Windows startup design

This document describes the VencordAutoRepair 0.4.0 startup design for Windows. The design is per user, non-elevated, and intended for an interactive desktop session.

## Original risk diagnosis

The 0.3.1 startup path was reviewed from its code and shortcut behavior. These are identified risks, not a reproduced end-user incident:

| Observed risk | Consequence | 0.4.0 control |
| --- | --- | --- |
| The shortcut targeted the console `main.exe` or a console `python.exe` running `main.py`. | A console process or flash could appear at sign-in. | The packaged entry point is a windowed PyInstaller executable, and automation runs it with `--run-once`. |
| Source-mode shortcut arguments were composed as an unquoted path. | A checkout path containing spaces could be parsed as multiple arguments. | Task Scheduler stores command and arguments separately; the registry fallback uses Windows command-line quoting. |
| Settings, state, and downloads were written beside the executable. | A protected or read-only application directory could block writes. | Runtime data moved to the current user's Local AppData directory. |
| The old build definition did not explicitly set UAC behavior; the local original binary was inspected and already requests `asInvoker`. | UAC elevation is not established as this host's root cause. | The new executable also uses `asInvoker`; installation and startup stay per user and non-elevated. |

No failure report from a user was available, so no specific prompt, launch failure, or data-loss event is claimed.

## Registration flow

`--enable-startup` first attempts a current-user Task Scheduler task named `VencordAutoRepair-<user SID>`. The task principal uses the current user's SID, `InteractiveToken` logon, and `LeastPrivilege` run level. `InteractiveToken` requires an existing interactive logon session and lets the tool run in that user's desktop context rather than as a service or as SYSTEM. Microsoft documents these semantics in [LogonType (principalType) Element](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-logontype-principaltype-element) and [RunLevel (principalType) Element](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-runlevel-principaltype-element).

The Task Scheduler action is the installed `VencordAutoRepair.exe` with the arguments `--run-once --startup` and the application directory as the working directory. The XML schema keeps the executable and argument strings separate, avoiding the old shortcut's path-to-argument ambiguity. The task uses `MultipleInstancesPolicy=IgnoreNew` and a twenty-minute execution limit.

If Task Scheduler rejects registration, including an access denial, the tool writes a per-user entry under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. The entry contains the same absolute executable path and uses the same one-shot arguments with Windows command-line quoting. No administrator registration is attempted.

Only after one of those registrations succeeds does `--enable-startup` remove the exact legacy `VencordAutoRepair.lnk` shortcut from the current user's Startup folder. A failed registration leaves existing startup state available for diagnosis. `--disable-startup` removes the scheduled task, the registry fallback, and the legacy shortcut. `--refresh-startup` re-registers only when startup is already enabled, so an installer upgrade does not silently opt a user into startup.

## Timing

The scheduled task uses a logon trigger with `Delay=PT30S`. Microsoft defines the value as the interval between user logon and task start in [LogonTrigger.Delay](https://learn.microsoft.com/en-us/windows/win32/taskschd/logontrigger-delay).

The application also applies one additional fixed 30-second delay when its internal `--startup` argument is present. This gives Discord's delayed sign-in startup time to begin an update without creating a polling monitor. The two delays mean intended execution begins at roughly one minute after an interactive logon; Task Scheduler can start later under system load, so this is a delay policy rather than a hard readiness guarantee. The registry fallback does not receive the Task Scheduler delay, but still receives the application's bounded 30-second delay.

## Process and duplicate control

The repair engine runs one pass and exits. The GUI can start another pass manually, but no tray icon, Windows service, watchdog, or continuous Discord monitor remains resident.

Repair execution holds a per-user lock. Windows uses a named mutex; Linux source mode uses an advisory lock file in the XDG data directory. A second invocation exits without a second repair pass and logs the skip without overwriting the active result. The scheduled task's `IgnoreNew` policy provides a second layer while the task is active.

## Packaging and console behavior

`build.ps1` uses PyInstaller's one-folder mode and a windowed executable. PyInstaller explains that Windows `noconsole`/windowed builds have no attached console and expose its standard streams as unavailable in [Common Issues and Pitfalls: standard streams in noconsole applications](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#sysstdin-sysstdout-and-sysstderr-in-noconsolewindowed-applications-windows-only). `--run-once` therefore stays silent, and diagnostic output is also persisted to `diagnostics.json` rather than relying on a console.

The one-folder distribution contains the executable and its runtime files. Portable users must keep the whole folder together. Startup records an absolute path; moving the folder leaves the registration pointing at the old path until `--enable-startup` is run again.

The Inno Setup installer uses `PrivilegesRequired=lowest` and installs per user under `%LOCALAPPDATA%\Programs\VencordAutoRepair`. It does not install Python. Setup creates a Start menu entry by default, offers an optional desktop shortcut, and does not expose a startup task. Startup is configured in the GUI.

After installation or upgrade, Setup always runs `--refresh-startup`. This refreshes an enabled registration and preserves a disabled state without opting the user into startup. A normal interactive installation launches the GUI once after Setup finishes; silent installation skips that launch.

## Data and migration

Windows runtime files are stored under `%LOCALAPPDATA%\VencordAutoRepair`: settings and state, rotating logs, downloads, the last result, diagnostics, and startup status. Linux uses `$XDG_DATA_HOME/VencordAutoRepair` or `~/.local/share/VencordAutoRepair`.

Before a repair pass, the runtime checks adjacent legacy locations and the application directory named by the exact legacy shortcut. A legacy `settings.json` or `state.json` is copied only when it is a valid JSON object and the destination file does not exist. Migration never replaces newer data and does not delete the source files. A legacy installer path is redirected to the new `downloads` directory only when it identifies an official Vencord installer beside that legacy source.

This separation also makes upgrades safer: replacing files in the application directory does not replace user settings. Administrator-owned Discord installations may still deny modification. Those cases require manual remediation with an account that already has the appropriate access; VencordAutoRepair does not request elevation, schedule a highest-privilege task, or bypass UAC.

## Repair safeguards

The startup modernization preserves the existing Discord Stable, PTB, and Canary branches, NoiseToggle repair, and restart preferences. A closed Discord installation remains closed. A running installation may be restarted only when a change was needed and its restart option is enabled.

When Discord's updater is active, the tool waits for completion. A timeout raises a branch-level failure and defers the patch instead of proceeding over an active updater. Failures are isolated per branch, recorded in the log and result file, and reflected in the process exit code.

## Validation boundary

This design document records intended behavior and the source-level risk diagnosis. Build and runtime validation is provided in the separate validation report; this document does not claim that validation has passed.
