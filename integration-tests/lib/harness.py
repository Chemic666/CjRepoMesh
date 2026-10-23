from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


class TestFailure(RuntimeError):
    """A deterministic integration-test assertion failure."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes


def run_command(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    expect_success: bool = True,
    timeout: float | None = None,
) -> CommandResult:
    printable = " ".join(str(item) for item in command)
    try:
        completed = subprocess.run(
            [str(item) for item in command],
            cwd=cwd,
            env=None if env is None else dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise TestFailure(f"Command timed out after {timeout}s: {printable}") from error
    result = CommandResult(completed.returncode, completed.stdout)
    if expect_success and result.returncode != 0:
        raise TestFailure(
            f"Command failed with exit code {result.returncode}: {printable}\n{result.output}"
        )
    if not expect_success and result.returncode == 0:
        raise TestFailure(f"Command unexpectedly succeeded: {printable}\n{result.output}")
    return result


def assert_contains(value: str, expected: str, *, label: str = "output") -> None:
    if expected not in value:
        raise TestFailure(f"Expected {label} to contain {expected!r}, got:\n{value}")


def assert_equal(actual: object, expected: object, *, label: str) -> None:
    if actual != expected:
        raise TestFailure(f"Expected {label} to be {expected!r}, got {actual!r}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def publish_frame(metadata: bytes, artifact: bytes) -> bytes:
    return b"".join(
        (
            b"\x01",
            struct.pack("<I", len(metadata)),
            metadata,
            b"\x01",
            struct.pack("<I", len(artifact)),
            artifact,
        )
    )


def http_request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 10.0,
) -> HttpResult:
    request = urllib.request.Request(url, data=body, headers=dict(headers or {}), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResult(response.status, response.read())
    except urllib.error.HTTPError as error:
        return HttpResult(error.code, error.read())
    except OSError as error:
        raise TestFailure(f"HTTP {method} failed for {url}: {error}") from error


def wait_for_health(port: int, *, attempts: int = 50, interval: float = 0.1,
                    process: subprocess.Popen | None = None, log_path: Path | None = None) -> None:
    url = f"http://127.0.0.1:{port}/health"
    last_error: Exception | None = None
    for _ in range(attempts):
        if process is not None and process.poll() is not None:
            location = f"; child log: {log_path}" if log_path is not None else ""
            raise TestFailure(f"Repository on port {port} exited with code {process.returncode}{location}")
        try:
            result = http_request("GET", url, timeout=1.0)
            if result.status == 200 and json.loads(result.body).get("status") == "ok":
                return
        except (TestFailure, json.JSONDecodeError) as error:
            last_error = error
        time.sleep(interval)
    suffix = f": {last_error}" if last_error else ""
    location = f"; child log: {log_path}" if log_path is not None else ""
    raise TestFailure(f"Repository on port {port} did not become ready{suffix}{location}")


def wait_for_port(port: int, *, attempts: int = 50, interval: float = 0.05) -> None:
    for _ in range(attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(interval)
            if client.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(interval)
    raise TestFailure(f"Process did not listen on port {port}")


def assert_ports_available(ports: Iterable[int]) -> None:
    occupied: list[int] = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(0.1)
            if client.connect_ex(("127.0.0.1", port)) == 0:
                occupied.append(port)
    if occupied:
        raise TestFailure(f"Required test ports are already in use: {', '.join(map(str, occupied))}")


def wait_for_ports_closed(ports: Iterable[int], *, attempts: int = 50) -> None:
    remaining = set(ports)
    for _ in range(attempts):
        open_ports: set[int] = set()
        for port in remaining:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.settimeout(0.05)
                if client.connect_ex(("127.0.0.1", port)) == 0:
                    open_ports.add(port)
        if not open_ports:
            return
        remaining = open_ports
        time.sleep(0.1)
    raise TestFailure(f"Test processes left listening ports behind: {sorted(remaining)}")


class ManagedProcesses:
    def __init__(self) -> None:
        self._processes: list[tuple[subprocess.Popen[bytes], object | None]] = []

    def start(
        self,
        command: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        output_path: Path | None = None,
    ) -> subprocess.Popen[bytes]:
        output_stream = output_path.open("wb") if output_path else subprocess.DEVNULL
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            [str(item) for item in command],
            cwd=cwd,
            env=None if env is None else dict(env),
            stdin=subprocess.DEVNULL,
            stdout=output_stream,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        self._processes.append((process, None if output_stream is subprocess.DEVNULL else output_stream))
        return process

    def stop(self, process: subprocess.Popen[bytes]) -> None:
        for item in list(self._processes):
            if item[0] is process:
                self._stop_item(item)
                self._processes.remove(item)
                return

    def close(self) -> None:
        for item in reversed(self._processes):
            self._stop_item(item)
        self._processes.clear()

    @staticmethod
    def _stop_item(item: tuple[subprocess.Popen[bytes], object | None]) -> None:
        process, output_stream = item
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if output_stream is not None:
            output_stream.close()

    def __enter__(self) -> "ManagedProcesses":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


def remove_within(path: Path, allowed_roots: Iterable[Path]) -> None:
    resolved = path.resolve()
    roots = [root.resolve() for root in allowed_roots]
    if not any(resolved != root and root in resolved.parents for root in roots):
        raise TestFailure(f"Refusing to remove path outside test roots: {resolved}")
    if resolved.is_dir() and not resolved.is_symlink():
        shutil.rmtree(resolved)
    elif resolved.exists() or resolved.is_symlink():
        resolved.unlink()


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def platform_executable(base: Path) -> Path:
    if os.name == "nt":
        return base.with_suffix(".exe")
    return base


def python_command() -> str:
    return sys.executable
