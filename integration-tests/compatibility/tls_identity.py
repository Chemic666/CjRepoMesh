#!/usr/bin/env python3
"""Real Linux cjpm TLS identity checks with an owned HTTPS registry fixture."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", type=Path, required=True)
    parser.add_argument("--package-dir", type=Path, required=True, help="existing genuine company::teamhello bundle output")
    parser.add_argument("--evidence-dir", type=Path, required=True, help="new directory for sanitized evidence")
    parser.add_argument('--expiry-only',action='store_true',help='run only the four expired-leaf stages')
    args = parser.parse_args()
    if os.name != "posix":
        parser.error("run with the existing Linux SDK environment; no Windows Cangjie execution")
    client, package, report = args.cjpm.resolve(), args.package_dir.resolve(), args.evidence_dir.resolve()
    if not client.is_file():
        parser.error("the existing Linux cjpm executable is required")
    metadata = json.loads((package / "meta-data.json").read_text())
    if (metadata["name"], metadata["organization"], metadata["version"]) != ("teamhello", "company", "1.0.0"):
        parser.error("use the existing team example archive")
    artifact = (package / "teamhello-1.0.0.cjp").read_bytes()
    assert hashlib.sha256(artifact).hexdigest() == metadata["index"]["sha256sum"]
    report.mkdir(parents=True, exist_ok=False)
    root = Path(tempfile.mkdtemp(prefix="cjrepomesh-tls-"))
    cert = root / "certificates"
    cert.mkdir(mode=0o700)
    publish_token, read_token = secrets.token_hex(32), secrets.token_hex(32)
    environment = {k:v for k,v in os.environ.items() if k.upper() not in
                   ("CJPM_CONFIG", "SSL_CERT_FILE", "SSL_CERT_DIR") and not k.upper().startswith("CJREPO_")}
    mode, observations, redirected, cases = "", [], [], []
    servers, threads, error = [], [], ""
    handshakes=[]; handshake_changed=threading.Condition(); total=4 if args.expiry_only else 19
    started = time.monotonic()

    def openssl(*arguments):
        result = subprocess.run(["openssl", *arguments], cwd=cert, capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError("synthetic certificate generation failed")

    def run(job, command, *, trust=True, token=None, label):
        home = job / ".home"
        home.mkdir(exist_ok=True)
        env = dict(environment, HOME=str(home), USERPROFILE=str(home), TLS_TEST_TOKEN=token or read_token,
                   SSL_CERT_DIR=str(cert / "empty-trust-directory"))
        if trust:
            env["SSL_CERT_FILE"] = str(cert / "ca.pem")
        else:
            env["SSL_CERT_FILE"] = str(cert / "missing-ca.pem")
        result = subprocess.run([str(v) for v in command], cwd=job, env=env, text=True,
                                capture_output=True, timeout=90)
        output = result.stdout + result.stderr
        for value in (read_token, publish_token):
            output = output.replace(value, "[REDACTED]")
        (report / (label + ".log")).write_text(output, encoding="utf-8")
        return result.returncode, output

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_registry(self):
            token = self.headers.get("Authorization", "")
            wanted = publish_token if self.command == "POST" else read_token
            authorized = token == wanted
            redirect = mode.startswith("redirect-") and (
                (mode == "redirect-index" and self.path.startswith("/index/")) or
                (mode == "redirect-publish" and self.command == "POST") or
                (mode == "redirect-download" and self.path.startswith("/pkg/")))
            observations.append(dict(method=self.command, path=self.path, authorized=authorized,
                                     tls=self.connection.version()))
            if not authorized:
                status, body = 401, b'{"message":"authentication failed"}'
            elif redirect:
                if self.command == "POST":
                    self.rfile.read(int(self.headers.get("Content-Length", "0")))
                status, body = (302 if mode == "redirect-index" else 307), b"{}"
            elif self.command == "POST":
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                status, body = 200, b"{}"
            elif self.path.startswith("/index/"):
                if mode in ('download-wrong-host','download-expired'):
                    selected='expired' if mode=='download-expired' else 'wrong'
                    context.load_cert_chain(cert / (selected+'.pem'), cert / (selected+'.key'))
                status, body = 200, (json.dumps(metadata["index"]) + "\n").encode()
            elif self.path.startswith("/pkg/"):
                status, body = 200, artifact
            else:
                status, body = 404, b"{}"
            self.send_response(status)
            observations[-1]["status"] = status
            if authorized and redirect:
                self.send_header("Location", sink_origin + self.path)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        do_GET = do_POST = handle_registry

    class RedirectSink(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_sink(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            redirected.append(dict(method=self.command, path=self.path, bytes=len(body),
                                   authorization_present=bool(self.headers.get("Authorization")),
                                   contains_archive=body.endswith(artifact) if body else False))
            payload = (json.dumps(metadata["index"]) + "\n").encode() if self.path.startswith("/index/") else artifact
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = handle_sink

    try:
        openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=CjRepoMesh synthetic CA",
                "-days", "1", "-keyout", "ca.key", "-out", "ca.pem", "-addext", "basicConstraints=critical,CA:TRUE")
        for number, (name, san) in enumerate((("good", "DNS:localhost,IP:127.0.0.1"),
                                              ("wrong", "DNS:wrong.invalid"),
                                              ("wrongip", "IP:127.0.0.2"),
                                              ("clientonly", "DNS:localhost,IP:127.0.0.1"),
                                              ('expired','DNS:localhost,IP:127.0.0.1')), 1):
            openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=" + ("localhost" if name in ('good','expired') else "wrong.invalid"),
                    "-keyout", name + ".key", "-out", name + ".csr")
            (cert / (name + ".ext")).write_text("subjectAltName=" + san + "\nextendedKeyUsage=" +
                ("clientAuth" if name == "clientonly" else "serverAuth") + "\n")
            openssl("x509", "-req", "-in", name + ".csr", "-CA", "ca.pem", "-CAkey", "ca.key",
                    "-set_serial", str(number), "-days", '-1' if name=='expired' else '1', "-extfile", name + ".ext", "-out", name + ".pem")
        for key in cert.glob("*.key"):
            key.chmod(0o600)
        (cert / "empty-trust-directory").mkdir()
        openssl('verify','-CAfile','ca.pem','-purpose','sslserver','good.pem')
        expiry=subprocess.run(['openssl','verify','-CAfile','ca.pem','-purpose','sslserver','expired.pem'],
            cwd=cert,capture_output=True,timeout=30)
        assert expiry.returncode!=0 and b'error 10 at 0 depth' in expiry.stdout+expiry.stderr,'expired leaf fixture was not validated'
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert / "good.pem", cert / "good.key")
        class HttpsServer(ThreadingHTTPServer):
            daemon_threads=True
            def get_request(self):
                raw,address=super().get_request();raw.settimeout(5)
                event=dict(case=mode,status='attempted')
                with handshake_changed:handshakes.append(event)
                try:connection=context.wrap_socket(raw,server_side=True)
                except OSError as failure:
                    with handshake_changed:
                        event.update(status='failed',reason=getattr(failure,'reason',type(failure).__name__))
                        handshake_changed.notify_all()
                    raw.close();raise
                with handshake_changed:
                    event.update(status='succeeded',tls=connection.version());handshake_changed.notify_all()
                return connection,address
        server = HttpsServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        servers.append(server)
        threads.append(thread)
        thread.start()
        origin = "https://127.0.0.1:" + str(server.server_port)
        sink = ThreadingHTTPServer(("127.0.0.1", 0), RedirectSink)
        sink.daemon_threads = True
        sink_thread = threading.Thread(target=sink.serve_forever, daemon=True)
        servers.append(sink)
        threads.append(sink_thread)
        sink_thread.start()
        sink_origin = "http://127.0.0.1:" + str(sink.server_port)
        definitions = [("trusted-index", "good", True, "doctor"),
                       ("untrusted-index", "good", False, "doctor"),
                       ("wrong-host-index", "wrong", True, "doctor"),
                       ("trusted-publish", "good", True, "publish"),
                       ("wrong-host-publish", "wrong", True, "publish"),
                       ("download-wrong-host", "good", True, "build"),
                       ("trusted-build-and-run", "good", True, "build"),
                       ("trusted-wrong-token", "good", True, "doctor"),
                       ("trusted-dns-name", "good", True, "doctor"),
                       ("wrong-ip-san", "wrongip", True, "doctor"),
                       ("wrong-dns-name", "wrong", True, "doctor"),
                       ("client-only-purpose", "clientonly", True, "doctor"),
                       ("redirect-index", "good", True, "doctor"),
                       ("redirect-publish", "good", True, "publish"),
                       ("redirect-download", "good", True, "build"),
                       ('expired-ip-index','expired',True,'doctor'),
                       ('expired-dns-index','expired',True,'doctor'),
                       ('expired-publish','expired',True,'publish'),
                       ('download-expired','good',True,'build')]
        if args.expiry_only:
            definitions=[d for d in definitions if d[0].startswith('expired-') or d[0]=='download-expired']
        assert len(definitions)==total
        for label, certificate, trust, operation in definitions:
            mode = label
            observations.clear()
            redirected.clear()
            context.load_cert_chain(cert / (certificate + ".pem"), cert / (certificate + ".key"))
            job = root / label
            job.mkdir()
            selected_origin = origin.replace("127.0.0.1", "localhost") if label in ("trusted-dns-name", "wrong-dns-name",'expired-dns-index') or label.startswith("redirect-") else origin
            publisher = operation == "publish"
            template = ROOT / "examples/team" / ("publisher" if publisher else "consumer")
            shutil.copyfile(template / "cjpm.toml", job / "cjpm.toml")
            shutil.copytree(template / "src", job / "src")
            config = '[repository.cache]\npath="cache"\n[repository.' + ("home" if publisher else "internal") + ']\n'
            config += 'registry=' + json.dumps(selected_origin) + '\ntoken-env="TLS_TEST_TOKEN"\n'
            if not publisher:
                config += '[[route]]\nnamespace="company::*"\nregistry="internal"\nexclusive=true\n'
            (job / "cangjie-repo.toml").write_text(config)
            if publisher:
                (job / "target").mkdir()
                for name in ("meta-data.json", "teamhello-1.0.0.cjp"):
                    shutil.copyfile(package / name, job / "target" / name)
            command = (client, "repo", "doctor", "company::teamhello") if operation == "doctor" else (client, operation)
            token = "synthetic-wrong-token" if label == "trusted-wrong-token" else publish_token if publisher else read_token
            code, output = run(job, command, trust=trust, token=token, label=label)
            should_succeed = label in ("trusted-index", "trusted-publish", "trusted-build-and-run", "trusted-dns-name")
            facts = dict(exit_matches=(code == 0) == should_succeed,
                         retained_log_redacted=read_token not in output and publish_token not in output,
                         requests=list(observations))
            if label.startswith("redirect-"):
                facts["redirect_target_not_contacted"] = not redirected
                facts["redirect_response_reached"] = any(r["status"] in (302, 307) for r in observations)
                facts["no_success_provenance"] = not (job / "cjpm-provenance.json").exists()
                facts["redirected_requests"] = list(redirected)
            elif should_succeed:
                facts["endpoint_reached"] = bool(observations) and all(r["authorized"] for r in observations)
            elif label == "trusted-wrong-token":
                facts["authentication_rejected"] = bool(observations) and "401" in output
            elif label in ('download-wrong-host','download-expired'):
                facts["index_only_before_identity_rejection"] = bool(observations) and all(r["path"].startswith("/index/") for r in observations)
                facts["no_success_provenance"] = not (job / "cjpm-provenance.json").exists()
            else:
                facts["no_http_before_identity_rejection"] = not observations
            if label.startswith('expired-') or label=='download-expired':
                with handshake_changed:
                    facts['expired_leaf_handshake_reached']=handshake_changed.wait_for(lambda:any(
                        h.get('case')==label and h.get('status')=='failed' and h.get('reason') in
                        ('SSLV3_ALERT_CERTIFICATE_EXPIRED','TLSV1_ALERT_CERTIFICATE_EXPIRED')
                        for h in handshakes),timeout=2)
            with handshake_changed:facts['handshakes']=[dict(h) for h in handshakes if h['case']==label]
            if label == "trusted-build-and-run" and code == 0:
                app_code, app_output = run(job, (job / "target/release/bin/main",), label="trusted-runtime")
                entry = json.loads((job / "cjpm-provenance.json").read_text())["packages"][0]
                facts["real_runtime"] = app_code == 0 and "CjRepoMesh team 1.0.0: CI" in app_output
                facts["provenance"] = entry["registry"] == origin and entry["sha256"] == metadata["index"]["sha256sum"]
            passed = all(value for key, value in facts.items() if key not in ("requests", "redirected_requests",'handshakes'))
            cases.append(dict(name=label, passed=passed, returncode=code, facts=facts))
            print(f"{'PASS' if passed else 'FAIL'} {len(cases)}/{total} {label}", flush=True)
    except (OSError, ValueError, KeyError, AssertionError, RuntimeError, subprocess.SubprocessError) as failure:
        error = str(failure) or type(failure).__name__
        print("FAIL TLS identity: " + error, flush=True)
    finally:
        try:
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=2)
            count = sum(case["passed"] for case in cases)
            success = not error and len(cases) == count == total
            summary = dict(success=success, passed=count, total=total, seconds=round(time.monotonic()-started,2), cases=cases,error=error,
                           inputs=dict(client_sha256=digest(client),runner_sha256=digest(Path(__file__)),archive_sha256=hashlib.sha256(artifact).hexdigest()),
                           limits=["Owned local Python HTTPS registry fixture, not a production gateway or deployed server.",
                                   "Linux SDK/client only; synthetic CA is scoped to child environment, system trust unchanged.",
                                   "Three automatic redirect refusal cases, not arbitrary redirect/proxy or complete PKI acceptance.",
                                   'Four expired-leaf stages only; no future-validity, expired-root, clock-change or revocation acceptance.',
                                   "No LAN/HTTPS reverse proxy or mTLS acceptance."])
            (report / "summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
        finally:
            shutil.rmtree(root)
    print(f"TLS identity: {count}/{total}; success={success}; report: {report}",flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
