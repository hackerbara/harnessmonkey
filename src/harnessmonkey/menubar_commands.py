from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_CAPTURE_CHARS = 120_000
MAX_LOG_FIELD_CHARS = 2_000
# Bound on how long finalize() waits for the reader threads to hit EOF after
# the process itself has exited. A double-forked/backgrounded descendant can
# inherit the stdout/stderr pipe fds and keep them open indefinitely, which
# would otherwise wedge the reader threads (and the held _mutating_lock)
# forever even though the command we launched is long gone.
READER_JOIN_TIMEOUT_SECONDS = 5.0


class MutatingCommandBusy(RuntimeError):
    pass


@dataclass(frozen=True)
class CapturedProcess:
    returncode: int
    stdout: str
    stderr: str


@dataclass
class StreamingHandle:
    process: subprocess.Popen[str]

    def cancel(self, grace_seconds: float = 5.0) -> None:
        try:
            pgid = os.getpgid(self.process.pid)
        except ProcessLookupError:
            return
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return

        def escalate() -> None:
            try:
                self.process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        threading.Thread(target=escalate, daemon=True).start()


class _BoundedTextCapture:
    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars
        self._chunks: list[str] = []
        self._length = 0

    def append(self, text: str) -> None:
        if self._length >= self.max_chars:
            return
        remaining = self.max_chars - self._length
        kept = text[:remaining]
        self._chunks.append(kept)
        self._length += len(kept)

    def value(self) -> str:
        return "".join(self._chunks)


def _drain_stream(stream, capture: _BoundedTextCapture) -> None:
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            capture.append(chunk)
    finally:
        stream.close()


