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
import extended


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
    return extended.make_fixture(number, version)


def select_item(items: list, sequence: int):
    """Visit each package before moving to its next version (four versions per package)."""
    packages = len(items) // 4
    return items[(sequence % packages) * 4 + (sequence // packages) % 4]


def measure_batch(label, workers, count, action, direction, *, phases, report, measurements):
    phase_start = measurements.start()
    def sample(number):
        begin = measurements.start()
        try:
            statuses, size, identity = action(number)
            result = dict(sequence=number, valid=True, httpStatuses=statuses,
                          artifactBytes=size, package=identity)
        except (TestFailure, OSError, ValueError, KeyError, TypeError) as failure:
            result = dict(sequence=number, valid=False, error=str(failure))
        timing = measurements.finish(begin)
        result.update(begin, endedAtUtc=timing['endedAtUtc'], endOffsetSeconds=timing['endOffsetSeconds'],
                      elapsedMs=timing['elapsedSeconds'] * 1000)
        return result
    with ThreadPoolExecutor(max_workers=workers) as pool:
        samples = [f.result() for f in as_completed([pool.submit(sample, n) for n in range(count)])]
    timing = measurements.finish(phase_start)
    elapsed = timing['elapsedSeconds']
    failures = sum(not item['valid'] for item in samples)
    phase = dict(name=label, concurrency=workers, operations=count, validOperations=count-failures,
                 failedOperations=failures, **phase_start, **timing,
                 operationsPerSecond=count/elapsed if elapsed > 0 else None,
                 artifactDirection=direction,
                 artifactMiBPerSecond=sum(s.get('artifactBytes', 0) for s in samples)/1048576/elapsed if elapsed > 0 else None,
                 httpRequests=sum(len(s.get('httpStatuses', [])) for s in samples),
                 packagesVisited=len({(s['package']['organization'],s['package']['name']) for s in samples if s['valid']}),
                 latency=distribution([s['elapsedMs'] for s in samples]),
                 samples=sorted(samples, key=lambda sample: sample['sequence']))
    phases.append(phase)
    (report / 'samples.json').write_text(json.dumps(phases, indent=2) + '\n', encoding='utf-8')
    if elapsed <= 0:
        raise TestFailure(f'{label}: non-positive measurement interval; see samples.json')
    print(f"MEASURE {label}: {count-failures}/{count}; {phase['operationsPerSecond']:.2f} ops/s; p95 {phase['latency']['p95Ms']:.2f}ms", flush=True)
    if failures:
        raise TestFailure(f'{label}: {failures} invalid operations; see samples.json')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="existing local Linux amd64 CjRepo server image")
    parser.add_argument("--evidence-dir", required=True, type=Path, help="new directory outside the source checkout")
    parser.add_argument("--read-operations", type=int, default=128, help="read pairs per comparison phase, 32..1024")
    parser.add_argument("--large-fixtures", action="store_true", help="also check 16MiB artifacts and a near-4MiB index")
    parser.add_argument("--soak-seconds", type=int, default=0, help="optional paced mixed load, 60..1800 seconds (0 disables)")
    args = parser.parse_args()
    if not 32 <= args.read_operations <= 1024:
        parser.error("read-operations must be between 32 and 1024")
    if args.soak_seconds != 0 and not 60 <= args.soak_seconds <= 1800:
        parser.error("soak-seconds must be 0 or between 60 and 1800")
    report = args.evidence_dir.resolve()
    if report == ROOT or ROOT in report.parents:
        parser.error("retain raw capacity evidence outside the source checkout")
    report.mkdir(parents=True, exist_ok=False)
    scope = "cjrepomesh-capacity-" + uuid.uuid4().hex
    label_key = "io.cjrepomesh.capacity-drill"
    (report / 'scope.json').write_text(json.dumps(dict(labelKey=label_key, scope=scope))+'\n', encoding='utf-8')
    environment = {k: v for k, v in os.environ.items()
                   if not k.upper().startswith(("CJREPO_", "CJREPOMESH_", "COMPOSE_"))}
    environment.update(CJREPO_PUBLISH_TOKEN=secrets.token_hex(32), CJREPO_READ_TOKEN=secrets.token_hex(32))
    secrets_used = [environment["CJREPO_PUBLISH_TOKEN"], environment["CJREPO_READ_TOKEN"]]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    containers, volumes, phases, stages, cleanup_errors, peaks = [], [], [], [], [], []
    total_stages = 10 + 2 * int(args.large_fixtures) + int(bool(args.soak_seconds))
    index_hashes, complete_indexes, resource_samples = {}, {}, []
    soak = dict(requestedSeconds=args.soak_seconds, intervalSeconds=5, rounds=0, elapsedSeconds=0)
    large_details = {}
    items = []
    runtime, error, success = {}, "", False
    measurements = extended.MeasurementClock()
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
        print(f"PASS {len(stages)}/{total_stages} {name}", flush=True)

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
        key = (item['organization'], item['name'])
        if key in complete_indexes:
            extended.validate_complete_index(index.body, complete_indexes[key])
        else:
            validate_index(index.body, item)
        index_hashes[f"index/{item['organization'] or 'default'}/{item['name'][:2]}/{item['name'][2:4]}/{item['name']}"] = hashlib.sha256(index.body).hexdigest()
        if hashlib.sha256(artifact.body).hexdigest() != item["sha256"] or artifact.body != item["body"]:
            raise TestFailure("download or index differs from immutable source fixture")
        return [index.status, artifact.status], len(artifact.body), {k:item[k] for k in ("name", "version", "organization")}

    def batch(label, workers, count, action, direction):
        measure_batch(label, workers, count, action, direction,
                      phases=phases, report=report, measurements=measurements)

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
        info = inspect(server)
        if info['State']['OOMKilled'] or not info['State']['Running'] or info['RestartCount']:
            raise TestFailure('server exited, restarted or was OOM-killed during load')
        host = info['HostConfig']
        if (host['Memory'] != 1073741824 or host['NanoCpus'] != 2000000000 or host['PidsLimit'] != 256):
            raise TestFailure('resource limits changed during load')
        result = subprocess.run(["docker", "exec", server, "cat", "/sys/fs/cgroup/memory.peak"],
                                env=environment, capture_output=True, text=True, timeout=15)
        peak = int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip().isdigit() else None
        peaks.append(peak)
        stats = json.loads(docker("stats", "--no-stream", "--format", "{{json .}}", server))
        current = docker('exec', server, 'cat', '/sys/fs/cgroup/memory.current', '/sys/fs/cgroup/pids.current').decode().split()
        sample = dict(elapsedSeconds=round(measurements.elapsed(), 2), cgroupMemoryPeakBytes=peak,
                      cgroupMemoryCurrentBytes=int(current[0]), cgroupPidsCurrent=int(current[1]),
                      endSnapshot={key:stats.get(key) for key in ("CPUPerc", "MemUsage", "PIDs", "BlockIO", "NetIO")})
        resource_samples.append(sample)
        (report / 'resources.json').write_text(json.dumps(resource_samples, indent=2)+'\n', encoding='utf-8')
        return sample

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
        if args.large_fixtures:
            large = extended.large_fixtures()
            batch('publish-16MiB-artifacts', 1, len(large), lambda n: publish(large[n]), 'send')
            items.extend(large)
            index_items = extended.index_fixtures()
            batch('grow-near-4MiB-index', 1, 63, lambda n: publish(index_items[n]), 'send')
            complete_indexes[(index_items[0]['organization'], index_items[0]['name'])] = index_items[:63]
            items.extend(index_items[:63])
            batch('read-large-artifacts', 2, 8, lambda n: read(large[n % 4]), 'receive')
            batch('read-near-limit-index', 2, 4, lambda n: read(index_items[n]), 'receive')
            index_before = request(index_items[0]['index'], environment['CJREPO_READ_TOKEN']).body
            if not 3.9 * 1048576 < len(index_before) <= 4 * 1048576:
                raise TestFailure('large index did not approach the default 4MiB byte limit')
            large_details = dict(artifactBytes=16*1048576, artifactVersions=4,
                                 indexBytes=len(index_before), indexVersions=63, rejectedVersion=index_items[-1]['version'])
            passed('large-artifacts-and-near-limit-index-verified', **large_details)
            batch('reject-next-large-index-version', 1, 1, lambda n: publish(index_items[-1], expected=413), 'send')
            if request(index_items[0]['index'], environment['CJREPO_READ_TOKEN']).body != index_before:
                raise TestFailure('oversized-index rejection changed existing bytes')
            if request(index_items[-1]['download'], environment['CJREPO_READ_TOKEN']).status != 404:
                raise TestFailure('oversized-index rejection left a visible artifact')
            passed('cumulative-index-limit-rejection-preserves-existing-storage')
        if args.soak_seconds:
            soak_start = time.monotonic()
            stream = []
            soak_rounds = []
            last_resource = float('-inf')
            for number in extended.paced_rounds(args.soak_seconds):
                with extended.record_soak_round(report, soak_rounds, number, measurements) as record:
                    item = extended.stream_fixture(number)
                    record['phaseNames'].append(f'soak-{number:03d}-publish')
                    batch(f'soak-{number:03d}-publish', 1, 1, lambda n: publish(item), 'send')
                    stream.append(item)
                    complete_indexes[(item['organization'], item['name'])] = stream
                    items.append(item)
                    selected = [large[number % 4] if args.large_fixtures else items[number % 256],
                                index_items[number % 63] if args.large_fixtures else items[(number+1) % 256],
                                item, items[(number*4) % 256], items[(number*4+1) % 256], items[(number*4+2) % 256]]
                    def mixed(n):
                        if n == 6:
                            return publish(items[number % 256], expected=409)
                        if n == 7:
                            return publish(item, expected=401, token='synthetic-invalid-publish')
                        return read(selected[n])
                    record['phaseNames'].append(f'soak-{number:03d}-mixed')
                    batch(f'soak-{number:03d}-mixed', 8, 8, mixed, 'mixed')
                    soak['rounds'] = number+1
                    if time.monotonic() - last_resource >= 30:
                        runtime_sample(server)
                        last_resource = time.monotonic()
            soak['elapsedSeconds'] = round(time.monotonic()-soak_start, 2)
            if soak['elapsedSeconds'] < args.soak_seconds or not soak['rounds']:
                raise TestFailure('soak did not run for its requested duration')
            passed('paced-mixed-soak-completed-without-invalid-operations', **soak)
        batch("verify-all-before-restart", 8, len(items), lambda n: read(items[n]), "receive")
        runtime["beforeRestart"] = runtime_sample(server)
        passed("every-published-version-and-index-verified-after-load")
        docker("stop", "--time", "5", server)
        save_log(server, "server-before-restart")
        wait_for_ports_closed((port,))
        first = snapshot(image, volume, report / "after-load.tar")
        expected_artifacts = {f"artifacts/{item['organization'] or 'default'}/{item['name']}/{item['version']}/{item['name']}-{item['version']}.cjp":item["sha256"] for item in items}
        if first != dict(expected_artifacts, **index_hashes):
            raise TestFailure("persisted exact file set or artifact/index digest differs from verified source")
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
        success = len(stages) == total_stages
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
        summary = dict(measurementFormatVersion=2,
                       success=success,passed=len(stages),total=total_stages,seconds=round(measurements.elapsed(),2),
                       recordedAtUtc=recorded_at,scope=scope,runtime=runtime,stages=stages,error=error,
                       cleanup_errors=cleanup_errors,retained_volumes=volumes if not success else [],
                       runnerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       extendedSha256=hashlib.sha256(Path(extended.__file__).read_bytes()).hexdigest(),
                       soak=soak,largeFixtures=large_details,resourceSamples=len(resource_samples),
                       workload=dict(packageSteps=[1,16,64],versionsPerPackage=4,artifactBytes=262144,
                                     baseArtifactBytes=67108864,totalArtifactBytes=sum(len(item['body']) for item in items),
                                     finalVersions=len(items),finalPackages=len({(item['organization'],item['name']) for item in items}),
                                     readOperationsPerComparison=args.read_operations,
                                     syntheticProtocolBytes=True),
                       phaseSummary=[{k:v for k,v in phase.items() if k != "samples"} for phase in phases],
                       limits=["One bounded local Docker Desktop workload; no saturation search, SLA or user-count estimate.",
                               "Synthetic protocol payloads are not buildable CJP archives; no client compilation.",
                               "Latency includes local Python/HTTP transport and verification; each read operation is index plus artifact.",
                               "Warm reads after publish; no cold disk, external network, Proxy or TLS measurement.",
                               "Cgroup memory peak is reported only if available; end CPU/memory snapshots are not sampled peaks.",
                               "No Windows Cangjie, downloads, installations, production data or network policy changes."])
        (report / "summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print(f"Capacity workload: {len(stages)}/{total_stages}; success={success}; report: {report}",flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
