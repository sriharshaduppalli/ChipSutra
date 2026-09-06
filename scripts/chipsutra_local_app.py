"""ChipSutra Local — Windows control panel for the native stack."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

ROOT = Path(__file__).resolve().parents[1]
PS1 = ROOT / "scripts" / "chipsutra-local.ps1"
POWERSHELL = os.environ.get("SystemRoot", r"C:\Windows") + r"\System32\WindowsPowerShell\v1.0\powershell.exe"


def _ps(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    cmd = [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PS1),
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))


def _url_ok(url: str) -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=2) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def _health() -> dict:
    out = {
        "backend": _url_ok("http://127.0.0.1:8001/api/health"),
        "frontend": _url_ok("http://127.0.0.1:3000"),
        "ollama": _url_ok("http://127.0.0.1:11434/api/tags"),
        "detail": {},
    }
    if out["backend"]:
        try:
            import urllib.request

            with urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=3) as r:
                out["detail"] = json.loads(r.read().decode("utf-8", errors="replace"))
        except Exception:
            out["detail"] = {}
    return out


def _admin_email() -> str:
    env = ROOT / "backend" / ".env"
    email = "admin@chipsutra.local"
    if not env.is_file():
        return email
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("ADMIN_EMAIL"):
            email = line.split("=", 1)[-1].strip().strip('"').strip("'")
            break
    return email


class LocalApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ChipSutra Local")
        self.geometry("520x560")
        self.minsize(480, 520)
        self.resizable(False, False)
        self._busy = False

        pad = {"padx": 16, "pady": 4}
        ttk.Label(self, text="ChipSutra Local", font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=16, pady=(16, 2))
        ttk.Label(
            self,
            text="Start the stack on this PC, then test Generate + Pure SV Simulate.",
            wraplength=480,
        ).pack(anchor="w", **pad)

        self.status = ttk.LabelFrame(self, text="Status")
        self.status.pack(fill="x", padx=16, pady=8)
        self.vars = {
            "backend": tk.StringVar(value="…"),
            "frontend": tk.StringVar(value="…"),
            "ollama": tk.StringVar(value="…"),
            "verilator": tk.StringVar(value="…"),
            "mongo": tk.StringVar(value="…"),
            "model": tk.StringVar(value="…"),
        }
        for key, label in (
            ("backend", "API  :8001"),
            ("frontend", "UI   :3000"),
            ("ollama", "Ollama"),
            ("verilator", "Verilator"),
            ("mongo", "Mongo"),
            ("model", "LLM"),
        ):
            row = ttk.Frame(self.status)
            row.pack(fill="x", padx=10, pady=3)
            ttk.Label(row, text=label, width=14).pack(side="left")
            ttk.Label(row, textvariable=self.vars[key]).pack(side="left")

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=16, pady=8)
        self.btn_start = ttk.Button(btns, text="Start", command=self.on_start)
        self.btn_stop = ttk.Button(btns, text="Stop", command=self.on_stop)
        self.btn_open = ttk.Button(btns, text="Open portal", command=lambda: webbrowser.open("http://localhost:3000"))
        self.btn_health = ttk.Button(
            btns, text="API health", command=lambda: webbrowser.open("http://localhost:8001/api/health")
        )
        self.btn_start.pack(side="left", padx=(0, 6))
        self.btn_stop.pack(side="left", padx=6)
        self.btn_open.pack(side="left", padx=6)
        self.btn_health.pack(side="left", padx=6)

        extra = ttk.Frame(self)
        extra.pack(fill="x", padx=16, pady=(0, 8))
        ttk.Button(extra, text="Pin to Desktop", command=self.on_shortcut).pack(side="left")
        ttk.Button(extra, text="Refresh", command=self.refresh).pack(side="left", padx=6)

        box = ttk.LabelFrame(self, text="How to test")
        box.pack(fill="both", expand=True, padx=16, pady=8)
        steps = (
            f"1. Click Start, wait until API and UI are up, then Open portal.\n"
            f"2. Sign in with { _admin_email() } (password is ADMIN_PASSWORD in backend\\.env).\n"
            f"   Or create a new account on /signup — email verification is off locally.\n"
            f"3. Projects → 60s wizard (counter), or upload your own .sv.\n"
            f"4. Generate → Testbench (Pure SV). Then Simulate → Compile + Run.\n"
            f"5. UVM is source-only here; ChipSutra Simulate runs Pure SV on Verilator.\n"
            f"Stop only closes :8001 and :3000. Ollama stays running."
        )
        ttk.Label(box, text=steps, justify="left", wraplength=470).pack(anchor="w", padx=10, pady=8)

        self.log = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.log, wraplength=480).pack(anchor="w", padx=16, pady=(0, 12))

        self.after(200, self.refresh)
        self.after(4000, self._tick)

    def _tick(self) -> None:
        if not self._busy:
            self.refresh()
        self.after(4000, self._tick)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_start, self.btn_stop):
            b.configure(state=state)

    def refresh(self) -> None:
        h = _health()
        self.vars["backend"].set("up" if h["backend"] else "down")
        self.vars["frontend"].set("up" if h["frontend"] else "down")
        self.vars["ollama"].set("up" if h["ollama"] else "down — start Ollama from the Start menu")
        d = h.get("detail") or {}
        v = d.get("verilator")
        self.vars["verilator"].set("yes" if v is True else ("no" if v is False else ("—" if not h["backend"] else str(v))))
        mongo = d.get("mongo") or {}
        if not h["backend"]:
            self.vars["mongo"].set("—")
        else:
            self.vars["mongo"].set("ok" if mongo.get("ok") else f"error: {mongo.get('error') or 'unknown'}")
        llm = (d.get("llm_providers") or {}).get("ollama_model") or (d.get("ollama") or {}).get("model")
        self.vars["model"].set(str(llm) if llm else ("—" if not h["backend"] else "not reported"))

    def on_start(self) -> None:
        self._run_ps(["-Start"], "Starting backend + frontend… first UI compile can take a minute.")

    def on_stop(self) -> None:
        self._run_ps(["-Stop"], "Stopping API and UI…")

    def on_shortcut(self) -> None:
        try:
            r = _ps(["-Shortcut"], timeout=20)
            if r.returncode != 0:
                messagebox.showerror("ChipSutra Local", (r.stderr or r.stdout or "Shortcut failed").strip())
                return
            self.log.set("Desktop shortcut created: ChipSutra Local")
        except Exception as e:
            messagebox.showerror("ChipSutra Local", str(e))

    def _run_ps(self, args: list[str], msg: str) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self.log.set(msg)

        def work() -> None:
            err = ""
            try:
                r = _ps(args, timeout=180)
                if r.returncode != 0:
                    err = (r.stderr or r.stdout or "command failed").strip()[-500:]
            except Exception as e:
                err = str(e)

            def done() -> None:
                self._set_busy(False)
                self.refresh()
                if err:
                    self.log.set(err)
                    messagebox.showerror("ChipSutra Local", err)
                else:
                    self.log.set("Done. Use Open portal to test Generate.")
                    if args == ["-Start"] and _url_ok("http://127.0.0.1:3000"):
                        webbrowser.open("http://localhost:3000")

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()


if __name__ == "__main__":
    LocalApp().mainloop()
