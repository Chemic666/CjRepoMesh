#!/usr/bin/env python3
"""Bounded single-instance Hosted workload; synthetic protocol bytes, not buildable CJPs."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import secrets
import socket
import statistics
import subprocess
import sys
import tarfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integration-tests"))
sys.path.insert(0, str(ROOT / "integration-tests/recovery"))
from lib.harness import TestFailure, http_request as harness_http_request, publish_frame, wait_for_health, wait_for_ports_closed
from docker_backup import archive_manifest


def http_request(method, url, *, headers=None, body=None, timeout=30):
    try:
        return harness_http_request(method, url, headers=headers, body=body, timeout=timeout)
    except HTTPException as failure:
        raise TestFailure("incomplete HTTP response or invalid HTTP protocol") from failure


def validate_index(body: bytes, item: dict) -> None:
    rows = [json.loads(line) for line in body.splitlines() if line]
    if any(not isinstance(row, dict) or not isinstance(row.get("version"), str) for row in rows):
        raise TestFailure("invalid index row shape")
    selected = [row for row in rows if row["version"] == item["version"]]
    if (len(rows) != 4 or len({row["version"] for row in rows}) != 4 or
            len(selected) != 1 or selected[0] != item["metadata"]["index"]):
        raise TestFailure("complete index record differs from immutable source fixture")


def distribution(values: list[float]) -> dict:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot summarize an empty workload")
    return dict(minMs=ordered[0], p50Ms=ordered[math.ceil(len(ordered) * .50) - 1],
                p95Ms=ordered[math.ceil(len(ordered) * .95) - 1],
                p99Ms=ordered[math.ceil(len(ordered) * .99) - 1], maxMs=ordered[-1],
                meanMs=statistics.mean(ordered))


def fixture(number: int, version: int) -> dict:
    name, ver = f"capacity_{number:03d}", f"1.0.{version}"
    org = "benchcorp" if number % 2 else ""
    body = hashlib.shake_256(f"CjRepoMesh capacity/{org}/{name}/{ver}".encode()).digest(256 * 1024)
    checksum = hashlib.sha256(body).hexdigest()
    index = dict(name=name, version=ver, organization=org, sha256sum=checksum, dependencies=[])
    metadata = dict(name=name, version=ver, organization=org, index=index)
    query = "?organization=" + org if org else ""
    return dict(name=name, version=ver, organization=org, body=body, sha256=checksum, metadata=metadata,
                publish=f"/pkg/{name}{query}", download=f"/pkg/{name}/{ver}{query}",
                index=f"/index/{name[:2]}/{name[2:4]}/{name}{query}")


def select_item(items: list, sequence: int):
    """Visit each package before moving to its next version (four versions per package)."""
    packages = len(items) // 4
    return items[(sequence % packages) * 4 + (sequence // packages) % 4]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="existing local Linux amd64 CjRepo server image")
    parser.add_argument("--evidence-dir", required=True, type=Path, help="new directory outside the source checkout")
    parser.add_argument("--read-operations", type=int, default=128, help="read pairs per comparison phase, 32..1024")
    args = parser.parse_args()
    if not 32 <= args.read_operations <= 1024:
        parser.error("read-operations must be between 32 and 1024")
    report = args.evidence_dir.resolve()
    if report == ROOT or ROOT in report.parents:
        parser.error("retain raw capacity evidence outside the source checkout")
    report.mkdir(parents=True, exist_ok=False)
    scope = "cjrepomesh-capacity-" + uuid.uuid4().hex
    label_key = "io.cjrepomesh.capacity-drill"
    environment = {k: v for k, v in os.environ.items()
                   if not k.upper().startswith(("CJREPO_", "CJREPOMESH_", "COMPOSE_"))}
    environment.update(CJREPO_PUBLISH_TOKEN=secrets.token_hex(32), CJREPO_READ_TOKEN=secrets.token_hex(32))
    secrets_used = [environment["CJREPO_PUBLISH_TOKEN"], environment["CJREPO_READ_TOKEN"]]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    containers, volumes, phases, stages, cleanup_errors, peaks = [], [], [], [], [], []
    runtime, error, success = {}, "", False
    started = time.monotonic()
    recorded_at = datetime.now(timezone.utc).isoformat()

    def docker(*arguments, stdout=subprocess.PIPE, timeout=60):
        result = subprocess.run(["docker", *map(str, arguments)], env=environment,
                                stdout=stdout, stderr=subprocess.PIPE, timeout=timeout)
        if result.returncode:
            raise TestFailure(f"docker {arguments[0]} failed with exit {result.returncode}")
        return result.stdout or b""

    def inspect(identifier):
        return json.loads(docker("inspect", identifier))[0]

    def passed(name, **facts):
        stages.append(dict(name=name, facts=facts))
        print(f"PASS {len(stages)}/10 {name}", flush=True)

    def request(path, token, body=None):
        response = http_request("POST" if body is not None else "GET", base + path,
                                headers={"Authorization": token}, body=body, timeout=30)
        return response

    def publish(item, expected=200, token=None, conflict=False):
        body = item["body"]
        metadata = item["metadata"]
        if conflict:
            body = bytes([body[0] ^ 1]) + body[1:]
            metadata = dict(metadata, index=dict(metadata["index"], sha256sum=hashlib.sha256(body).hexdigest()))
        frame = publish_frame(json.dumps(metadata, separators=(",", ":")).encode(), body)
        response = request(item["publish"], token or environment["CJREPO_PUBLISH_TOKEN"], frame)
        if response.status != expected:
            raise TestFailure(f"publication returned {response.status}, expected {expected}")
        return [response.status], len(body), {k:item[k] for k in ("name", "version", "organization")}

    def read(item):
        index = request(item["index"], environment["CJREPO_READ_TOKEN"])
        artifact = request(item["download"], environment["CJREPO_READ_TOKEN"])
        if index.status != 200 or artifact.status != 200:
            raise TestFailure(f"read returned {index.status}/{artifact.status}")
        validate_index(index.body, item)
        if hashlib.sha256(artifact.body).hexdigest() != item["sha256"] or artifact.body != item["body"]:
            raise TestFailure("download or index differs from immutable source fixture")
        return [index.status, artifact.status], len(artifact.body), {k:item[k] for k in ("name", "version", "organization")}

    def batch(label, workers, count, action, direction):
        wall_start = time.perf_counter()
        def sample(number):
            begin = time.perf_counter()
            try:
                statuses, size, identity = action(number)
                return dict(sequence=number, elapsedMs=(time.perf_counter() - begin) * 1000,
                            valid=True, httpStatuses=statuses, artifactBytes=size, package=identity)
            except (TestFailure, OSError, ValueError, KeyError, TypeError) as failure:
                return dict(sequence=number, elapsedMs=(time.perf_counter() - begin) * 1000,
                            valid=False, error=str(failure))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            samples = [f.result() for f in as_completed([pool.submit(sample, n) for n in range(count)])]
        elapsed = time.perf_counter() - wall_start
        failures = sum(not item["valid"] for item in samples)
        phase = dict(name=label, concurrency=workers, operations=count, validOperations=count-failures,
                     failedOperations=failures, elapsedSeconds=elapsed, operationsPerSecond=count/elapsed,
                     artifactDirection=direction, artifactMiBPerSecond=sum(s.get("artifactBytes", 0) for s in samples)/1048576/elapsed,
                     httpRequests=sum(len(s.get("httpStatuses", [])) for s in samples),
                     packagesVisited=len({(s["package"]["organization"],s["package"]["name"]) for s in samples if s["valid"]}),
                     latency=distribution([s["elapsedMs"] for s in samples]),
                     samples=sorted(samples, key=lambda sample: sample["sequence"]))
        phases.append(phase)
        (report / "samples.json").write_text(json.dumps(phases, indent=2) + "\n", encoding="utf-8")
        print(f"MEASURE {label}: {count-failures}/{count}; {count/elapsed:.2f} ops/s; p95 {phase['latency']['p95Ms']:.2f}ms", flush=True)
        if failures:
            raise TestFailure(f"{label}: {failures} invalid operations; see samples.json")

    def save_log(identifier, name):
        result = subprocess.run(["docker", "logs", identifier], env=environment, capture_output=True, timeout=30)
        if result.returncode:
            raise TestFailure("cannot retain owned container log")
        output = (result.stdout + result.stderr).decode(errors="replace")
        for secret in secrets_used:
            output = output.replace(secret, "[REDACTED]")
        (report / (name + ".log")).write_text(output, encoding="utf-8")

    def create(image, volume=None, *, server=False):
        options = ["create", "--pull=never", "--label", label_key + "=" + scope, "--read-only",
                   "--cap-drop=ALL", "--security-opt", "no-new-privileges:true"]
        if volume:
            options += ["--mount", "type=volume,source=" + volume + ",target=/var/lib/cjrepo" +
                        ("" if server else ",readonly")]
        if server:
            options += ["--cpus=2", "--memory=1g", "--pids-limit=256", "--init",
                        "--tmpfs", "/tmp:size=16m,mode=1777", "--publish", f"127.0.0.1:{port}:8080",
                        "--env", "CJREPO_ADDRESS=0.0.0.0", "--env", "CJREPO_PORT=8080",
                        "--env", "CJREPO_STORAGE=/var/lib/cjrepo", "--env", "CJREPO_PUBLISH_TOKEN",
                        "--env", "CJREPO_READ_TOKEN", "--env", "CJREPO_UPSTREAM=", "--env", "CJREPO_UPSTREAM_TOKEN="]
        else:
            options += ["--network=none", "--entrypoint", "sha256sum" if not volume else "/bin/tar"]
        command = ("/usr/local/bin/cjrepo",) if not volume else ("-C", "/var/lib/cjrepo", "-cf", "-", ".")
        identifier = docker(*options, image, *(command if not server else ())).decode().strip()
        containers.append(identifier)
        return identifier

    def snapshot(image, volume, target):
        if docker("ps", "-q", "--filter", "volume=" + volume).strip():
            raise TestFailure("stop all test volume mounts before snapshot")
        helper = create(image, volume)
        with target.open("xb") as stream:
            docker("start", "--attach", helper, stdout=stream)
        return archive_manifest(target)

    def runtime_sample(server):
        result = subprocess.run(["docker", "exec", server, "cat", "/sys/fs/cgroup/memory.peak"],
                                env=environment, capture_output=True, text=True, timeout=15)
        peak = int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip().isdigit() else None
        peaks.append(peak)
        stats = json.loads(docker("stats", "--no-stream", "--format", "{{json .}}", server))
        return dict(cgroupMemoryPeakBytes=peak,
                    endSnapshot={key:stats.get(key) for key in ("CPUPerc", "MemUsage", "PIDs", "BlockIO", "NetIO")})

    try:
        image_info = json.loads(docker("image", "inspect", args.image))[0]
        if image_info["Os"] != "linux" or image_info["Architecture"] != "amd64":
            raise TestFailure("requires an existing Linux amd64 server image")
        image = image_info["Id"]
        helper = create(image)
        binary_sha = docker("start", "--attach", helper).decode().split()[0]
        volume = scope + "-data"
        docker("volume", "create", "--label", label_key + "=" + scope, volume)
        volumes.append(volume)
        server = create(image, volume, server=True)
        docker("start", server)
        wait_for_health(port)
        info = inspect(server)
        config = info["HostConfig"]
        if (info["Image"] != image or info["Config"]["User"] != "10001:10001" or
                config["Memory"] != 1073741824 or config["NanoCpus"] != 2000000000 or config["PidsLimit"] != 256 or
                not config["ReadonlyRootfs"] or "ALL" not in config["CapDrop"] or
                not any(value.startswith("no-new-privileges") for value in config["SecurityOpt"]) or
                info["NetworkSettings"]["Ports"]["8080/tcp"] != [dict(HostIp="127.0.0.1",HostPort=str(port))] or
                [m["Name"] for m in info["Mounts"] if m["Destination"] == "/var/lib/cjrepo"] != [volume]):
            raise TestFailure("runtime does not match the fixed resource and isolation settings")
        runtime = dict(image=image, serverSha256=binary_sha, limits=dict(cpus=2,memoryBytes=1073741824,pids=256),
                       dockerEngine=json.loads(docker("version", "--format", "{{json .Server}}"))["Version"],
                       engineHost=docker("info", "--format", "{{.NCPU}} {{.MemTotal}} {{.OSType}}").decode().strip())
        passed("fixed-image-runtime-and-resource-limits-verified")
        items, current = [], 0
        for package_count in (1, 16, 64):
            extra = [fixture(number, version) for number in range(current, package_count) for version in range(4)]
            batch(f"publish-growth-{package_count}", 8, len(extra), lambda n: publish(extra[n]), "send")
            items.extend(extra)
            workers_list = (1, 8, 32) if package_count == 64 else (8,)
            for workers in workers_list:
                batch(f"read-{package_count}-packages-c{workers}", workers, args.read_operations,
                      lambda n: read(select_item(items, n)), "receive")
            passed(f"growth-{package_count}-packages-four-versions-integrity-checked",
                   artifacts=len(items), artifactBytes=len(items)*256*1024)
            current = package_count
        # Keep immutable-write checks within the default eight publish slots.
        # Admission overload is a separate429 scenario, not a duplicate409.
        batch("immutable-duplicate-rejection", 8, 32, lambda n: publish(items[n], expected=409), "send")
        batch("immutable-conflict-rejection", 8, 32,
              lambda n: publish(items[n], expected=409, conflict=True), "send")
        passed("concurrent-duplicate-and-conflicting-publications-rejected")
        batch("mixed-read-and-invalid-publish", 8, args.read_operations,
              lambda n: publish(select_item(items, n), expected=401, token="synthetic-invalid-publish")
              if n % 8 == 0 else read(select_item(items, n)), "mixed")
        if request(items[0]["download"], "synthetic-invalid-read").status != 401:
            raise TestFailure("invalid read token unexpectedly succeeded")
        passed("mixed-reads-and-rejected-publishes-preserve-authentication")
        batch("verify-all-before-restart", 8, len(items), lambda n: read(items[n]), "receive")
        runtime["beforeRestart"] = runtime_sample(server)
        passed("every-published-version-and-index-verified-after-load")
        docker("stop", "--time", "5", server)
        save_log(server, "server-before-restart")
        wait_for_ports_closed((port,))
        first = snapshot(image, volume, report / "after-load.tar")
        if len(first) != 320:
            raise TestFailure("stored file set differs from 64 indexes and 256 artifacts")
        expected_artifacts = {f"artifacts/{item['organization'] or 'default'}/{item['name']}/{item['version']}/{item['name']}-{item['version']}.cjp":item["sha256"] for item in items}
        if any(first.get(key) != value for key, value in expected_artifacts.items()):
            raise TestFailure("persisted artifact digest differs from synthetic source")
        (report / "storage-manifest.json").write_text(json.dumps(first, indent=2) + "\n")
        passed("stopped-storage-file-set-and-all-artifact-hashes-verified", files=len(first))
        docker("start", server)
        wait_for_health(port)
        batch("verify-all-after-restart", 8, len(items), lambda n: read(items[n]), "receive")
        runtime["afterRestart"] = runtime_sample(server)
        passed("all-versions-remain-readable-after-container-restart")
        docker("stop", "--time", "5", server)
        save_log(server, "server-after-restart")
        if snapshot(image, volume, report / "after-restart.tar") != first:
            raise TestFailure("restart or read load changed stored bytes")
        state = inspect(server)["State"]
        if state["OOMKilled"] or state["Running"]:
            raise TestFailure("server was OOM-killed or remains running")
        runtime["availableCgroupPeakBytes"] = max((v for v in peaks if v is not None), default=None)
        passed("restart-preserves-entire-storage-without-observed-oom")
        success = len(stages) == 10
    except (TestFailure, OSError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.SubprocessError) as failure:
        error = str(failure) or type(failure).__name__
        print("FAIL capacity workload: " + error, flush=True)
    finally:
        for identifier in reversed(containers):
            try:
                if inspect(identifier)["Config"]["Labels"].get(label_key) != scope:
                    raise TestFailure("owned container label mismatch")
                if not success:
                    save_log(identifier, "failure-" + identifier[:12])
                docker("rm", "--force", identifier)
            except (TestFailure, OSError, ValueError, KeyError, subprocess.SubprocessError) as failure:
                cleanup_errors.append(str(failure))
                try:
                    if inspect(identifier)["Config"]["Labels"].get(label_key) == scope:
                        docker("stop", "--time", "5", identifier)
                except (TestFailure, OSError, ValueError, KeyError, subprocess.SubprocessError):
                    pass
        if success and not cleanup_errors:
            for volume in volumes:
                try:
                    if json.loads(docker("volume", "inspect", volume))[0]["Labels"].get(label_key) != scope:
                        raise TestFailure("owned volume label mismatch")
                    docker("volume", "rm", volume)
                except (TestFailure, OSError, ValueError, KeyError, subprocess.SubprocessError) as failure:
                    cleanup_errors.append(str(failure))
        success = success and not cleanup_errors
        summary = dict(success=success,passed=len(stages),total=10,seconds=round(time.monotonic()-started,2),
                       recordedAtUtc=recorded_at,scope=scope,runtime=runtime,stages=stages,error=error,
                       cleanup_errors=cleanup_errors,retained_volumes=volumes if not success else [],
                       runnerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       workload=dict(packageSteps=[1,16,64],versionsPerPackage=4,artifactBytes=262144,
                                     totalArtifactBytes=67108864,readOperationsPerComparison=args.read_operations,
                                     syntheticProtocolBytes=True),
                       phaseSummary=[{k:v for k,v in phase.items() if k != "samples"} for phase in phases],
                       limits=["One bounded local Docker Desktop workload; no saturation search, SLA or user-count estimate.",
                               "Synthetic protocol payloads are not buildable CJP archives; no client compilation.",
                               "Latency includes local Python/HTTP transport and verification; each read operation is index plus artifact.",
                               "Warm reads after publish; no cold disk, external network, Proxy or TLS measurement.",
                               "Cgroup memory peak is reported only if available; end CPU/memory snapshots are not sampled peaks.",
                               "No Windows Cangjie, downloads, installations, production data or network policy changes."])
        (report / "summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print(f"Capacity workload: {len(stages)}/10; success={success}; report: {report}",flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
