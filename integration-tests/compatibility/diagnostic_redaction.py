#!/usr/bin/env python3
"""Check configured-token redaction in real cjpm HTTP 400 diagnostics."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
import uuid

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from lib.harness import TestFailure, run_command, sha256, remove_within  # noqa: E402

TOKEN = "synthetic-cjrepomesh-diagnostic-token-4ab87e"
DETAIL = "fixture-validation-detail"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", required=True, type=Path)
    parser.add_argument("--evidence-dir", type=Path, help="new output directory")
    args = parser.parse_args()
    client = args.cjpm.resolve()
    if not client.is_file():
        parser.error("an existing enhanced cjpm binary is required")
    parent = TESTS / ".tmp"
    suffix = uuid.uuid4().hex
    root = parent / ("diagnostic-redaction-" + suffix)
    report = (args.evidence_dir or parent / ("diagnostic-redaction-report-" + suffix)).resolve()
    report.mkdir(parents=True, exist_ok=False)
    root.mkdir(parents=True)
    home = root / "home"
    home.mkdir()
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("CJREPO_", "CJREPOMESH_")) and key != "CJPM_CONFIG"}
    environment.update(HOME=str(home), USERPROFILE=str(home), CJREPOMESH_DIAGNOSTIC_TOKEN=TOKEN)
    mode, endpoint = "", ""
    requests = []
    index = b""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self):
            authorization = self.headers.get("Authorization", "")
            requests.append(dict(method=self.command, path=self.path,
                                 authorization_matches=authorization == ("" if mode == "no-token" else TOKEN)))
            if endpoint == "download" and self.path.startswith("/index/"):
                status, body = 200, index
            else:
                message = DETAIL if mode in ("control", "no-token") else DETAIL + " " + authorization
                body = (json.dumps(dict(errors=[dict(message=message)])).encode()
                        if mode != "text" else message.encode())
                status = 400
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.respond()

    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    fixture.daemon_threads = True
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{fixture.server_port}"
    results, error = [], ""
    started = time.monotonic()

    def application(relative: str, label: str, token: str = TOKEN) -> Path:
        app = root / label
        app.mkdir()
        source = TESTS / relative
        shutil.copyfile(source / "cjpm.toml", app / "cjpm.toml")
        shutil.copytree(source / "src", app / "src")
        if source.joinpath("README.md").is_file():
            shutil.copyfile(source / "README.md", app / "README.md")
        app.joinpath("cangjie-repo.toml").write_text(
            f'[repository.cache]\npath = "cache"\n[repository.home]\nregistry = "{origin}"\n'
            'token-env = "CJREPOMESH_DIAGNOSTIC_TOKEN"\n', encoding="utf-8")
        return app

    try:
        package = application("multirepo/packages/meshdep-v1-high", "package")
        bundled = run_command((client, "bundle"), cwd=package, env=environment, timeout=60)
        (report / "bundle.log").write_text(bundled.output, encoding="utf-8")
        metadata = json.loads(package.joinpath("target/meta-data.json").read_text(encoding="utf-8"))
        index = (json.dumps(metadata["index"]) + "\n").encode()
        cases = [(f"index-{body}-{command}", body, "index", ("repo", command, "meshdep"))
                 for command in ("explain", "doctor") for body in ("json", "text")]
        cases += [(f"{operation}-{body}", body, operation,
                   ("build",) if operation == "download" else ("publish",))
                  for operation in ("download", "publish") for body in ("json", "text")]
        cases += [("ordinary-detail", "control", "index", ("repo", "doctor", "meshdep")),
                  ("no-token-detail", "no-token", "index", ("repo", "doctor", "meshdep"))]
        for label, mode, endpoint, arguments in cases:
            requests.clear()
            if endpoint == "publish":
                app = package
            else:
                app = application("multirepo/app-pinned", label)
            variables = dict(environment)
            if mode == "no-token":
                variables["CJREPOMESH_DIAGNOSTIC_TOKEN"] = ""
            result = run_command((client, *arguments), cwd=app, env=variables,
                                 expect_success=False, timeout=60)
            (report / (label + ".log")).write_text(result.output, encoding="utf-8")
            reached = (any(r["method"] == "POST" and r["path"].startswith("/pkg/") for r in requests)
                       if endpoint == "publish" else
                       any(r["method"] == "GET" and r["path"].startswith("/pkg/") for r in requests)
                       if endpoint == "download" else
                       any(r["path"].startswith("/index/") for r in requests))
            facts = dict(endpoint_reached=reached, token_absent=TOKEN not in result.output,
                         detail_preserved=DETAIL in result.output,
                         status_preserved="status=400" in result.output or "status 400" in result.output,
                         authorization_matches=bool(requests) and all(r["authorization_matches"] for r in requests),
                         no_success_provenance=not app.joinpath("cjpm-provenance.json").exists())
            passed = all(facts.values())
            results.append(dict(name=label, status="PASS" if passed else "FAIL",
                                returncode=result.returncode, facts=facts, requests=list(requests)))
            print(f"{'PASS' if passed else 'FAIL'} {label} token_absent={facts['token_absent']}", flush=True)
    except (TestFailure, OSError, ValueError, KeyError) as failure:
        error = str(failure)
        print("FAIL diagnostic redaction: " + error, flush=True)
    finally:
        fixture.shutdown()
        fixture.server_close()
        thread.join(timeout=2)
        passed_count = sum(item["status"] == "PASS" for item in results)
        success = not error and len(results) == passed_count == 10
        summary = dict(success=success, passed=passed_count, total=10,
                       seconds=round(time.monotonic() - started, 2),
                       inputs=dict(client_sha256=sha256(client), runner_sha256=sha256(Path(__file__)),
                                   harness_sha256=sha256(TESTS / "lib/harness.py")),
                       cases=results, error=error,
                       limits=["Owned local HTTP fixture and synthetic token; not a production-secret audit.",
                               "Covers exact configured token in HTTP 400 JSON/plain-text diagnostics only.",
                               "Does not establish redaction of encoded tokens or every exception/log path."])
        (report / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if success:
            remove_within(root, (parent,))
        else:
            print(f"Failure fixtures retained: {root}", flush=True)
    print(f"Diagnostic redaction: {passed_count}/10; success={success}; report: {report}", flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
