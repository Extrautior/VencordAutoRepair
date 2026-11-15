"""Lightweight Tkinter configuration UI for VencordAutoRepair."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

APP_NAME = "Vencord Auto Repair"
BRANCHES = (("stable", "Stable"), ("ptb", "PTB"), ("canary", "Canary"))
OPTIONS = (
    ("restart_discord_after_repair", "Restart Discord after repair"),
    ("restart_discord_after_install", "Restart Discord after installation"),
    ("repair_noise_toggle_bridge", "Repair the NoiseToggle bridge"),
    ("restart_discord_after_noise_toggle_bridge", "Restart after bridge repair"),
)
BG, CARD, TEXT, MUTED, BLUE = "#F4F7FB", "#FFFFFF", "#172033", "#5F6B7A", "#2563EB"


def _result_view(result: Any) -> tuple[str, str, str, str]:
    """Return display state, badge, summary, and timestamp for a result."""
    if result is None:
        return "none", "No result yet", "Run a repair to see its result here.", ""
    data = result if isinstance(result, Mapping) else {"summary": str(result)}
    status = str(data.get("status", data.get("state", ""))).lower()
    code = data.get("returncode", data.get("exit_code"))
    success = data.get("success", data.get("ok"))
    failed = success is False or code not in (None, 0, "0") or any(x in status for x in ("fail", "error"))
    completed = success is True or any(x in status for x in ("success", "complete", "current", "healthy", "ok"))
    summary = str(data.get("error") or data.get("message") or data.get("summary") or data.get("detail") or "").strip()
    finished = str(data.get("finished_at") or data.get("completed_at") or data.get("updated_at") or "").strip()
    if failed:
        return "error", "Needs attention", summary or "The last repair did not finish successfully.", finished
    if completed:
        return "success", "Completed", summary or "The last repair completed successfully.", finished
    return "neutral", "Last run", summary or "A repair result is available.", finished


class _Window:
    def __init__(self, root: Any, main: Any, startup: Any, runtime: Any, tk: Any, ttk: Any, messagebox: Any, font: str) -> None:
        self.root, self.main, self.startup, self.runtime = root, main, startup, runtime
        self.tk, self.ttk, self.messagebox, self.font = tk, ttk, messagebox, font
        self.settings: dict[str, Any] = {}
        self.defaults: dict[str, Any] = {}
        self.branch_vars: dict[str, Any] = {}
        self.option_vars: dict[str, Any] = {}
        self.branch_checks: list[Any] = []
        self.option_checks: dict[str, Any] = {}
        self.startup_var = tk.BooleanVar(root, False)
        for name in ("startup_hint", "status", "detail", "feedback"):
            setattr(self, name, tk.StringVar(root))
        self.loading, self.ready = True, False
        self.startup_available, self.startup_actual = False, False
        self.baseline: dict[str, Any] = {}
        self.baseline_startup: bool | None = None
        self.process: subprocess.Popen[Any] | None = None
        self.poll_job: str | None = None
        self.result_state, self.result_summary = "none", ""
        self._style()
        self._build()
        self._load()
        self.loading = False
        self._changed()
        root.after(60, self._refresh)

    def _style(self) -> None:
        self.root.title(APP_NAME)
        self.root.configure(bg=BG)
        self.root.minsize(680, 580)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        style = self.ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except self.tk.TclError:
            pass
        style.configure(".", font=(self.font, 10), background=BG, foreground=TEXT)
        style.configure("Page.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=(self.font, 20, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=(self.font, 10))
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=(self.font, 10))
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=(self.font, 9))
        style.configure("Section.TLabel", background=CARD, foreground=TEXT, font=(self.font, 11, "bold"))
        style.configure("Card.TCheckbutton", background=CARD, foreground=TEXT, font=(self.font, 10), padding=(0, 5))
        style.map("Card.TCheckbutton", background=[("active", CARD)], foreground=[("disabled", "#8A94A6")])
        style.configure("Primary.TButton", background=BLUE, foreground="#FFFFFF", font=(self.font, 10, "bold"), padding=(15, 8))
        style.map("Primary.TButton", background=[("active", "#1D4ED8"), ("disabled", "#9AA9BF")])
        style.configure("Secondary.TButton", background=CARD, foreground=TEXT, padding=(12, 7))
        style.configure("Accent.Horizontal.TProgressbar", background=BLUE, troughcolor="#E6ECF5")

    def _card(self, parent: Any, row: int, pady: int = 0) -> Any:
        card = self.ttk.Frame(parent, style="Card.TFrame", padding=(20, 16))
        card.grid(row=row, column=0, sticky="nsew", pady=(0, pady))
        card.grid_columnconfigure(0, weight=1)
        return card

    def _build(self) -> None:
        page = self.page = self.ttk.Frame(self.root, style="Page.TFrame", padding=(28, 22))
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(4, weight=1)
        self.tk.Frame(page, bg=BLUE, height=4, bd=0).grid(row=0, column=0, sticky="ew", pady=(0, 16))
        self.ttk.Label(page, text=APP_NAME, style="Title.TLabel").grid(row=1, column=0, sticky="w")
        self.ttk.Label(page, text="Keep Vencord working after Discord updates.", style="Sub.TLabel").grid(
            row=2, column=0, sticky="w", pady=(2, 14))

        status = self._card(page, 3, 14)
        self.ttk.Label(status, text="Last repair", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.badge = self.tk.Label(status, font=(self.font, 9, "bold"), padx=10, pady=4, bd=0)
        self.badge.grid(row=0, column=1, sticky="e")
        for row, variable, style in ((1, self.status, "Card.TLabel"), (2, self.detail, "Muted.TLabel")):
            self.ttk.Label(status, textvariable=variable, style=style, wraplength=650, justify="left").grid(
                row=row, column=0, sticky="ew", pady=(7 if row == 1 else 4, 0))
        self.progress = self.ttk.Progressbar(status, style="Accent.Horizontal.TProgressbar", mode="indeterminate")
        self.progress.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.progress.grid_remove()

        settings = self._card(page, 4)
        self.ttk.Label(settings, text="Discord branches", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        branches = self.ttk.Frame(settings, style="Card.TFrame")
        branches.grid(row=1, column=0, sticky="w", pady=(5, 10))
        for column, (key, label) in enumerate(BRANCHES):
            self.branch_vars[key] = self.tk.BooleanVar(self.root, False)
            check = self.ttk.Checkbutton(branches, text=label, variable=self.branch_vars[key],
                                         style="Card.TCheckbutton", command=self._changed)
            check.grid(row=0, column=column, sticky="w", padx=(0, 22))
            self.branch_checks.append(check)
        self.ttk.Label(settings, text="Behavior", style="Section.TLabel").grid(row=2, column=0, sticky="w")
        body = self.ttk.Frame(settings, style="Card.TFrame")
        body.grid(row=3, column=0, sticky="nsew")
        for index, (key, label) in enumerate(OPTIONS):
            self.option_vars[key] = self.tk.BooleanVar(self.root, False)
            check = self.ttk.Checkbutton(body, text=label, variable=self.option_vars[key],
                                         style="Card.TCheckbutton", command=self._changed)
            check.grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 18), pady=1)
            self.option_checks[key] = check
        self.startup_check = self.ttk.Checkbutton(body, text="Start automatic checks when I sign in",
                                                  variable=self.startup_var, style="Card.TCheckbutton", command=self._changed)
        self.startup_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.ttk.Label(body, textvariable=self.startup_hint, style="Muted.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", padx=(24, 0))
        self.ttk.Label(settings, text="Automatic checks run once at sign-in, then exit completely.",
                       style="Muted.TLabel").grid(row=4, column=0, sticky="w", pady=(9, 0))

        footer = self.ttk.Frame(page, style="Page.TFrame")
        footer.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        footer.grid_columnconfigure(0, weight=1)
        self.ttk.Label(footer, textvariable=self.feedback, style="Sub.TLabel").grid(row=0, column=0, sticky="w")
        buttons = self.ttk.Frame(footer, style="Page.TFrame")
        buttons.grid(row=0, column=1, sticky="e")
        for column, (text, command, style) in enumerate((
            ("Refresh", self._refresh, "Secondary.TButton"), ("Open logs", self._open_logs, "Secondary.TButton"),
            ("Run repair now", self._repair, "Secondary.TButton"), ("Save settings", self._save, "Primary.TButton"))):
            button = self.ttk.Button(buttons, text=text, command=command, style=style)
            button.grid(row=0, column=column, padx=(0, 7) if column < 3 else 0)
            if text == "Run repair now":
                self.repair_button = button
            elif text == "Save settings":
                self.save_button = button

    def _load(self) -> None:
        try:
            self.defaults = dict(self.main.default_settings())
            loaded = self.main.load_json(self.main.settings_path(), self.defaults)
            if not isinstance(loaded, Mapping):
                raise TypeError("settings.json must contain a JSON object")
            self.settings = dict(loaded)
            watched = self.settings.get("watched_branches", self.defaults.get("watched_branches", []))
            watched = {str(x).lower() for x in watched if isinstance(watched, (list, tuple, set))}
            for key, variable in self.branch_vars.items():
                variable.set(key in watched)
            for key, variable in self.option_vars.items():
                variable.set(bool(self.settings.get(key, self.defaults.get(key, False))))
            self.ready = True
        except Exception as exc:
            self._set_enabled(False)
            self._set_status("error", "Settings unavailable", f"Fix settings.json, then reopen. ({exc})")
            self.root.after_idle(lambda error=str(exc): self._error(
                f"Settings could not be loaded. The file was not changed.\n\n{error}"))
            return
        try:
            self.startup_actual = self._startup_enabled()
            self.startup_available = True
            self.startup_var.set(self.startup_actual)
            self.startup_hint.set("Detected from the current startup registration.")
        except Exception as exc:
            self.startup_hint.set("Startup status could not be read; Save will leave it unchanged.")
            self.root.after_idle(lambda error=str(exc): self._error(
                f"Startup status could not be read.\n\n{error}"))
        self.baseline = self._values()
        self.baseline_startup = self.startup_actual if self.startup_available else None
        self._set_enabled(True)

    def _startup_enabled(self) -> bool:
        check = getattr(self.startup, "is_enabled", None)
        if callable(check):
            value = check()
            if isinstance(value, bool):
                return value
        path_fn = getattr(self.startup, "shortcut_path", None)
        if not callable(path_fn):
            raise RuntimeError("startup_manager cannot report startup status")
        return Path(path_fn()).exists()

    def _values(self) -> dict[str, Any]:
        return {"watched_branches": [key for key, var in self.branch_vars.items() if var.get()],
                **{key: bool(var.get()) for key, var in self.option_vars.items()}}

    def _changed(self, *_args: Any) -> None:
        if not self.loading:
            dirty = self.ready and (self._values() != self.baseline or
                                    (self.startup_available and self.startup_var.get() != self.baseline_startup))
            self.feedback.set("Save changes before running repair" if dirty else ("Settings unavailable" if not self.ready else "Settings are up to date"))
            self.repair_button.configure(state="normal" if self.ready and not dirty and self.process is None else "disabled")

    def _set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for check in (*self.branch_checks, *self.option_checks.values()):
            check.configure(state=state)
        self.startup_check.configure(state=state if enabled and self.startup_available else "disabled")
        self.option_checks["restart_discord_after_noise_toggle_bridge"].configure(
            state="normal" if enabled and self.option_vars["repair_noise_toggle_bridge"].get() else "disabled")
        self.save_button.configure(state=state)
        self.repair_button.configure(state=state if self.process is None else "disabled")
        self._changed()

    def _save(self) -> None:
        if not self.ready or self.process is not None:
            return
        values = self._values()
        if not values["watched_branches"]:
            self._error("Choose at least one Discord branch before saving.")
            return
        updated = {**self.settings, **values}
        try:
            self.main.save_json(self.main.settings_path(), updated)
        except Exception as exc:
            self.feedback.set("Save failed")
            self._error(f"Settings could not be saved.\n\n{exc}")
            return
        self.settings = updated
        startup_error = None
        if self.startup_available:
            desired = bool(self.startup_var.get())
            try:
                if self._startup_enabled() != desired:
                    action = self.startup.add_to_startup if desired else self.startup.remove_from_startup
                    response = action()
                    failed = isinstance(response, Mapping) and response.get("success") is False
                    if response is False or failed or self._startup_enabled() != desired:
                        raise RuntimeError("startup registration did not change")
                self.startup_actual = self._startup_enabled()
            except Exception as exc:
                startup_error = exc
                try:
                    self.startup_actual = self._startup_enabled()
                    self.startup_var.set(self.startup_actual)
                except Exception:
                    pass
        self.baseline = self._values()
        self.baseline_startup = self.startup_actual if self.startup_available else None
        self._changed()
        if startup_error:
            self.feedback.set("Settings saved; startup update failed")
            self._error(f"Settings were saved, but startup could not be updated.\n\n{startup_error}")
        else:
            self.feedback.set("Settings saved")

    def _set_status(self, state: str, badge: str, summary: str, detail: str = "") -> None:
        colors = {"success": ("#E8F6EE", "#176B3A"), "error": ("#FDECEC", "#A12828")}
        background, foreground = colors.get(state, ("#EEF2F7", "#475569"))
        self.badge.configure(text=badge, background=background, foreground=foreground)
        self.status.set(summary)
        self.detail.set(detail)
        self.result_state, self.result_summary = state, summary

    def _refresh(self) -> None:
        if self.process is not None:
            return
        try:
            result = self.runtime.read_result()
        except Exception as exc:
            self._set_status("error", "Status unavailable", "The last repair result could not be read.")
            self._error(f"The last repair result could not be read.\n\n{exc}")
            return
        state, badge, summary, finished = _result_view(result)
        self._set_status(state, badge, summary, f"Finished {finished}" if finished else "")

    def _repair_command(self) -> tuple[list[str], Path]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--run-once"], Path(sys.executable).resolve().parent
        app = Path(__file__).resolve().with_name("app.py")
        if not app.is_file():
            raise FileNotFoundError(f"Application entry point not found: {app}")
        return [sys.executable, str(app), "--run-once"], app.parent

    def _repair(self) -> None:
        if self.process is not None:
            return
        if not self.ready:
            self._error("Repair cannot start until settings are available.")
            return
        try:
            command, cwd = self._repair_command()
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            self.process = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            creationflags=flags, close_fds=True)
        except Exception as exc:
            self.process = None
            self._error(f"The repair could not be started.\n\n{exc}")
            return
        self._set_enabled(False)
        self.feedback.set("Repair running")
        self.progress.grid()
        self.progress.start(12)
        self._set_status("neutral", "In progress", "Repairing selected Discord branches...",
                         "Discord may close briefly if Vencord needs repair.")
        self.poll_job = self.root.after(200, self._poll)

    def _poll(self) -> None:
        self.poll_job = None
        if self.process is None:
            return
        code = self.process.poll()
        if code is None:
            self.poll_job = self.root.after(200, self._poll)
            return
        self.process = None
        self.progress.stop()
        self.progress.grid_remove()
        self._set_enabled(True)
        self._refresh()
        self.feedback.set("Repair finished" + (" with an error" if code else ""))
        if code:
            self._error(f"The repair process exited with code {code}. Open the logs for details.")
        elif self.result_state == "error":
            self._error(f"The repair finished, but reported a failure.\n\n{self.result_summary}")

    def _open_logs(self) -> None:
        try:
            folder = Path(self.runtime.data_dir())
            if not folder.exists():
                raise FileNotFoundError(f"Log folder does not exist yet: {folder}")
            if os.name == "nt":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(folder)], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
            else:
                raise OSError("Opening logs is supported on Windows and Linux.")
        except Exception as exc:
            self._error(f"The log folder could not be opened.\n\n{exc}")

    def _error(self, message: str) -> None:
        self.messagebox.showerror(APP_NAME, message, parent=self.root)

    def close(self) -> None:
        if self.process is not None and not self.messagebox.askyesno(
                APP_NAME, "Repair is still running. Closing this window will not stop it.\n\nClose anyway?"):
            return
        if self.poll_job:
            self.root.after_cancel(self.poll_job)
        self.root.destroy()


def show_gui() -> None:
    """Import and start the GUI only when the caller requests it."""
    import tkinter as tk
    from tkinter import font as tkfont, messagebox, ttk
    import app_runtime, main, startup_manager

    root = tk.Tk(className="VencordAutoRepair")
    icon = Path(__file__).resolve().parent / "assets" / "VencordAutoRepair.ico"
    if os.name == "nt" and icon.exists():
        root.iconbitmap(str(icon))
    root.withdraw()
    families = set(tkfont.families(root))
    font = "Segoe UI" if "Segoe UI" in families else tkfont.nametofont("TkDefaultFont", root=root).actual("family")
    _Window(root, main, startup_manager, app_runtime, tk, ttk, messagebox, font)
    x = max(0, (root.winfo_screenwidth() - 780) // 2)
    y = max(0, (root.winfo_screenheight() - 640) // 2 - 20)
    root.geometry(f"780x640+{x}+{y}")
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    show_gui()
