#!/usr/bin/env python3
"""Verify named-registry URL changes cannot relabel and reuse another source's cache."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import time
import uuid

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from lib.harness import (  # noqa: E402
    TestFailure, assert_contains, assert_equal, assert_ports_available, remove_within,
    run_command, sha256, wait_for_ports_closed,
)
from showcase.run import AuditedHTTP  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", required=True, type=Path)
    parser.add_argument("--port", type=int, default=39760, help="first of three owned loopback ports")
    parser.add_argument("--evidence-dir", type=Path, help="new output directory")
    parser.add_argument("--retain-builds", action="store_true",
                        help="keep application targets, lockfiles and prior provenance during URL switches")
    parser.add_argument("--coarse-source-times", action="store_true",
                        help="normalize real test CJP timestamps equally across sources")
    parser.add_argument("--coarse-artifact-times", action="store_true",
                        help="normalize owned compiler CJO timestamps, preserving real compiler output and exit")
    parser.add_argument('--transitive', action='store_true', help='keep a local static bridge between app and changing registry package')
    args = parser.parse_args()
    if (args.coarse_source_times or args.coarse_artifact_times) and (not args.retain_builds or os.name == 'nt'):
        parser.error('coarse-time probes require retained builds and the Linux toolchain')
    client = args.cjpm.resolve()
    if not client.is_file() or not 1 <= args.port <= 65533:
        parser.error("an existing cjpm binary and three valid consecutive ports are required")
    ports = tuple(range(args.port, args.port + 3))
    assert_ports_available(ports)
    suffix = uuid.uuid4().hex
    parent = TESTS / ".tmp"
    root = parent / ("cache-identity-" + suffix)
    report = (args.evidence_dir or parent / ("cache-identity-report-" + suffix)).resolve()
    report.mkdir(parents=True, exist_ok=False)
    root.mkdir(parents=True)
    home = root / "home"
    home.mkdir()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("CJREPO_", "CJREPOMESH_")) and key != "CJPM_CONFIG"}
    env.update(HOME=str(home), USERPROFILE=str(home), CJREPOMESH_CACHE_TOKEN="upstream-read-fixture")
    cache = root / "shared-cache"
    urls = tuple(f"http://127.0.0.1:{port}" for port in ports)
    actors = []
    stages = []
    total = 7 if args.retain_builds else 6
    success, error = False, ""
    started = time.monotonic()
    inputs = dict(platform=sys.platform, client_sha256=sha256(client),
                  runner_sha256=sha256(Path(__file__)),
                  harness_sha256=sha256(TESTS / "lib/harness.py"),
                  http_fixture_sha256=sha256(TESTS / "showcase/run.py"))
    inputs.update(coarse_source_times=args.coarse_source_times, coarse_artifact_times=args.coarse_artifact_times)
    inputs['transitive_static_bridge'] = args.transitive

    def passed(name: str, **facts) -> None:
        stages.append(dict(name=name, status="PASS", facts=facts))
        print(f"PASS {len(stages)}/{total} {name}", flush=True)

    def registry(port: int, package: dict):
        actor = AuditedHTTP(port, packages=(package,))
        actors.append(actor)
        return actor

    def command(label: str, cwd: Path, *arguments: str, variables=None, expect_success=True):
        try:
            result = run_command((client, *arguments), cwd=cwd, env=variables or env,
                                 expect_success=expect_success, timeout=90)
        except TestFailure as failure:
            (report / (label + ".log")).write_text(str(failure), encoding="utf-8")
            raise
        (report / (label + ".log")).write_text(result.output, encoding="utf-8")
        return result

    def configure(app: Path, url: str, *, legacy=False) -> None:
        selected_cache = root / "legacy-cache" if legacy else cache
        app.joinpath("cangjie-repo.toml").write_text(
            '[repository.cache]\npath = "' + selected_cache.as_posix() + '"\n'
            f'[repository.{"home" if legacy else "internal"}]\nregistry = "{url}"\n'
            'token-env = "CJREPOMESH_CACHE_TOKEN"\n', encoding="utf-8")

    def fixture(relative: str, label: str, *, legacy=False) -> Path:
        destination = root / label
        destination.mkdir()
        original = TESTS / relative
        shutil.copyfile(original / "cjpm.toml", destination / "cjpm.toml")
        shutil.copytree(original / "src", destination / "src")
        if original.joinpath("README.md").is_file():
            shutil.copyfile(original / "README.md", destination / "README.md")
        configure(destination, urls[0], legacy=legacy)
        return destination

    def bundle(relative: str, label: str) -> dict:
        destination = fixture(relative, label)
        command("bundle-" + label, destination, "bundle")
        data = json.loads(destination.joinpath("target/meta-data.json").read_text(encoding="utf-8"))
        archives = list(destination.joinpath("target").glob("*.cjp"))
        assert_equal(len(archives), 1, label="one real archive")
        artifact = archives[0].read_bytes()
        assert_equal(hashlib.sha256(artifact).hexdigest(), data["index"]["sha256sum"], label="archive checksum")
        if args.coarse_source_times or args.coarse_artifact_times:
            # Change only test-copy tar timestamps; keep genuine CJP contents and
            # bind the fixture index to the resulting archive bytes.
            timestamp = 1700000000 + (60 if args.coarse_artifact_times and not args.coarse_source_times and label.startswith('source-b') else 0)
            output = io.BytesIO()
            with tarfile.open(fileobj=io.BytesIO(artifact), mode='r:*') as before, tarfile.open(fileobj=output, mode='w:gz') as after:
                for member in before.getmembers():
                    member.mtime = timestamp
                    member.pax_headers.pop('mtime', None)
                    after.addfile(member, before.extractfile(member) if member.isfile() else None)
            artifact = output.getvalue()
            data['index']['sha256sum'] = hashlib.sha256(artifact).hexdigest()
        return dict(name=data["name"], version=data["version"], organization=data["organization"],
                    index=data["index"], artifact=artifact)

    def reset_build(app: Path) -> None:
        if args.retain_builds:
            assert_equal(app.joinpath("target").is_dir(), True, label="existing application target retained")
            assert_equal(app.joinpath("cjpm.lock").is_file(), True, label="existing lockfile retained")
            assert_equal(app.joinpath("cjpm-provenance.json").is_file(), True, label="existing provenance retained")
            return
        # Keep all downloaded caches; only force a fresh application resolution/build.
        for name in ("target", "cjpm.lock", "cjpm-provenance.json"):
            remove_within(app / name, (root,))

    def provenance(app: Path, package: dict, url: str, *, legacy=False) -> None:
        document = json.loads(app.joinpath("cjpm-provenance.json").read_text(encoding="utf-8"))
        rows = document["packages"]
        assert_equal(len(rows), 1, label="one dependency")
        expected = dict(package="meshdep", version="1.0.0", repository="home" if legacy else "internal",
                        registry=url, sha256=package["index"]["sha256sum"])
        for field, value in expected.items():
            assert_equal(rows[0][field], value, label="provenance " + field)

    def compile_snapshot(app: Path, label: str) -> None:
        files = {}
        for directory in (app / 'target', cache):
            for path in directory.rglob('*'):
                if path.is_file():
                    info = path.stat()
                    files[path.relative_to(root).as_posix()] = dict(sha256=sha256(path), bytes=info.st_size,
                                                                   mtime_ns=info.st_mtime_ns)
        (report / (label + '.json')).write_text(json.dumps(files, indent=2), encoding='utf-8')

    try:
        first = bundle("multirepo/packages/meshdep-v1-high", "source-a-package")
        second = bundle("multirepo/packages/meshdep-v1-low", "source-b-package")
        assert first["index"]["sha256sum"] != second["index"]["sha256sum"]
        source_a = registry(ports[0], first)
        source_b = registry(ports[1], second)
        denied = registry(ports[2], second)
        app = fixture("multirepo/app-pinned", "named-consumer")
        if args.transitive:
            bridge = root / 'local-bridge'; bridge.mkdir()
            original = TESTS / 'multirepo/packages/meshbridge-v1'
            shutil.copyfile(original / 'cjpm.toml', bridge / 'cjpm.toml')
            shutil.copytree(original / 'src', bridge / 'src')
            config = (app / 'cjpm.toml').read_text()
            assert config.count('meshdep = "1.0.0"') == 1
            (app / 'cjpm.toml').write_text(config.replace('meshdep = "1.0.0"', 'meshbridge = { path = "../local-bridge" }'))
            source = (app / 'src/main.cj').read_text()
            assert source.count('import meshdep.*') == source.count('registryMarker()') == 1
            (app / 'src/main.cj').write_text(source.replace('import meshdep.*', 'import meshbridge.*').replace('registryMarker()', 'bridgeMarker()'))
        if args.coarse_source_times or args.coarse_artifact_times:
            compiler = shutil.which('cjc', path=env.get('PATH'))
            if not compiler: raise TestFailure('coarse-time probe requires the real cjc')
            toolchain = root / 'controlled-toolchain'; toolchain.mkdir()
            wrapper = toolchain / 'cjc'
            wrapper.write_text('#!' + sys.executable + '\n' +
                'from pathlib import Path\nimport json, os, subprocess, sys\n' +
                f'root=Path({str(root)!r})\nreal={compiler!r}\n' +
                'result=subprocess.run([real,*sys.argv[1:]])\n' +
                'artifacts=[]\n' +
                f'if result.returncode==0 and "-v" not in sys.argv and {args.coarse_artifact_times!r}:\n' +
                '    for path in root.rglob("*.cjo"):\n' +
                '        if path.is_file() and path.resolve().is_relative_to(root):\n' +
                '            os.utime(path,ns=(1700000000000000000,1700000000000000000))\n' +
                '            artifacts.append(path.relative_to(root).as_posix())\n' +
                f'with Path({str(report / "compiler-events.jsonl")!r}).open("a") as stream:\n' +
                '    stream.write(json.dumps(dict(exitCode=result.returncode,versionProbe="-v" in sys.argv,normalized=artifacts))+"\\n")\n' +
                'raise SystemExit(result.returncode)\n', encoding='utf-8')
            wrapper.chmod(0o755)
            inputs['compiler_wrapper_sha256'] = sha256(wrapper)
            env['PATH'] = str(toolchain) + os.pathsep + env['PATH']
        result = command("01-source-a", app, "run")
        assert_contains(result.output, "high-1.0.0")
        provenance(app, first, urls[0])
        compile_snapshot(app, 'source-a-compile-state')

        # Preserve a genuine warmed index/source pair in the historical name-only layout.
        # Discover the current location rather than duplicating the new hash algorithm.
        indexes = [path for path in cache.rglob("meshdep") if path.is_file()]
        assert_equal(len(indexes), 1, label="one warmed index")
        current = next(parent for parent in indexes[0].parents if parent.name == "index").parent
        historical = cache / "repository/registries/internal"
        if current != historical:
            for kind in ("index", "source"):
                shutil.copytree(current / kind, historical / kind)
        preserved = {path.relative_to(cache).as_posix(): sha256(path)
                     for path in cache.rglob("*") if path.is_file()}
        passed("named-source-a-and-historical-cache-warmed", checksum=first["index"]["sha256sum"])

        configure(app, urls[1])
        reset_build(app)
        result = command("02-switch-source-b", app, "run")
        compile_snapshot(app, 'source-b-compile-state')
        # Save observations before assertions so a baseline failure remains inspectable.
        (report / "switch-observation.json").write_text(json.dumps(dict(
            source_b_requests=source_b.requests,
            provenance=json.loads(app.joinpath("cjpm-provenance.json").read_text(encoding="utf-8"))),
            indent=2), encoding="utf-8")
        assert_contains(result.output, "low-1.0.0")
        provenance(app, second, urls[1])
        assert any(path.startswith("/pkg/meshdep/") for path in source_b.requests)
        for name, checksum in preserved.items():
            assert_equal(sha256(cache / name), checksum, label="previous cache retained")
        passed("same-name-new-url-downloads-real-source-b", checksum=second["index"]["sha256sum"],
               prior_cache_files_unchanged=len(preserved))

        if args.retain_builds:
            original_source = app.joinpath("src/main.cj").read_bytes()
            previous_record = sha256(app / "cjpm-provenance.json")
            configure(app, urls[0])
            source = original_source.decode("utf-8")
            assert_equal(source.count("return 0"), 1, label="one controlled return type error")
            try:
                app.joinpath("src/main.cj").write_text(
                    source.replace("return 0", 'return "type-error-fixture"'), encoding="utf-8")
                result = command("02b-resolution-before-compiler-failure", app, "build", expect_success=False)
                assert_contains(result.output, "Error: cjpm build failed")
                provenance(app, first, urls[0])
                assert sha256(app / "cjpm-provenance.json") != previous_record
                passed("resolution-record-is-not-a-compilation-success-receipt", compiler_failed=True,
                       record_updated_to_resolved_source=True)
            finally:
                app.joinpath("src/main.cj").write_bytes(original_source)

        source_a.close()
        source_b.close()
        wait_for_ports_closed(ports[:2])
        configure(app, urls[0])
        reset_build(app)
        result = command("03-return-source-a-offline", app, "run",
                         variables=dict(env, CJREPOMESH_CACHE_TOKEN="rotated-fixture-token"))
        assert_contains(result.output, "high-1.0.0")
        provenance(app, first, urls[0])
        passed("returning-url-reuses-its-own-offline-cache", token_rotation_does_not_partition_cache=True)

        configure(app, urls[2])
        previous_provenance = sha256(app / "cjpm-provenance.json")
        reset_build(app)
        result = command("04-new-url-denied", app, "build", expect_success=False,
                         variables=dict(env, CJREPOMESH_CACHE_TOKEN="wrong-fixture-token"))
        assert_contains(result.output, "status 401")
        assert denied.requests
        if args.retain_builds:
            assert_equal(sha256(app / "cjpm-provenance.json"), previous_provenance,
                         label="failed build preserves the previous successful provenance")
        else:
            assert_equal(app.joinpath("cjpm-provenance.json").exists(), False, label="no successful denied provenance")
        passed("new-url-401-cannot-use-old-url-cache", requests=len(denied.requests),
               previous_successful_record_preserved=args.retain_builds)

        restarted_a = registry(ports[0], first)
        legacy = fixture("multirepo/app-pinned", "legacy-consumer", legacy=True)
        result = command("05-legacy-home", legacy, "run")
        assert_contains(result.output, "high-1.0.0")
        provenance(legacy, first, urls[0], legacy=True)
        old_root = root / "legacy-cache/repository"
        assert_equal(old_root.joinpath("index/default/me/sh/meshdep").is_file(), True, label="legacy index layout")
        assert_equal(old_root.joinpath("registries").exists(), False, label="no legacy layout migration")
        passed("single-home-retains-compatible-layout")

        restarted_a.close()
        denied.close()
        wait_for_ports_closed(ports)
        reset_build(legacy)
        result = command("06-legacy-offline", legacy, "run")
        assert_contains(result.output, "high-1.0.0")
        provenance(legacy, first, urls[0], legacy=True)
        passed("single-home-same-url-offline-cache")
        success = True
    except (TestFailure, OSError, ValueError, KeyError, AssertionError) as failure:
        error = str(failure) or type(failure).__name__
        print("FAIL cache identity: " + error, flush=True)
    finally:
        for actor in reversed(actors):
            actor.close()
        result = dict(success=success, passed=len(stages), total=total, seconds=round(time.monotonic()-started, 2),
                      retain_application_builds=args.retain_builds,
                      inputs=inputs, stages=stages, error=error,
                      limits=["Local fixtures with real cjpm archives and builds; not an official test.",
                              "Token rotation does not revoke already downloaded local files.",
                              "Provenance records dependency resolution; compilation can still fail afterwards.",
                              "Legacy single home URL changes still require a new cache root."])
        report.joinpath("summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        report.joinpath("requests.json").write_text(json.dumps([actor.requests for actor in actors], indent=2), encoding="utf-8")
        if success:
            remove_within(root, (parent,))
        else:
            print(f"Failure fixtures retained: {root}", flush=True)
    print(f"Cache identity: {len(stages)}/{total}; success={success}; report: {report}", flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
