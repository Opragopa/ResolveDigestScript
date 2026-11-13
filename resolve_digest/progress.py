"""Responsive Windows progress UI, isolated from Resolve's busy Python thread.

Only the main Resolve thread calls its API. A WinForms child handles painting
and Cancel while Python waits for HTTP; JSON lines carry state over pipes.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import threading


class ProgressCancelled(RuntimeError):
    pass


class ConsoleProgress:
    def update(self, percent, message, detail="", cancellable=True):
        print(f"Resolve Digest [{percent}%]: {message} {detail}")

    def check_cancelled(self):
        pass

    def finish(self, status, message, detail="", output_dir="", report_path=""):
        print(f"Resolve Digest [100%] — {status}: {message}\n{detail}\nРабота завершена.")


class WindowsProgress(ConsoleProgress):
    def __init__(self):
        self._cancelled = threading.Event()
        self._ready = threading.Event()
        self._terminal_received = threading.Event()
        self._startup_ok = False
        self._diagnostics = []
        self._finished = False
        self._percent = 0
        script = Path(__file__).with_name("progress_window.ps1").read_text(encoding="utf-8-sig")
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        self._process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-STA", "-EncodedCommand", encoded],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        threading.Thread(target=self._read_events, daemon=True).start()
        if not self._ready.wait(15):
            self._stop()
            raise RuntimeError("Не удалось открыть окно прогресса. " + "\n".join(self._diagnostics))
        if not self._startup_ok or self._process.poll() is not None:
            self._stop()
            raise RuntimeError("Окно прогресса завершилось при запуске. " + "\n".join(self._diagnostics))

    def _read_events(self):
        try:
            for line in self._process.stdout:
                if line.strip() == "READY":
                    self._startup_ok = True
                    self._ready.set()
                elif line.strip() == "CANCEL":
                    self._cancelled.set()
                elif line.strip() == "FINISHED":
                    self._terminal_received.set()
                else:
                    self._diagnostics.append(line.strip())
                    self._diagnostics = self._diagnostics[-12:]
        finally:
            self._ready.set()  # Wake startup promptly if PowerShell failed.
            self._process.stdout.close()

    def _stop(self):
        if self._process.poll() is None:
            self._process.terminate()
        self._process.wait(timeout=5)
        if self._process.stdin:
            self._process.stdin.close()

    def check_cancelled(self):
        if self._cancelled.is_set():
            raise ProgressCancelled("Операция отменена пользователем.")
        if not self._finished and self._process.poll() is not None:
            raise RuntimeError("Окно прогресса неожиданно закрылось. " + "\n".join(self._diagnostics))

    def _send(self, state):
        try:
            self._process.stdin.write(json.dumps(state, ensure_ascii=False) + "\n")
            self._process.stdin.flush()
        except (OSError, ValueError) as error:
            raise RuntimeError("Потеряна связь с окном прогресса.") from error

    def update(self, percent, message, detail="", cancellable=True):
        self.check_cancelled()
        self._percent = max(self._percent, min(99, int(percent)))
        self._send(dict(status="working", percent=self._percent, message=message,
                        detail=detail, cancellable=cancellable))

    def finish(self, status, message, detail="", output_dir="", report_path=""):
        if self._finished:
            return
        try:
            self._send(dict(status=status, percent=100,
                            message=message, detail=detail, cancellable=False,
                            output_dir=str(output_dir), report_path=str(report_path)))
            if not self._terminal_received.wait(5):
                raise RuntimeError("Окно прогресса не подтвердило итог операции. " + "\n".join(self._diagnostics))
            self._finished = True
        finally:
            self._process.stdin.close()


def create_progress():
    return WindowsProgress() if os.name == "nt" else ConsoleProgress()