def _run_bounded_subprocess(argv: list[str]) -> CapturedProcess:
    process = subprocess.Popen(  # noqa: S603 - argv is explicit and shell=False.
        argv,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("subprocess pipes were not created")
    stdout_capture = _BoundedTextCapture(MAX_CAPTURE_CHARS)
    stderr_capture = _BoundedTextCapture(MAX_CAPTURE_CHARS)
    stdout_thread = threading.Thread(
        target=_drain_stream, args=(process.stdout, stdout_capture), daemon=True
    )
    stderr_thread = threading.Thread(
        target=_drain_stream, args=(process.stderr, stderr_capture), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()
    returncode = process.wait()
    stdout_thread.join()
    stderr_thread.join()
    return CapturedProcess(returncode, stdout_capture.value(), stderr_capture.value())


class CommandRunner:
    def __init__(
        self,
        *,
        cli_argv: list[str] | None = None,
        logs_dir: Path,
        run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.cli_argv = list(cli_argv or ["harnessmonkey"])
        self.logs_dir = logs_dir
        self.run = run
        self._mutating_lock = threading.Lock()
        self._busy_for_test = False
        self._results: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def log_path(self) -> Path:
        return self.logs_dir / "menubar.log"

    def mark_busy_for_test(self) -> None:
        self._busy_for_test = True

    def clear_busy_for_test(self) -> None:
        self._busy_for_test = False

    def post_result_for_test(self, name: str, payload: dict[str, Any]) -> None:
        self._results.put((name, payload))

    def drain_results(self) -> list[tuple[str, dict[str, Any]]]:
        items: list[tuple[str, dict[str, Any]]] = []
        while True:
            try:
                items.append(self._results.get_nowait())
            except queue.Empty:
                break
        return items

    def _log(self, command: list[str], returncode: int, stderr: str, stdout: str = "") -> None:
        stamp = datetime.now(UTC).isoformat()
        line = json.dumps(
            {
                "timestamp": stamp,
                "command": command,
                "returncode": returncode,
                "stdout": stdout[:MAX_LOG_FIELD_CHARS],
                "stderr": stderr[:MAX_LOG_FIELD_CHARS],
            },
            sort_keys=True,
        )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def log_ui_event(self, event: str, **fields: Any) -> None:
        stamp = datetime.now(UTC).isoformat()
        line = json.dumps(
            {
                "timestamp": stamp,
                "event": event,
                **fields,
            },
            sort_keys=True,
        )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def run_json(self, args: list[str], *, mutating: bool) -> dict[str, Any]:
        if self._busy_for_test and mutating:
            raise MutatingCommandBusy("another mutating command is running")

        acquired = False
        if mutating:
            acquired = self._mutating_lock.acquire(blocking=False)
            if not acquired:
                raise MutatingCommandBusy("another mutating command is running")

        try:
            argv = [*self.cli_argv, *args]
            result = self._run_command(argv)
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            self._log(argv, int(result.returncode), stderr, stdout)
            return self._finalize_json_payload(stdout, stderr, int(result.returncode))
        finally:
            if acquired:
                self._mutating_lock.release()

    def _finalize_json_payload(self, stdout: str, stderr: str, returncode: int) -> dict[str, Any]:
        if stdout.strip():
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                return payload
        if returncode != 0:
            message = stderr.strip() or f"command exited {returncode}"
            return {
                "schemaVersion": 1,
                "ok": False,
                "status": "error",
                "summary": message,
                "reportPath": None,
                "targetPath": None,
                "authorizationRequired": False,
                "authorizationMethod": None,
                "dryRun": False,
                "plannedActions": [],
                "error": {"message": message, "code": "command_failed"},
            }
        raise ValueError("command succeeded but did not emit JSON")

    def open_path(self, path: Path) -> None:
        expanded = path.expanduser()
        result = self._run_command(["open", str(expanded)])
        self._log(
            ["open", str(expanded)],
            int(result.returncode),
            result.stderr or "",
            result.stdout or "",
        )

    def _run_command(self, argv: list[str]) -> CapturedProcess | subprocess.CompletedProcess[str]:
        if self.run is not None:
            return self.run(
                argv,
                shell=False,
                capture_output=True,
                text=True,
                check=False,
            )
        return _run_bounded_subprocess(argv)

    def run_background(self, name: str, args: list[str], *, mutating: bool) -> None:
        def worker() -> None:
            try:
                payload = self.run_json(args, mutating=mutating)
            except Exception as exc:
                payload = {
                    "schemaVersion": 1,
                    "ok": False,
                    "status": "error",
                    "summary": str(exc),
                    "reportPath": None,
                    "targetPath": None,
                    "authorizationRequired": False,
                    "authorizationMethod": None,
                    "dryRun": False,
                    "plannedActions": [],
                    "error": {"message": str(exc), "code": "command_failed"},
                }
            self._results.put((name, payload))

        threading.Thread(target=worker, daemon=True).start()

    def run_streaming(
        self, name: str, args: list[str], *, on_event: Callable[[dict[str, Any]], None]
    ) -> StreamingHandle:
        if self._busy_for_test:
            raise MutatingCommandBusy("another mutating command is running")

        acquired = self._mutating_lock.acquire(blocking=False)
        if not acquired:
            raise MutatingCommandBusy("another mutating command is running")

        released = threading.Event()

        def release_lock() -> None:
            if not released.is_set():
                released.set()
                self._mutating_lock.release()

        argv = [*self.cli_argv, *args]
        try:
            process = subprocess.Popen(  # noqa: S603 - argv is explicit and shell=False.
                argv,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except Exception:
            release_lock()
            raise

        if process.stdout is None or process.stderr is None:
            release_lock()
            raise RuntimeError("subprocess pipes were not created")

        stdout_capture = _BoundedTextCapture(MAX_CAPTURE_CHARS)
        stderr_capture = _BoundedTextCapture(MAX_CAPTURE_CHARS)

        def read_stdout() -> None:
            _drain_stream(process.stdout, stdout_capture)

        def read_stderr() -> None:
            # Intentionally line-buffered (unlike _drain_stream's chunked
            # reads) because each stderr line must be individually parsed as
            # a JSONL progress event or, failing that, wrapped as a log event.
            stream = process.stderr
            try:
                for raw_line in stream:
                    stderr_capture.append(raw_line)
                    stripped = raw_line.rstrip("\n")
                    if not stripped:
                        continue
                    try:
                        obj = json.loads(stripped)
                    except json.JSONDecodeError:
                        obj = None
                    event = (
                        obj
                        if isinstance(obj, dict)
                        else {"event": "log", "stage": None, "line": stripped}
                    )
                    try:
                        on_event(event)
                    except Exception:
                        # Progress reporting must never break the underlying
                        # operation: a bad GUI callback shouldn't truncate
                        # the rest of the stream (matches StageTracker
                        # philosophy elsewhere in the codebase).
                        pass
            finally:
                stream.close()

        def finalize() -> None:
            try:
                stdout_thread = threading.Thread(target=read_stdout, daemon=True)
                stderr_thread = threading.Thread(target=read_stderr, daemon=True)
                stdout_thread.start()
                stderr_thread.start()
                returncode = process.wait()
                # Bounded: a double-forked/backgrounded grandchild can inherit
                # the pipe fds and keep them open past the parent's exit, in
                # which case these threads would never see EOF. Proceed with
                # whatever was captured rather than hanging (and holding
                # _mutating_lock) forever; the leaked daemon threads simply
                # keep running in the background until the descendant exits.
                stdout_thread.join(timeout=READER_JOIN_TIMEOUT_SECONDS)
                stderr_thread.join(timeout=READER_JOIN_TIMEOUT_SECONDS)
                truncated = stdout_thread.is_alive() or stderr_thread.is_alive()
                stdout = stdout_capture.value()
                stderr = stderr_capture.value()
                if truncated:
                    stderr = (
                        stderr
                        + "\n[harnessmonkey: reader thread still running after process "
                        "exit; capture may be truncated (likely an orphaned descendant "
                        "holding stdio open)]"
                    )
                self._log(argv, int(returncode), stderr, stdout)
                try:
                    payload = self._finalize_json_payload(stdout, stderr, int(returncode))
                except Exception as exc:
                    payload = {
                        "schemaVersion": 1,
                        "ok": False,
                        "status": "error",
                        "summary": str(exc),
                        "reportPath": None,
                        "targetPath": None,
                        "authorizationRequired": False,
                        "authorizationMethod": None,
                        "dryRun": False,
                        "plannedActions": [],
                        "error": {"message": str(exc), "code": "command_failed"},
                    }
                self._results.put((name, payload))
            finally:
                release_lock()

        threading.Thread(target=finalize, daemon=True).start()

        return StreamingHandle(process=process)
