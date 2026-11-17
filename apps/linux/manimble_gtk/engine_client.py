"""Asynchronous JSON-lines client for the shared Python engine."""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
from concurrent.futures import Future
from pathlib import Path


class EngineClient:
    def __init__(self, *, on_event=None, python: str | None = None):
        executable = python or os.environ.get("MANIMBLE_PYTHON") or sys.executable
        spec = importlib.util.find_spec("manimble")
        if spec is None or spec.origin is None:
            raise RuntimeError("The Manimble engine package is not installed")
        package_root = str(Path(spec.origin).resolve().parent.parent)
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            item for item in (package_root, env.get("PYTHONPATH", "")) if item
        )
        env["MANIMBLE_PYTHON"] = executable
        env["PYTHONUNBUFFERED"] = "1"
        self.process = subprocess.Popen(
            [executable, "-u", "-m", "manimble.rpc"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1, env=env,
        )
        self.on_event = on_event
        self._pending: dict[int, Future] = {}
        self._lock = threading.Lock()
        self._write_queue: queue.Queue[str | None] = queue.Queue()
        self._next_id = 1
        threading.Thread(target=self._read_stdout, daemon=True, name="manimble-engine-output").start()
        threading.Thread(target=self._read_stderr, daemon=True, name="manimble-engine-log").start()
        threading.Thread(target=self._write_stdin, daemon=True, name="manimble-engine-input").start()

    def request(self, command: str, **args) -> Future:
        future = Future()
        with self._lock:
            if self.process.poll() is not None:
                future.set_exception(RuntimeError("The Manimble engine is not running"))
                return future
            request_id = self._next_id
            self._next_id += 1
            self._pending[request_id] = future
        message = {"id": request_id, "cmd": command, **args}
        self._write_queue.put(json.dumps(message, ensure_ascii=False) + "\n")
        return future

    def _write_stdin(self):
        try:
            while line := self._write_queue.get():
                if self.process.stdin is None:
                    break
                self.process.stdin.write(line)
                self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            self._fail_pending(RuntimeError("The Manimble engine stopped"))

    def _read_stdout(self):
        try:
            for line in self.process.stdout or ():
                message = json.loads(line)
                if "event" in message:
                    if self.on_event:
                        self.on_event(message)
                    continue
                request_id = message.get("id")
                with self._lock:
                    future = self._pending.pop(request_id, None)
                if future is None:
                    continue
                if "error" in message:
                    future.set_exception(RuntimeError(message["error"]))
                else:
                    future.set_result(message.get("result", {}))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self._fail_pending(RuntimeError(f"Invalid response from the Manimble engine: {error}"))
        finally:
            self._fail_pending(RuntimeError("The Manimble engine stopped"))

    def _read_stderr(self):
        for line in self.process.stderr or ():
            sys.stderr.write(line)

    def _fail_pending(self, error: Exception):
        with self._lock:
            pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(error)

    def close(self):
        self._write_queue.put(None)
        if self.process.poll() is None:
            self.process.terminate()
