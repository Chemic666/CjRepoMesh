import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PORT = int(sys.argv[1])
REPOSITORY = sys.argv[2]
ROOT = Path(__file__).resolve().parent
LOG = ROOT / f"{REPOSITORY}.requests.log"


def fixtures():
    if REPOSITORY in (
        "high", "token", "artifact-unauthorized", "artifact-forbidden", "corrupt-high"
    ):
        return [ROOT / "packages" / "meshdep-v1-high"]
    if REPOSITORY in ("low", "corrupt"):
        return [
            ROOT / "packages" / "meshdep-v1-low",
            ROOT / "packages" / "meshdep-v2-low",
        ]
    if REPOSITORY == "legacy-mixed":
        return [
            ROOT / "packages" / "meshdep-v1-low",
            ROOT / "packages" / "meshdep-v2-low",
            ROOT / "packages" / "company-auth-v1-private",
        ]
    if REPOSITORY == "legacy-transitive":
        return [
            ROOT / "packages" / "meshdep-v1-low",
            ROOT / "packages" / "meshdep-v2-low",
            ROOT / "packages" / "meshbridge-v1",
            ROOT / "packages" / "meshbridge-v2",
        ]
    if REPOSITORY in ("transitive-high", "artifact-forbidden-transitive-high"):
        return [
            ROOT / "packages" / "meshdep-v1-high",
            ROOT / "packages" / "meshbridge-v2",
        ]
    if REPOSITORY in ("transitive-low", "artifact-forbidden-transitive-low"):
        return [
            ROOT / "packages" / "meshdep-v1-low",
            ROOT / "packages" / "meshdep-v2-low",
            ROOT / "packages" / "meshbridge-v1",
        ]
    if REPOSITORY == "private":
        return [ROOT / "packages" / "company-auth-v1-private"]
    if REPOSITORY == "public":
        return [ROOT / "packages" / "company-auth-v9-public"]
    if REPOSITORY in ("missing", "server-error", "unauthorized", "forbidden"):
        return []
    raise ValueError(f"unknown repository: {REPOSITORY}")


def metadata(package_dir):
    return json.loads((package_dir / "target" / "meta-data.json").read_text(encoding="utf-8"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def send_bytes(self, status, data, content_type="application/octet-stream"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        with LOG.open("a", encoding="utf-8") as request_log:
            request_log.write(f"GET {path}\n")
        forced_status = {
            "missing": 404,
            "server-error": 500,
            "unauthorized": 401,
            "forbidden": 403,
        }.get(REPOSITORY)
        if forced_status is not None:
            payload = json.dumps({"errors": [{"message": REPOSITORY}]}).encode("utf-8")
            self.send_bytes(forced_status, payload, "application/json")
            return
        if REPOSITORY == "token" and self.headers.get("Authorization") != "secret-token":
            self.send_bytes(401, b'{"errors":[{"message":"bad token"}]}', "application/json")
            return
        parts = [part for part in path.split("/") if part]
        if parts and parts[0] == "index":
            name = parts[-1]
            matches = [item for item in fixtures() if metadata(item)["name"] == name]
            if matches:
                payload = "".join(json.dumps(metadata(item)["index"]) + "\n" for item in matches)
                self.send_bytes(200, payload.encode("utf-8"), "application/json")
                return
        if len(parts) == 3 and parts[0] == "pkg":
            artifact_status = {
                "artifact-unauthorized": 401,
                "artifact-forbidden": 403,
                "artifact-forbidden-transitive-high": 403,
                "artifact-forbidden-transitive-low": 403,
            }.get(REPOSITORY)
            if artifact_status is not None:
                payload = json.dumps({"errors": [{"message": REPOSITORY}]}).encode("utf-8")
                self.send_bytes(artifact_status, payload, "application/json")
                return
            name = parts[1]
            version = parts[2]
            for item in fixtures():
                info = metadata(item)
                if info["name"] == name and info["version"] == version:
                    artifact = item / "target" / f"{name}-{version}.cjp"
                    payload = artifact.read_bytes()
                    if REPOSITORY in ("corrupt", "corrupt-high"):
                        payload = bytes([payload[0] ^ 0xFF]) + payload[1:]
                    self.send_bytes(200, payload)
                    return
        self.send_bytes(404, b'{"errors":[{"message":"not found"}]}', "application/json")


ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
