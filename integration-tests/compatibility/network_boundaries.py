#!/usr/bin/env python3
"""Check real cjpm multi-registry fallback boundaries with isolated local HTTP fixtures."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import uuid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", type=Path, required=True)
    parser.add_argument("--include-timeout", action="store_true",
                        help="also exercise the client's real 60-second read timeout")
    args = parser.parse_args()
    executable = args.cjpm.resolve()
    if not executable.is_file():
        parser.error("cjpm executable does not exist")
    parent = Path(__file__).resolve().parents[1] / ".tmp"
    root = parent / f"network-boundaries-{uuid.uuid4().hex}"
    root.mkdir(parents=True)
    mode = ""
    requests: list[str] = []
    timeout_release = threading.Event()
    index = (json.dumps(dict(name="auth", organization="company", version="1.0.0",
                             sha256sum="0" * 64, dependencies=[])) + "\n").encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            requests.append(self.path)
            if self.path.startswith("/high/"):
                if mode == "timeout":
                    timeout_release.wait(70)
                    self.close_connection = True
                    return
                if mode == "reset":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.close_connection = True
                    return
                if mode == "truncated":
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(index) + 100))
                    self.end_headers()
                    self.wfile.write(index[:10])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                status = int(mode) if mode.isdigit() else 200
                body = b"not JSON" if mode == "malformed" else index
            else:
                status, body = 200, index
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    fixture.daemon_threads = True
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    refused = socket.socket()
    refused.bind(("127.0.0.1", 0))  # Reserve an unused endpoint without listening.
    origin = f"http://127.0.0.1:{fixture.server_port}"
    failures = 0
    cases = [(status, False, status in ("404", "500", "503"))
             for status in ("400", "401", "403", "404", "429", "500", "503")]
    cases += [(failure, False, False) for failure in ("reset", "truncated", "malformed", "refused")]
    cases += [(failure, True, False) for failure in ("404", "503", "reset")]
    if args.include_timeout:
        cases.append(("timeout", False, False))
    try:
        for number, (failure, exclusive, should_fallback) in enumerate(cases, 1):
            mode = failure
            requests.clear()
            case_root = root / str(number)
            case_root.mkdir()
            high = (f"http://127.0.0.1:{refused.getsockname()[1]}" if failure == "refused"
                    else origin + "/high")
            config = (f'[repository.cache]\npath = "cache"\n'
                      f'[repository.high]\nregistry = "{high}"\npriority = 100\n'
                      f'[repository.low]\nregistry = "{origin}/low"\npriority = 10\n')
            if exclusive:
                config += '[[route]]\nnamespace = "company::*"\nregistry = "high"\nexclusive = true\n'
            (case_root / "cangjie-repo.toml").write_text(config, encoding="utf-8")
            result = subprocess.run((executable, "repo", "explain", "company::auth"), cwd=case_root,
                                    env=dict(os.environ), capture_output=True, text=True,
                                    encoding="utf-8", errors="replace",
                                    timeout=75 if failure == "timeout" else 15)
            output = result.stdout + result.stderr
            (case_root / "output.log").write_text(output, encoding="utf-8")
            low_count = sum(path.startswith("/low/") for path in requests)
            passed = ((result.returncode == 0) == should_fallback and
                      low_count == int(should_fallback) and
                      (not should_fallback or "repository: low" in output))
            failures += not passed
            print(f"{'PASS' if passed else 'FAIL'} mode={failure} exclusive={exclusive} "
                  f"lower_requests={low_count} exit={result.returncode}", flush=True)
    finally:
        timeout_release.set()
        refused.close()
        fixture.shutdown()
        fixture.server_close()
        thread.join(timeout=2)
        if failures or sys.exc_info()[0] is not None:
            print(f"Failure evidence retained: {root}", flush=True)
        else:
            shutil.rmtree(root)
            try:
                parent.rmdir()
            except OSError:
                pass
    print(f"Network boundaries: {len(cases) - failures}/{len(cases)} passed.", flush=True)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
