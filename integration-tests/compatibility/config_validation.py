#!/usr/bin/env python3
"""Reject mistyped routing settings before any registry request (stdlib only)."""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
import threading


class Registry(BaseHTTPRequestHandler):
    requests: list[str] = []

    def do_GET(self) -> None:
        self.requests.append(self.path)
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args) -> None:
        pass


def main() -> int:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", type=Path, required=True)
    args = parser.parse_args()
    executable = args.cjpm.resolve()
    if not executable.is_file():
        parser.error("cjpm executable does not exist")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Registry)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    temporary_parent = project / "integration-tests" / ".tmp"
    temporary_parent.mkdir(exist_ok=True)
    origin = f"http://127.0.0.1:{server.server_port}"
    repositories = f'''[repository.cache]
path = "cache"
[repository.private]
registry = "{origin}/private"
priority = 100
enabled = true
token-env = "CJREPOMESH_CONFIG_FIXTURE_TOKEN"
token = ""
[repository.public]
registry = "{origin}/public"
priority = 10
'''
    route = '''[[route]]
namespace = "company::*"
registry = "private"
exclusive = true
'''
    base = repositories + route
    cases = [
        ("exclusive", base.replace("exclusive = true", 'exclusive = "true"'), "boolean"),
        ("enabled", base.replace("enabled = true", 'enabled = "false"'), "boolean"),
        ("priority", base.replace("priority = 100", 'priority = "100"'), "integer"),
        ("token-env", base.replace('token-env = "CJREPOMESH_CONFIG_FIXTURE_TOKEN"', "token-env = 123"), "string"),
        ("token", base.replace('token = ""', "token = 123"), "string"),
        ("path", base.replace('path = "cache"', "path = 123"), "string"),
        ("registry", base.replace(f'registry = "{origin}/private"', "registry = 123"), "string"),
        ("namespace", base.replace('namespace = "company::*"', "namespace = 123"), "string"),
        ("registry", repositories + route.replace('registry = "private"', "registry = 123"), "string"),
        ("strict-tls", '[global]\nstrict-tls = "false"\n' + base, "boolean"),
        ("global", 'global = "invalid"\n' + base, "table"),
        ("repository", 'repository = "invalid"\n', "table"),
        ("route", 'route = "invalid"\n' + repositories, "array"),
    ]
    # The shared TOML-to-DataModel converter turns all four temporal types into
    # strings. Repository configuration must validate the original TOML types.
    for temporal in ("2026-10-20", "12:34:56", "2026-10-20T12:34:56", "2026-10-20T12:34:56Z"):
        cases.append(("namespace", base.replace('namespace = "company::*"',
                                                f"namespace = {temporal}"), "string"))
    for field, old_value in (
        ("path", 'path = "cache"'),
        ("registry", f'registry = "{origin}/private"'),
        ("token-env", 'token-env = "CJREPOMESH_CONFIG_FIXTURE_TOKEN"'),
        ("token", 'token = ""'),
        ("registry", 'registry = "private"'),
    ):
        cases.append((field, base.replace(old_value, f"{field} = 2026-10-20"), "string"))
    for address in (
        origin.replace("http://", "http://fixture-user:fixture-secret@") + "/private",
        origin + "/private?token=fixture-secret",
        origin + "/private#fixture-secret",
        "file:///fixture-secret",
        "//127.0.0.1/fixture-secret",
        origin + "/private\\fixture-secret",
        origin + "/private\nfixture-secret",
    ):
        cases.append(("registry", base.replace(f'registry = "{origin}/private"',
                                               f"registry = {json.dumps(address)}"), "safe-url"))
    environment = dict(os.environ)
    environment["CJREPOMESH_CONFIG_FIXTURE_TOKEN"] = "fixture-token"
    failures = 0
    try:
        with tempfile.TemporaryDirectory(prefix="config-validation-", dir=temporary_parent) as directory:
            root = Path(directory)
            config_path = root / "cangjie-repo.toml"

            def invoke(config: str, command: str = "doctor", recorded: bool = False) -> subprocess.CompletedProcess[str]:
                config_path.write_text(config, encoding="utf-8")
                Registry.requests.clear()
                return subprocess.run(
                    [str(executable), "repo", command, "company::auth"] + (["--recorded"] if recorded else []), cwd=root,
                    env=environment, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=20,
                )

            for number, (field, config, expected_type) in enumerate(cases, 1):
                result = invoke(config)
                article = "an" if expected_type in {"integer", "array"} else "a"
                diagnostic = ("registry URL must use HTTP(S)" if expected_type == "safe-url" else
                              f"field '{field}' must be {article} {expected_type}")
                output = result.stdout + result.stderr
                passed = (result.returncode != 0 and diagnostic in output and not Registry.requests and
                          "fixture-secret" not in output)
                if expected_type == "safe-url":
                    explained = invoke(config, "explain")
                    explain_output = explained.stdout + explained.stderr
                    passed = (passed and explained.returncode != 0 and diagnostic in explain_output and
                              not Registry.requests and "fixture-secret" not in explain_output)
                failures += not passed
                print(f"{'PASS' if passed else 'FAIL'} case={number} field={field} "
                      f"rejected_before_network={not Registry.requests}", flush=True)

            for address in (origin.replace("http://", "http://user:fixture-secret@"),
                            origin + "?token=fixture-secret", origin + "#fixture-secret", origin):
                document = dict(formatVersion=1, packages=[dict(package="company::auth", version="1.0.0",
                                repository="private", registry=address, sha256="0" * 64)])
                (root / "cjpm-provenance.json").write_text(json.dumps(document), encoding="utf-8")
                result = invoke(base, "explain", recorded=True)
                output = result.stdout + result.stderr
                safe = address == origin
                passed = ((result.returncode == 0) == safe and not Registry.requests and
                          "fixture-secret" not in output and
                          ("Recorded resolution:" in output if safe else "recorded registry URL is unsafe" in output))
                failures += not passed
                print(f"{'PASS' if passed else 'FAIL'} historical-record safe={safe}", flush=True)

            # Omitted optional fields retain their defaults and reach only the exclusive route.
            minimal = f'[repository.home]\nregistry = "{origin}/private"\n'
            quoted_date_token = base.replace('token-env = "CJREPOMESH_CONFIG_FIXTURE_TOKEN"\n', "") \
                .replace('token = ""', 'token = "2026-10-20"')
            for label, config in (("valid-exclusive-route", base), ("legacy-defaults", minimal),
                                  ("quoted-date-string", quoted_date_token)):
                result = invoke(config)
                passed = result.returncode != 0 and len(Registry.requests) == 1 and \
                    Registry.requests[0].startswith("/private/") and "status=404" in result.stdout
                failures += not passed
                print(f"{'PASS' if passed else 'FAIL'} {label}", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        try:
            temporary_parent.rmdir()
        except OSError:
            pass
    print(f"Configuration validation: {len(cases) + 7 - failures}/{len(cases) + 7} passed.")
    return int(failures != 0)


if __name__ == "__main__":
    raise SystemExit(main())
