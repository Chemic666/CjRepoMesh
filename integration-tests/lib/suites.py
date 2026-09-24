from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable

from .harness import (
    ManagedProcesses,
    TestFailure,
    assert_contains,
    assert_equal,
    assert_ports_available,
    http_request,
    publish_frame,
    python_command,
    remove_within,
    run_command,
    sha256,
    wait_for_health,
    wait_for_port,
    wait_for_ports_closed,
)


CORE_PORTS = tuple(range(39141, 39148)) + (39200, 39201, 39202, 39300, 39301, 39302, 39303, 39304, 39305, 39306, 39307, 39401, 39501, 39502, 39503, 39504)


class TestContext:
    def __init__(self, project_root: Path, cjpm: Path, server: Path, *, build: bool) -> None:
        self.project_root = project_root.resolve()
        self.tests_root = (self.project_root / "integration-tests").resolve()
        self.multirepo_root = self.tests_root / "multirepo"
        self.server_root = self.project_root / "server"
        self.cjpm = cjpm.resolve()
        self.server = server.resolve()
        self.build = build
        self.env = dict(os.environ)
        for key in tuple(self.env):
            if key.startswith("CJREPO_") or key in {
                "CJREPOMESH_PUBLISH_TOKEN",
                "CJREPOMESH_TEST_TOKEN",
            }:
                self.env.pop(key)
        self._bundled: set[str] = set()
        self._server_ready = False
        self._temp_parent = self.tests_root / ".tmp"
        self._temp_parent.mkdir(exist_ok=True)
        self.temp_root = (
            self._temp_parent / f"run-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        ).resolve()
        self.temp_root.mkdir()

    def close(self) -> None:
        self.cleanup_generated()
        if self.temp_root.exists():
            shutil.rmtree(self.temp_root)
        try:
            self._temp_parent.rmdir()
        except OSError:
            pass

    def cleanup_generated(self) -> None:
        generated: list[Path] = []
        for package in (
            "meshdep-v1-high",
            "meshdep-v1-low",
            "meshdep-v2-low",
            "meshbridge-v1",
            "meshbridge-v2",
            "meshleaf-v1",
            "company-auth-v1-private",
            "company-auth-v9-public",
            "otherdep-v1",
        ):
            root = self.multirepo_root / "packages" / package
            generated.extend((root / "target", root / "cache", root / "cjpm.lock", root / "cjpm-provenance.json"))
        for app in (
            "app",
            "app-pinned",
            "app-replace",
            "app-replace-fallback",
            "app-replace-invalid",
            "app-fallback",
            "app-auth-barrier",
            "app-token",
            "app-namespace",
            "app-legacy",
        ):
            root = self.multirepo_root / app
            generated.extend(
                (root / "target", root / "cache", root / "cjpm.lock", root / "cjpm-provenance.json")
            )
        for suite in ("hosted-server", "proxy", "sync"):
            apps = ("app", "private-app", "org-package", "org-app", "org-private-app") if suite == "hosted-server" else (("app", "org-app") if suite in ("proxy", "sync") else ("app",))
            for name in apps:
                app = self.tests_root / suite / name
                generated.extend((app / "target", app / "cache", app / "cjpm.lock", app / "cjpm-provenance.json"))
        generated.extend(self.multirepo_root.glob("*.requests.log"))
        for path in generated:
            remove_within(path, (self.tests_root,))

    def reset_app(self, app: Path) -> None:
        for name in ("target", "cache", "cjpm.lock", "cjpm-provenance.json"):
            remove_within(app / name, (self.tests_root,))

    def bundle(self, package: str) -> Path:
        root = self.multirepo_root / "packages" / package
        if package not in self._bundled:
            run_command((self.cjpm, "bundle"), cwd=root, env=self.env)
            self._bundled.add(package)
        return root

    def ensure_server(self) -> None:
        if self._server_ready:
            return
        if self.build:
            run_command((self.cjpm, "build"), cwd=self.server_root, env=self.env)
        if not self.server.is_file():
            raise TestFailure(f"CjRepo Server executable not found: {self.server}")
        self._server_ready = True

    def cjpm_command(
        self,
        app: Path,
        *arguments: str,
        expect_success: bool = True,
        extra_env: dict[str, str] | None = None,
    ):
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        return run_command(
            (self.cjpm, *arguments), cwd=app, env=env, expect_success=expect_success
        )

    def pass_message(self, message: str) -> None:
        print(f"PASS {message}", flush=True)


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.rstrip("\r\n") for line in path.read_text(encoding="utf-8").splitlines()]


def _mock_command(context: TestContext, port: int, mode: str) -> tuple[str, ...]:
    return (python_command(), str(context.multirepo_root / "server.py"), str(port), mode)


def _run_with_repositories(
    context: TestContext,
    app_name: str | Path,
    repositories: Iterable[tuple[int, str]],
    arguments: tuple[str, ...],
    *,
    expect_success: bool = True,
    extra_env: dict[str, str] | None = None,
):
    with ManagedProcesses() as processes:
        ports: list[int] = []
        for port, mode in repositories:
            processes.start(_mock_command(context, port, mode), cwd=context.multirepo_root)
            ports.append(port)
        for port in ports:
            wait_for_port(port)
        app = app_name if isinstance(app_name, Path) else context.multirepo_root / app_name
        return context.cjpm_command(
            app,
            *arguments,
            expect_success=expect_success,
            extra_env=extra_env,
        )


def _transitive_app(
    context: TestContext, name: str, *, mesh_requirement: str, bridge_requirement: str,
    leaf_requirement: str | None = None,
) -> Path:
    app = context.temp_root / name
    shutil.copytree(context.multirepo_root / "app", app)
    context.reset_app(app)
    manifest = app / "cjpm.toml"
    text = manifest.read_text(encoding="utf-8")
    original_requirement = 'meshdep = "[1.0.0, 3.0.0)"'
    if original_requirement not in text:
        raise TestFailure("Multi-repository fixture lost its expected meshdep requirement")
    text = text.replace(original_requirement, f'meshdep = "{mesh_requirement}"')
    added_requirements = f'\nmeshbridge = "{bridge_requirement}"\n'
    if leaf_requirement is not None:
        added_requirements += f'meshleaf = "{leaf_requirement}"\n'
    manifest.write_text(text + added_requirements, encoding="utf-8")
    source = app / "src" / "main.cj"
    text = source.read_text(encoding="utf-8")
    if "import meshdep.*" not in text or "println(registryMarker())" not in text:
        raise TestFailure("Multi-repository fixture lost its expected source markers")
    text = text.replace("import meshdep.*", "import meshdep.*\nimport meshbridge.*").replace(
        "println(registryMarker())", "println(registryMarker())\n    println(bridgeMarker())"
    )
    if leaf_requirement is not None:
        text = text.replace("import meshbridge.*", "import meshbridge.*\nimport meshleaf.*").replace(
            "println(bridgeMarker())", "println(bridgeMarker())\n    println(leafMarker())"
        )
    source.write_text(text, encoding="utf-8")
    return app


def _assert_transitive_sources(
    context: TestContext, app: Path, *, mesh_version: str, mesh_repository: str,
    bridge_version: str, bridge_repository: str, leaf_repository: str | None = None,
) -> None:
    provenance = json.loads((app / "cjpm-provenance.json").read_text(encoding="utf-8"))
    selected = {item["package"]: item for item in provenance["packages"]}
    assert_equal(provenance["formatVersion"], 1, label="transitive provenance format")
    expected_packages = {"meshdep", "meshbridge"}
    if leaf_repository is not None:
        expected_packages.add("meshleaf")
    assert_equal(set(selected), expected_packages, label="transitive provenance packages")
    artifact_fixtures = {
        ("meshdep", "1.0.0", "high"): "meshdep-v1-high",
        ("meshdep", "2.0.0", "low"): "meshdep-v2-low",
        ("meshbridge", "1.0.0", "low"): "meshbridge-v1",
        ("meshbridge", "2.0.0", "high"): "meshbridge-v2",
        ("meshleaf", "1.0.0", "high"): "meshleaf-v1",
    }
    expected_sources = [
        ("meshdep", mesh_version, mesh_repository),
        ("meshbridge", bridge_version, bridge_repository),
    ]
    if leaf_repository is not None:
        expected_sources.append(("meshleaf", "1.0.0", leaf_repository))
    for package, version, repository in expected_sources:
        assert_equal(selected[package]["version"], version, label=f"{package} version")
        assert_equal(selected[package]["repository"], repository, label=f"{package} repository")
        port = 39141 if repository == "high" else 39142
        assert_equal(
            selected[package]["registry"], f"http://127.0.0.1:{port}",
            label=f"{package} registry URL",
        )
        artifact = (
            context.multirepo_root / "packages" / artifact_fixtures[(package, version, repository)]
            / "target" / f"{package}-{version}.cjp"
        )
        assert_equal(selected[package]["sha256"], sha256(artifact), label=f"{package} SHA-256")


def _run_multirepo_transitive(context: TestContext) -> None:
    high = (39141, "transitive-high")
    low = (39142, "transitive-low")
    cases = (
        ("transitive-constrained", "1.0.0", "[1.0.0, 3.0.0)",
         "high-1.0.0", "bridge-1.0.0-high-1.0.0", "1.0.0", "high", "1.0.0", "low"),
        ("transitive-latest", "[1.0.0, 3.0.0)", "[1.0.0, 3.0.0)",
         "low-2.0.0", "bridge-2.0.0-low-2.0.0", "2.0.0", "low", "2.0.0", "high"),
    )
    for (
        name, mesh_requirement, bridge_requirement, mesh_marker, bridge_marker,
        mesh_version, mesh_repository, bridge_version, bridge_repository,
    ) in cases:
        app = _transitive_app(
            context, name, mesh_requirement=mesh_requirement,
            bridge_requirement=bridge_requirement,
        )
        result = _run_with_repositories(context, app, (high, low), ("run",))
        assert_contains(result.output, mesh_marker)
        assert_contains(result.output, bridge_marker)
        _assert_transitive_sources(
            context, app, mesh_version=mesh_version, mesh_repository=mesh_repository,
            bridge_version=bridge_version, bridge_repository=bridge_repository,
        )
        context.pass_message(f"cross-repository {name}: resolved versions and audited sources")

    diamond = _transitive_app(
        context, "transitive-diamond", mesh_requirement="[1.0.0, 3.0.0)",
        bridge_requirement="1.0.0", leaf_requirement="1.0.0",
    )
    result = _run_with_repositories(context, diamond, (high, low), ("run",))
    for marker in ("high-1.0.0", "bridge-1.0.0-high-1.0.0", "leaf-1.0.0-high-1.0.0"):
        assert_contains(result.output, marker, label="diamond runtime marker")
    _assert_transitive_sources(
        context, diamond, mesh_version="1.0.0", mesh_repository="high",
        bridge_version="1.0.0", bridge_repository="low", leaf_repository="high",
    )
    context.pass_message("cross-repository diamond converges on one audited meshdep source")

    diamond_conflict = _transitive_app(
        context, "transitive-diamond-conflict", mesh_requirement="[1.0.0, 3.0.0)",
        bridge_requirement="2.0.0", leaf_requirement="1.0.0",
    )
    result = _run_with_repositories(
        context, diamond_conflict, (high, low), ("run",), expect_success=False,
    )
    for expected in ("meshdep", "1.0.0", "2.0.0"):
        assert_contains(result.output, expected, label="diamond conflict diagnostic")
    context.pass_message("cross-repository diamond conflict fails explicitly")

    conflict = _transitive_app(
        context, "transitive-conflict", mesh_requirement="2.0.0", bridge_requirement="1.0.0"
    )
    result = _run_with_repositories(
        context, conflict, (high, low), ("run",), expect_success=False
    )
    for expected in ("meshdep", "1.0.0", "2.0.0"):
        assert_contains(result.output, expected, label="cross-repository conflict diagnostic")
    context.pass_message("cross-repository incompatible transitive requirements fail explicitly")


def run_multirepo(context: TestContext) -> None:
    ports = tuple(range(39141, 39148))
    assert_ports_available(ports)
    for package in (
        "meshdep-v1-high",
        "meshdep-v1-low",
        "meshdep-v2-low",
        "company-auth-v1-private",
        "company-auth-v9-public",
    ):
        context.bundle(package)

    with ManagedProcesses() as processes:
        processes.start(_mock_command(context, 39142, "low"), cwd=context.multirepo_root)
        wait_for_port(39142)
        context.bundle("meshbridge-v1")
        context.bundle("meshbridge-v2")
        context.bundle("meshleaf-v1")
    wait_for_ports_closed((39142,))
    _run_multirepo_transitive(context)

    high = (39141, "high")
    low = (39142, "low")
    missing = (39143, "missing")
    server_error = (39143, "server-error")
    token = (39145, "token")
    private = (39146, "private")
    public = (39147, "public")

    app = context.multirepo_root / "app"
    context.reset_app(app)
    result = _run_with_repositories(context, "app", (high, low), ("run",))
    assert_contains(result.output, "low-2.0.0")
    provenance = json.loads((app / "cjpm-provenance.json").read_text(encoding="utf-8"))
    mesh_source = next(item for item in provenance["packages"] if item["package"] == "meshdep")
    assert_equal(provenance["formatVersion"], 1, label="provenance formatVersion")
    assert_equal(mesh_source["version"], "2.0.0", label="recorded version")
    assert_equal(mesh_source["repository"], "low", label="recorded repository")
    if not mesh_source.get("sha256"):
        raise TestFailure("Repository provenance did not record the selected checksum")
    context.pass_message("highest compatible version across repositories")
    context.pass_message("selected repository source and checksum are persisted")

    result = context.cjpm_command(app, "repo", "explain", "meshdep", "--recorded")
    for expected in ("Recorded resolution:", "version: 2.0.0", "repository: low", "checksum: sha256:"):
        assert_contains(result.output, expected)
    context.pass_message("recorded source remains explainable while repositories are offline")

    context.reset_app(app)
    result = _run_with_repositories(context, "app", (high, low), ("repo", "explain", "meshdep"))
    for expected in (
        "Requested:",
        "[1.0.0, 3.0.0)",
        "selected version: 2.0.0",
        "repository: low",
        "checksum: sha256:",
    ):
        assert_contains(result.output, expected)
    context.pass_message("repo explain reports the selected version, source and checksum")

    context.reset_app(app)
    result = _run_with_repositories(context, "app", (high, low), ("repo", "doctor", "meshdep"))
    for expected in ("Repository Diagnostics", "Metadata API   PASS  status=200", "Overall: PASS"):
        assert_contains(result.output, expected)
    context.pass_message("repo doctor checks every allowed repository")

    cases = (
        ("app-pinned", (high, low), ("run",), True, ("high-1.0.0",), "repository priority breaks duplicate-version ties"),
        ("app-replace", (high, low), ("run",), True, ("high-1.0.0",), "existing cjpm replace forces a version across repositories"),
        (
            "app-replace-fallback",
            (missing, low),
            ("run",),
            True,
            ("low-1.0.0",),
            "replaced version follows multi-repository fallback",
        ),
        (
            "app-replace-invalid",
            (high, low),
            ("run",),
            False,
            ("field 'replace'", "does not exist"),
            "missing replacement version fails explicitly",
        ),
        ("app-fallback", (missing, low), ("run",), True, ("low-2.0.0",), "404 fallback"),
        (
            "app-fallback",
            (server_error, low),
            ("run",),
            True,
            ("low-2.0.0", "trying the next repository"),
            "5xx fallback",
        ),
    )
    for app_name, repositories, arguments, success, expected_values, message in cases:
        app_root = context.multirepo_root / app_name
        context.reset_app(app_root)
        result = _run_with_repositories(
            context, app_name, repositories, arguments, expect_success=success
        )
        for expected in expected_values:
            assert_contains(result.output, expected)
        if app_name == "app-replace" and arguments == ("run",):
            lock = (app_root / "cjpm.lock").read_text(encoding="utf-8")
            if 'version = "1.0.0"' not in lock or 'version = "2.0.0"' in lock:
                raise TestFailure(f"Replace lockfile did not force meshdep to 1.0.0:\n{lock}")
        context.pass_message(message)

    replace_app = context.multirepo_root / "app-replace"
    context.reset_app(replace_app)
    result = _run_with_repositories(
        context, "app-replace", (high, low), ("repo", "explain", "meshdep")
    )
    for expected in (
        "applied: [1.0.0, 3.0.0) -> 1.0.0",
        "selected version: 1.0.0",
        "repository: high",
    ):
        assert_contains(result.output, expected)
    context.pass_message("repo explain makes replacement and source priority visible")

    low_log = context.multirepo_root / "low.requests.log"
    auth_app = context.multirepo_root / "app-auth-barrier"
    for status, mode in ((401, "unauthorized"), (403, "forbidden")):
        barrier = (39144, mode)
        context.reset_app(auth_app)
        remove_within(low_log, (context.tests_root,))
        result = _run_with_repositories(
            context, "app-auth-barrier", (barrier, low), ("run",), expect_success=False
        )
        if low_log.exists() and low_log.stat().st_size:
            raise TestFailure(
                f"{status} security barrier failed: lower-priority repository was accessed"
            )
        assert_contains(result.output, f"status {status}")
        context.pass_message(f"{status} blocks fallback")

        # Doctor diagnoses each configured candidate independently; its probes are not resolution fallback.
        context.reset_app(auth_app)
        result = _run_with_repositories(
            context,
            "app-auth-barrier",
            (barrier, low),
            ("repo", "doctor", "meshdep"),
            expect_success=False,
        )
        for expected in (
            f"Metadata API   FAIL  status={status}",
            "Fallback       BLOCKED",
            "Overall: FAIL",
        ):
            assert_contains(result.output, expected)
        context.pass_message(f"repo doctor identifies {status} authentication barrier")

    pinned_app = context.multirepo_root / "app-pinned"
    for status, mode in ((401, "artifact-unauthorized"), (403, "artifact-forbidden")):
        context.reset_app(pinned_app)
        barrier_log = context.multirepo_root / f"{mode}.requests.log"
        remove_within(barrier_log, (context.tests_root,))
        remove_within(low_log, (context.tests_root,))
        result = _run_with_repositories(
            context, "app-pinned", ((39141, mode), low), ("run",), expect_success=False
        )
        assert_contains(result.output, f"status {status}")
        if "GET /pkg/meshdep/1.0.0" not in _read_lines(barrier_log):
            raise TestFailure(f"{status} artifact barrier was not reached")
        if any(line.startswith("GET /pkg/") for line in _read_lines(low_log)):
            raise TestFailure(f"{status} artifact barrier fell back to a lower-priority artifact")
        if (pinned_app / "cjpm-provenance.json").exists():
            raise TestFailure(f"{status} artifact failure wrote a successful provenance record")
        context.pass_message(f"{status} artifact denial preserves the chosen repository source")

    context.reset_app(pinned_app)
    remove_within(low_log, (context.tests_root,))
    result = _run_with_repositories(
        context, "app-pinned", ((39141, "corrupt-high"), low),
        ("run",), expect_success=False,
    )
    assert_contains(result.output, "package was broken while downloading")
    if any(line.startswith("GET /pkg/") for line in _read_lines(low_log)):
        raise TestFailure("Corrupt chosen artifact fell back to a lower-priority artifact")
    if (pinned_app / "cjpm-provenance.json").exists():
        raise TestFailure("Corrupt chosen artifact wrote a successful provenance record")
    result = _run_with_repositories(context, "app-pinned", (high, low), ("run",))
    assert_contains(result.output, "high-1.0.0")
    provenance = json.loads((pinned_app / "cjpm-provenance.json").read_text(encoding="utf-8"))
    mesh_source = next(item for item in provenance["packages"] if item["package"] == "meshdep")
    assert_equal(mesh_source["repository"], "high", label="recovered artifact repository")
    artifact = (
        context.multirepo_root / "packages" / "meshdep-v1-high" / "target" / "meshdep-1.0.0.cjp"
    )
    assert_equal(mesh_source["sha256"], sha256(artifact), label="recovered artifact SHA-256")
    context.pass_message("corrupt chosen artifact is rejected without fallback or cache poisoning")

    denied_app = _transitive_app(
        context, "transitive-artifact-denied", mesh_requirement="2.0.0",
        bridge_requirement="2.0.0",
    )
    denied_modes = (
        (39141, "artifact-forbidden-transitive-high"),
        (39142, "artifact-forbidden-transitive-low"),
    )
    with ManagedProcesses() as processes:
        for port, mode in denied_modes:
            remove_within(
                context.multirepo_root / f"{mode}.requests.log", (context.tests_root,)
            )
            processes.start(_mock_command(context, port, mode), cwd=context.multirepo_root)
            wait_for_port(port)
        result = run_command(
            (context.cjpm, "build", "-j", "1"), cwd=denied_app, env=context.env,
            expect_success=False, timeout=30,
        )
    assert_contains(result.output, "status 403")
    for _port, mode in denied_modes:
        requests = _read_lines(context.multirepo_root / f"{mode}.requests.log")
        if not any(line.startswith("GET /pkg/") for line in requests):
            raise TestFailure(
                f"Single-job download did not reach artifact denial in {mode}: "
                f"requests={requests!r}\n{result.output}"
            )
    if (denied_app / "cjpm-provenance.json").exists():
        raise TestFailure("Failed parallel artifact downloads wrote a successful provenance record")
    context.pass_message("failed artifact downloads release single-job concurrency permits")

    token_app = context.multirepo_root / "app-token"
    context.reset_app(token_app)
    env_without_token = dict(context.env)
    env_without_token.pop("CJREPOMESH_TEST_TOKEN", None)
    result = run_command(
        (context.cjpm, "check"), cwd=token_app, env=env_without_token, expect_success=False
    )
    assert_contains(result.output, "environment variable 'CJREPOMESH_TEST_TOKEN'")
    result = _run_with_repositories(
        context,
        "app-token",
        (token,),
        ("run",),
        extra_env={"CJREPOMESH_TEST_TOKEN": "secret-token"},
    )
    assert_contains(result.output, "high-1.0.0")
    context.pass_message("token-env authentication")

    namespace_app = context.multirepo_root / "app-namespace"
    public_log = context.multirepo_root / "public.requests.log"
    context.reset_app(namespace_app)
    remove_within(public_log, (context.tests_root,))
    result = _run_with_repositories(context, "app-namespace", (private, public), ("run",))
    assert_contains(result.output, "private-1.0.0")
    if public_log.exists() and public_log.stat().st_size:
        raise TestFailure("Exclusive namespace route accessed the public repository")

    for status, mode in (
        (404, "missing"),
        (401, "unauthorized"),
        (403, "forbidden"),
        (500, "server-error"),
    ):
        context.reset_app(namespace_app)
        remove_within(public_log, (context.tests_root,))
        result = _run_with_repositories(
            context, "app-namespace", ((39146, mode), public),
            ("run",), expect_success=False,
        )
        assert_contains(result.output, f"status {status}")
        if public_log.exists() and public_log.stat().st_size:
            raise TestFailure(
                f"Exclusive namespace route accessed the public repository after {status}"
            )
        context.pass_message(f"exclusive namespace blocks public fallback after {status}")
    context.pass_message("exclusive namespace dependency-confusion protection")

    legacy_app = context.multirepo_root / "app-legacy"
    context.reset_app(legacy_app)
    result = _run_with_repositories(context, "app-legacy", (low,), ("run",))
    assert_contains(result.output, "low-2.0.0")
    _run_with_repositories(context, "app-legacy", (low,), ("update",))
    legacy_root = legacy_app / "cache" / "repository"
    if not (legacy_root / "index" / "default" / "me" / "sh" / "meshdep").exists():
        raise TestFailure("Legacy repository.home index path was not preserved")
    if (legacy_root / "registries").exists():
        raise TestFailure("Legacy repository.home unexpectedly used multi-registry cache layout")
    context.pass_message("legacy repository.home compatibility")
    wait_for_ports_closed(ports)


def _start_server(
    context: TestContext,
    processes: ManagedProcesses,
    *,
    port: int,
    storage: Path,
    upstream: str = "",
    publish_token: str = "",
    read_token: str = "",
    output_name: str,
):
    env = dict(context.env)
    env.update({"CJREPO_PORT": str(port), "CJREPO_STORAGE": str(storage)})
    if upstream:
        env["CJREPO_UPSTREAM"] = upstream
    else:
        env.pop("CJREPO_UPSTREAM", None)
    if publish_token:
        env["CJREPO_PUBLISH_TOKEN"] = publish_token
    else:
        env.pop("CJREPO_PUBLISH_TOKEN", None)
    if read_token:
        env["CJREPO_READ_TOKEN"] = read_token
    else:
        env.pop("CJREPO_READ_TOKEN", None)
    process = processes.start(
        (context.server,),
        cwd=context.server_root,
        env=env,
        output_path=context.temp_root / output_name,
    )
    wait_for_health(port)
    return process


def run_hosted(context: TestContext) -> None:
    port = 39200
    private_port = 39201
    assert_ports_available((port, private_port, 39202))
    package_root = context.bundle("meshdep-v2-low")
    concurrent_root = context.bundle("meshdep-v1-high")
    context.ensure_server()
    app = context.tests_root / "hosted-server" / "app"
    context.reset_app(app)
    private_app = context.tests_root / "hosted-server" / "private-app"
    context.reset_app(private_app)
    org_package = context.tests_root / "hosted-server" / "org-package"
    context.reset_app(org_package)
    org_app = context.tests_root / "hosted-server" / "org-app"
    context.reset_app(org_app)
    org_private_app = context.tests_root / "hosted-server" / "org-private-app"
    context.reset_app(org_private_app)
    storage = context.temp_root / "hosted-storage"

    metadata = (package_root / "target" / "meta-data.json").read_bytes()
    artifact_path = package_root / "target" / "meshdep-2.0.0.cjp"
    artifact = artifact_path.read_bytes()
    invalid_env = dict(context.env)
    invalid_env.update({
        "CJREPO_PORT": "39202",
        "CJREPO_STORAGE": str(context.temp_root / "invalid-private-storage"),
        "CJREPO_READ_TOKEN": "read-token",
    })
    invalid_server = run_command(
        (context.server,), cwd=context.server_root, env=invalid_env,
        expect_success=False, timeout=5,
    )
    assert_contains(invalid_server.output, "CJREPO_PUBLISH_TOKEN is required")
    context.pass_message("private read mode refuses unauthenticated publishing")
    base = f"http://127.0.0.1:{port}"
    with ManagedProcesses() as processes:
        _start_server(
            context,
            processes,
            port=port,
            storage=storage,
            publish_token="publish-token",
            output_name="hosted.log",
        )
        context.pass_message("Cangjie server health check")

        response = http_request(
            "POST",
            f"{base}/pkg/meshdep",
            headers={"Authorization": "wrong-token"},
            body=publish_frame(metadata, artifact),
        )
        assert_equal(response.status, 401, label="invalid-token publish status")
        context.pass_message("publish authentication rejects an invalid token")

        corrupt = bytearray(artifact)
        corrupt[0] ^= 0xFF
        response = http_request(
            "POST",
            f"{base}/pkg/meshdep",
            headers={"Authorization": "publish-token"},
            body=publish_frame(metadata, bytes(corrupt)),
        )
        assert_equal(response.status, 400, label="corrupt publish status")
        context.pass_message("publish rejects an artifact with a mismatched SHA-256")

        result = context.cjpm_command(
            package_root,
            "publish",
            extra_env={"CJREPOMESH_PUBLISH_TOKEN": "publish-token"},
        )
        context.pass_message("cjpm publishes a package to CjRepo Server")
        result = context.cjpm_command(
            package_root,
            "publish",
            expect_success=False,
            extra_env={"CJREPOMESH_PUBLISH_TOKEN": "publish-token"},
        )
        assert_contains(result.output, "status 409")
        context.pass_message("duplicate publish is rejected with 409")

        response = http_request("GET", f"{base}/index/me/sh/meshdep")
        record = json.loads(response.body)
        assert_equal(response.status, 200, label="hosted index status")
        assert_equal(record["version"], "2.0.0", label="hosted index version")
        context.pass_message("hosted index download")

        response = http_request("GET", f"{base}/pkg/meshdep/2.0.0")
        assert_equal(response.status, 200, label="hosted artifact status")
        if response.body != artifact:
            raise TestFailure("Hosted artifact checksum mismatch")
        context.pass_message("hosted artifact download and checksum")

        for query in ("organization=", "%6Frganization=demo", "unused=x", "organization=default"):
            for path in ("/index/me/sh/meshdep", "/pkg/meshdep/2.0.0"):
                assert_equal(
                    http_request("GET", f"{base}{path}?{query}").status,
                    400,
                    label=f"default namespace query rejection {path}?{query}",
                )
        organization = "meshcorp"
        organization_query = f"?organization={organization}"
        for path in ("/index/me/sh/meshdep", "/pkg/meshdep/2.0.0"):
            assert_equal(
                http_request("GET", base + path + organization_query).status,
                404,
                label=f"organization namespace starts empty {path}",
            )
        assert_equal(
            http_request(
                "POST", f"{base}/pkg/meshdep{organization_query}",
                headers={"Authorization": "publish-token"},
                body=publish_frame(metadata, artifact),
            ).status,
            400,
            label="organization publish metadata must match query",
        )
        organization_metadata = json.loads(metadata)
        organization_metadata["organization"] = organization
        organization_metadata["index"]["organization"] = organization
        organization_frame = publish_frame(json.dumps(organization_metadata).encode(), artifact)
        assert_equal(
            http_request(
                "POST", f"{base}/pkg/meshdep{organization_query}",
                headers={"Authorization": "publish-token"},
                body=organization_frame,
            ).status,
            200,
            label="organization publish status",
        )
        response = http_request("GET", f"{base}/index/me/sh/meshdep{organization_query}")
        assert_equal(response.status, 200, label="organization index status")
        assert_equal(json.loads(response.body)["organization"], organization, label="organization index identity")
        response = http_request("GET", f"{base}/pkg/meshdep/2.0.0{organization_query}")
        assert_equal(response.status, 200, label="organization artifact status")
        if response.body != artifact:
            raise TestFailure("Organization artifact checksum mismatch")
        assert_equal(
            http_request(
                "POST", f"{base}/pkg/meshdep{organization_query}",
                headers={"Authorization": "publish-token"},
                body=organization_frame,
            ).status,
            409,
            label="duplicate organization publish",
        )
        context.pass_message("Hosted organization publish, index and artifact are isolated from default storage")

        context.cjpm_command(org_package, "bundle")
        context.cjpm_command(
            org_package, "publish", extra_env={"CJREPOMESH_PUBLISH_TOKEN": "publish-token"},
        )
        result = context.cjpm_command(org_app, "run")
        assert_contains(result.output, "meshcorp-1.0.0")
        context.pass_message("enhanced cjpm bundles, publishes and runs a Hosted organization package")

        result = context.cjpm_command(app, "run")
        assert_contains(result.output, "low-2.0.0")
        context.pass_message("enhanced cjpm resolves and runs a package from CjRepo Server")

        concurrent_metadata = (concurrent_root / "target" / "meta-data.json").read_bytes()
        concurrent_path = concurrent_root / "target" / "meshdep-1.0.0.cjp"
        concurrent_body = publish_frame(concurrent_metadata, concurrent_path.read_bytes())

        def publish_once() -> int:
            return http_request(
                "POST",
                f"{base}/pkg/meshdep",
                headers={"Authorization": "publish-token"},
                body=concurrent_body,
            ).status

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = sorted(executor.map(lambda _item: publish_once(), range(2)))
        assert_equal(statuses, [200, 409], label="concurrent publish statuses")
        response = http_request("GET", f"{base}/index/me/sh/meshdep")
        versions = sorted(
            json.loads(line)["version"] for line in response.body.decode("utf-8").splitlines() if line
        )
        assert_equal(versions, ["1.0.0", "2.0.0"], label="concurrent package index")
        stored = storage / "artifacts" / "default" / "meshdep" / "1.0.0" / "meshdep-1.0.0.cjp"
        assert_equal(sha256(stored), sha256(concurrent_path), label="concurrent artifact checksum")
        context.pass_message("concurrent duplicate publish is atomic: one success, one conflict, intact index")

        _start_server(
            context,
            processes,
            port=private_port,
            storage=storage,
            publish_token="publish-token",
            read_token="read-token",
            output_name="hosted-private.log",
        )
        private_base = f"http://127.0.0.1:{private_port}"
        for path in ("/index/me/sh/meshdep", "/pkg/meshdep/2.0.0"):
            assert_equal(http_request("GET", private_base + path).status, 401, label=f"missing read token {path}")
            assert_equal(
                http_request("GET", private_base + path, headers={"Authorization": "wrong-token"}).status,
                401,
                label=f"wrong read token {path}",
            )
            assert_equal(
                http_request("GET", private_base + path, headers={"Authorization": "read-token"}).status,
                200,
                label=f"valid read token {path}",
            )
            assert_equal(
                http_request("GET", private_base + path + organization_query).status,
                401,
                label=f"missing read token with organization query {path}",
            )
            assert_equal(
                http_request(
                    "GET", private_base + path + organization_query,
                    headers={"Authorization": "read-token"},
                ).status,
                200,
                label=f"authorized organization query {path}",
            )
        context.pass_message("private Hosted index and artifact reject missing or invalid read tokens")
        result = context.cjpm_command(
            private_app,
            "run",
            extra_env={"CJREPOMESH_READ_TOKEN": "read-token"},
        )
        assert_contains(result.output, "low-2.0.0")
        context.pass_message("enhanced cjpm resolves private Hosted package via token-env")
        result = context.cjpm_command(
            org_private_app,
            "run",
            extra_env={"CJREPOMESH_READ_TOKEN": "read-token"},
        )
        assert_contains(result.output, "meshcorp-1.0.0")
        context.pass_message("enhanced cjpm resolves private Hosted organization package via token-env")
    wait_for_ports_closed((port, private_port, 39202))


def _concurrent_get(url: str, count: int) -> None:
    def get_once() -> None:
        response = http_request("GET", url)
        assert_equal(response.status, 200, label=f"concurrent GET status for {url}")

    with ThreadPoolExecutor(max_workers=count) as executor:
        list(executor.map(lambda _item: get_once(), range(count)))


def run_proxy(context: TestContext) -> None:
    ports = (39300, 39301, 39302, 39303, 39304, 39305, 39306, 39307)
    assert_ports_available(ports)
    context.bundle("meshdep-v1-low")
    context.bundle("meshdep-v2-low")
    context.bundle("otherdep-v1")
    context.ensure_server()
    app = context.tests_root / "proxy" / "app"
    context.reset_app(app)
    org_app = context.tests_root / "proxy" / "org-app"
    context.reset_app(org_app)
    storage = context.temp_root / "proxy-storage"
    low_log = context.multirepo_root / "low.requests.log"
    corrupt_log = context.multirepo_root / "corrupt.requests.log"
    slow_log = context.multirepo_root / "slow-mixed.requests.log"
    remove_within(low_log, (context.tests_root,))
    remove_within(corrupt_log, (context.tests_root,))
    remove_within(slow_log, (context.tests_root,))

    with ManagedProcesses() as processes:
        upstream = processes.start(_mock_command(context, 39301, "low"), cwd=context.multirepo_root)
        wait_for_port(39301)
        proxy = _start_server(
            context,
            processes,
            port=39300,
            storage=storage,
            upstream="http://127.0.0.1:39301",
            output_name="proxy.log",
        )
        _concurrent_get("http://127.0.0.1:39300/index/me/sh/meshdep", 8)
        _concurrent_get("http://127.0.0.1:39300/pkg/meshdep/2.0.0", 8)
        requests = _read_lines(low_log)
        assert_equal(requests.count("GET /index/me/sh/meshdep"), 1, label="concurrent index fills")
        assert_equal(requests.count("GET /pkg/meshdep/2.0.0"), 1, label="concurrent artifact fills")
        context.pass_message("concurrent proxy requests produce one verified upstream fill")

        result = context.cjpm_command(app, "run")
        assert_contains(result.output, "low-2.0.0")
        index_cache = storage / "index" / "default" / "me" / "sh" / "meshdep"
        artifact_cache = storage / "artifacts" / "default" / "meshdep" / "2.0.0" / "meshdep-2.0.0.cjp"
        if not index_cache.exists() or not artifact_cache.exists():
            raise TestFailure("Proxy MISS did not populate index and artifact caches")
        requests = _read_lines(low_log)
        assert_equal(requests.count("GET /index/me/sh/meshdep"), 1, label="MISS index requests")
        assert_equal(requests.count("GET /pkg/meshdep/2.0.0"), 1, label="MISS artifact requests")
        context.pass_message("proxy cache MISS fetches and validates index and artifact")

        expired = time.time() - 2 * 24 * 60 * 60
        os.utime(index_cache, (expired, expired))
        response = http_request("GET", "http://127.0.0.1:39300/index/me/sh/meshdep")
        assert_equal(response.status, 200, label="TTL refresh status")
        ttl_requests = _read_lines(low_log)
        assert_equal(ttl_requests.count("GET /index/me/sh/meshdep"), 2, label="TTL index requests")
        assert_equal(ttl_requests.count("GET /pkg/meshdep/2.0.0"), 1, label="TTL artifact requests")
        context.pass_message("expired proxy index refreshes without refetching immutable artifacts")

        processes.stop(upstream)
        context.reset_app(app)
        result = context.cjpm_command(app, "run")
        assert_contains(result.output, "low-2.0.0")
        assert_equal(_read_lines(low_log), ttl_requests, label="offline upstream request log")
        context.pass_message("proxy cache HIT supports an offline build")

        slow_upstream = processes.start(_mock_command(context, 39306, "slow-mixed"), cwd=context.multirepo_root)
        wait_for_port(39306)
        _start_server(
            context, processes, port=39307, storage=context.temp_root / "proxy-striped-storage",
            upstream="http://127.0.0.1:39306", output_name="proxy-striped.log",
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            slow_request = executor.submit(http_request, "GET", "http://127.0.0.1:39307/index/me/sh/meshdep")
            for _ in range(100):
                if "GET /index/me/sh/meshdep" in _read_lines(slow_log):
                    break
                time.sleep(0.02)
            else:
                raise TestFailure("slow upstream request did not begin")
            fast_response = http_request("GET", "http://127.0.0.1:39307/index/ot/he/otherdep")
            assert_equal(fast_response.status, 200, label="independent package proxy status")
            events = _read_lines(slow_log)
            if "GET /index/ot/he/otherdep" not in events or (
                "DONE /index/me/sh/meshdep" in events and
                events.index("DONE /index/me/sh/meshdep") < events.index("GET /index/ot/he/otherdep")
            ):
                raise TestFailure("an unrelated package waited behind the slow package fill")
            assert_equal(slow_request.result().status, 200, label="slow package proxy status")
        processes.stop(slow_upstream)
        context.pass_message("different packages fill concurrently without a global storage lock")

        processes.stop(proxy)
        if storage.exists():
            shutil.rmtree(storage)
        context.reset_app(app)
        corrupt_upstream = processes.start(
            _mock_command(context, 39302, "corrupt"), cwd=context.multirepo_root
        )
        wait_for_port(39302)
        _start_server(
            context,
            processes,
            port=39300,
            storage=storage,
            upstream="http://127.0.0.1:39302",
            output_name="proxy-corrupt.log",
        )
        result = context.cjpm_command(app, "run", expect_success=False)
        corrupt_cache = storage / "artifacts" / "default" / "meshdep" / "2.0.0" / "meshdep-2.0.0.cjp"
        assert_contains(result.output, "status 502")
        if corrupt_cache.exists():
            raise TestFailure("Proxy cached an artifact that failed SHA-256 verification")
        context.pass_message("proxy rejects a corrupt upstream artifact without caching it")
        processes.stop(corrupt_upstream)

        private_upstream = processes.start(_mock_command(context, 39301, "low"), cwd=context.multirepo_root)
        wait_for_port(39301)
        private_proxy_storage = context.temp_root / "private-proxy-storage"
        _start_server(
            context,
            processes,
            port=39303,
            storage=private_proxy_storage,
            upstream="http://127.0.0.1:39301",
            publish_token="proxy-publish-token",
            read_token="proxy-read-token",
            output_name="proxy-private.log",
        )
        private_base = "http://127.0.0.1:39303"
        upstream_before = _read_lines(low_log)
        for path in ("/index/me/sh/meshdep", "/pkg/meshdep/2.0.0"):
            assert_equal(http_request("GET", private_base + path).status, 401, label=f"private proxy {path}")
        assert_equal(_read_lines(low_log), upstream_before, label="unauthorized private proxy upstream requests")
        for path in ("/index/me/sh/meshdep", "/pkg/meshdep/2.0.0"):
            assert_equal(
                http_request(
                    "GET", private_base + path + "?unused=x",
                    headers={"Authorization": "proxy-read-token"},
                ).status,
                400,
                label=f"unsupported private proxy query {path}",
            )
        assert_equal(_read_lines(low_log), upstream_before, label="unsupported proxy query upstream requests")
        context.pass_message("unsupported query cannot fill or read the default Proxy cache")
        assert_equal(
            http_request("GET", private_base + "/index/me/sh/meshdep?organization=meshcorp",
                         headers={"Authorization": "proxy-read-token"}).status,
            502, label="Proxy refuses upstream index from wrong organization",
        )
        if (private_proxy_storage / "index" / "meshcorp" / "me" / "sh" / "meshdep").exists():
            raise TestFailure("Proxy cached an upstream index with the wrong organization")
        context.pass_message("Proxy rejects mismatched upstream organization without poisoning cache")
        for path in ("/index/me/sh/meshdep", "/pkg/meshdep/2.0.0"):
            assert_equal(
                http_request("GET", private_base + path, headers={"Authorization": "proxy-read-token"}).status,
                200,
                label=f"authorized private proxy {path}",
            )
        processes.stop(private_upstream)
        for path in ("/index/me/sh/meshdep", "/pkg/meshdep/2.0.0"):
            assert_equal(
                http_request("GET", private_base + path, headers={"Authorization": "proxy-read-token"}).status,
                200,
                label=f"offline private proxy cache {path}",
            )
        context.pass_message("private Proxy rejects unauthenticated MISS and serves authenticated offline HIT")

        org_package = context.tests_root / "hosted-server" / "org-package"
        context.reset_app(org_package)
        context.cjpm_command(org_package, "bundle")
        org_metadata = (org_package / "target" / "meta-data.json").read_bytes()
        org_artifact = (org_package / "target" / "orgmeshdep-1.0.0.cjp").read_bytes()
        org_source = "http://127.0.0.1:39304"
        org_proxy = "http://127.0.0.1:39305"
        org_source_process = _start_server(
            context, processes, port=39304, storage=context.temp_root / "proxy-org-source",
            publish_token="org-publish-token", output_name="proxy-org-source.log",
        )
        assert_equal(
            http_request("POST", org_source + "/pkg/orgmeshdep?organization=meshcorp",
                         headers={"Authorization": "org-publish-token"},
                         body=publish_frame(org_metadata, org_artifact)).status,
            200, label="organization upstream publish",
        )
        _start_server(
            context, processes, port=39305, storage=context.temp_root / "proxy-org-cache",
            upstream=org_source, output_name="proxy-org.log",
        )
        result = context.cjpm_command(org_app, "run")
        assert_contains(result.output, "meshcorp-1.0.0")
        org_cache = context.temp_root / "proxy-org-cache"
        if not (org_cache / "index" / "meshcorp" / "or" / "gm" / "orgmeshdep").exists():
            raise TestFailure("Proxy organization index was not isolated in cache")
        if not (org_cache / "artifacts" / "meshcorp" / "orgmeshdep" / "1.0.0" / "orgmeshdep-1.0.0.cjp").exists():
            raise TestFailure("Proxy organization artifact was not isolated in cache")
        assert_equal(http_request("GET", org_proxy + "/index/or/gm/orgmeshdep").status,
                     404, label="default namespace cannot read organization index")
        processes.stop(org_source_process)
        context.reset_app(org_app)
        result = context.cjpm_command(org_app, "run")
        assert_contains(result.output, "meshcorp-1.0.0")
        context.pass_message("Proxy organization cache isolates namespace and supports offline cjpm build")
    wait_for_ports_closed(ports)


def run_sync(context: TestContext) -> None:
    ports = (39401, 39501, 39502, 39503, 39504)
    assert_ports_available(ports)
    context.bundle("meshdep-v1-high")
    context.bundle("meshdep-v1-low")
    context.bundle("meshdep-v2-low")
    context.ensure_server()
    suite_root = context.tests_root / "sync"
    app = suite_root / "app"
    context.reset_app(app)
    org_app = suite_root / "org-app"
    context.reset_app(org_app)
    mirror_storage = context.temp_root / "mirror-storage"
    destination_storage = context.temp_root / "destination-storage"
    manifest = suite_root / "mirror-manifest.txt"
    invalid_manifest = suite_root / "mirror-manifest-invalid.txt"
    org_manifest = suite_root / "org-manifest.txt"
    upstream_log = context.multirepo_root / "low.requests.log"
    blocked_artifact_log = context.multirepo_root / "artifact-forbidden-low.requests.log"
    conflicting_source_log = context.multirepo_root / "high.requests.log"
    remove_within(upstream_log, (context.tests_root,))
    remove_within(blocked_artifact_log, (context.tests_root,))
    remove_within(conflicting_source_log, (context.tests_root,))

    with ManagedProcesses() as processes:
        upstream = processes.start(_mock_command(context, 39401, "low"), cwd=context.multirepo_root)
        wait_for_port(39401)
        mirror_env = dict(context.env)
        mirror_env["CJREPO_STORAGE"] = str(mirror_storage)
        first = run_command(
            (context.server, "mirror-manifest", "http://127.0.0.1:39401", manifest),
            cwd=context.server_root,
            env=mirror_env,
        )
        assert_contains(first.output, "total=2 succeeded=2 failed=0")
        first_request_count = len(_read_lines(upstream_log))
        again = run_command(
            (context.server, "mirror-manifest", "http://127.0.0.1:39401", manifest),
            cwd=context.server_root,
            env=mirror_env,
        )
        assert_contains(again.output, "total=2 succeeded=2 failed=0")
        assert_equal(again.output.count("result=SKIP"), 2, label="mirror SKIP count")
        assert_equal(len(_read_lines(upstream_log)), first_request_count, label="idempotent mirror requests")
        invalid = run_command(
            (context.server, "mirror-manifest", "http://127.0.0.1:39401", invalid_manifest),
            cwd=context.server_root,
            env=mirror_env,
            expect_success=False,
        )
        assert_contains(invalid.output, "total=2 succeeded=1 failed=1")
        assert_equal(len(_read_lines(upstream_log)), first_request_count, label="invalid mirror requests")
        malformed_org = run_command(
            (context.server, "mirror", "http://127.0.0.1:39401", "meshcorp::", "1.0.0"),
            cwd=context.server_root, env=mirror_env, expect_success=False,
        )
        assert_contains(malformed_org.output, "invalid organization-qualified package")
        assert_equal(len(_read_lines(upstream_log)), first_request_count,
                     label="malformed organization must not reach upstream")
        context.pass_message("batch mirror manifest is checksum-verified, idempotent and reports partial failure")
        processes.stop(upstream)

        source = _start_server(
            context,
            processes,
            port=39501,
            storage=mirror_storage,
            publish_token="source-publish-token",
            read_token="source-read-token",
            output_name="sync-source.log",
        )
        _start_server(
            context,
            processes,
            port=39502,
            storage=destination_storage,
            publish_token="sync-token",
            output_name="sync-destination.log",
        )
        sync_env = dict(context.env)
        sync_env["CJREPO_SYNC_DESTINATION_TOKEN"] = "sync-token"
        sync_command = (
            context.server,
            "sync-manifest",
            "http://127.0.0.1:39501",
            "http://127.0.0.1:39502",
        )
        unauthenticated_sync = run_command(
            (*sync_command, manifest),
            cwd=context.server_root,
            env=sync_env,
            expect_success=False,
        )
        assert_contains(unauthenticated_sync.output, "status 401")
        sync_env["CJREPO_UPSTREAM_TOKEN"] = "source-read-token"
        first_sync = run_command((*sync_command, manifest), cwd=context.server_root, env=sync_env)
        assert_contains(first_sync.output, "total=2 succeeded=2 failed=0")
        assert_equal(first_sync.output.count("result=SYNCED"), 2, label="synced item count")
        again_sync = run_command((*sync_command, manifest), cwd=context.server_root, env=sync_env)
        assert_contains(again_sync.output, "total=2 succeeded=2 failed=0")
        assert_equal(again_sync.output.count("result=SKIP"), 2, label="sync SKIP count")
        blocked_artifact_source = processes.start(
            _mock_command(context, 39401, "artifact-forbidden-low"), cwd=context.multirepo_root
        )
        wait_for_port(39401)
        incremental = run_command(
            (context.server, "sync", "http://127.0.0.1:39401", "http://127.0.0.1:39502",
             "meshdep", "1.0.0"), cwd=context.server_root, env=sync_env,
        )
        assert_contains(incremental.output, "result=SKIP reason=already-valid")
        assert_equal(_read_lines(blocked_artifact_log), ["GET /index/me/sh/meshdep"],
                     label="incremental Sync must not fetch an existing artifact")
        processes.stop(blocked_artifact_source)
        conflicting_source = processes.start(_mock_command(context, 39401, "high"), cwd=context.multirepo_root)
        wait_for_port(39401)
        conflict = run_command(
            (context.server, "sync", "http://127.0.0.1:39401", "http://127.0.0.1:39502",
             "meshdep", "1.0.0"), cwd=context.server_root, env=sync_env, expect_success=False,
        )
        assert_contains(conflict.output, "destination version conflicts with source checksum")
        assert_equal(_read_lines(conflicting_source_log), ["GET /index/me/sh/meshdep"],
                     label="checksum conflict must not fetch or upload artifact")
        processes.stop(conflicting_source)
        context.pass_message("incremental Sync skips matching versions before artifact download and rejects checksum conflicts")
        invalid_sync = run_command(
            (*sync_command, invalid_manifest),
            cwd=context.server_root,
            env=sync_env,
            expect_success=False,
        )
        assert_contains(invalid_sync.output, "total=2 succeeded=1 failed=1")
        context.pass_message("batch Sync requires source read and destination publish tokens, is idempotent and reports partial failure")

        _start_server(
            context, processes, port=39503, storage=context.temp_root / "private-destination-storage",
            publish_token="private-destination-publish", read_token="private-destination-read",
            output_name="sync-private-destination.log",
        )
        private_destination_env = dict(sync_env)
        private_destination_env["CJREPO_SYNC_DESTINATION_TOKEN"] = "private-destination-publish"
        private_destination_command = (
            context.server, "sync", "http://127.0.0.1:39501", "http://127.0.0.1:39503",
            "meshdep", "2.0.0",
        )
        missing_destination_read = run_command(
            private_destination_command, cwd=context.server_root,
            env=private_destination_env, expect_success=False,
        )
        assert_contains(missing_destination_read.output, "destination index returned status 401")
        private_destination_env["CJREPO_SYNC_DESTINATION_READ_TOKEN"] = "private-destination-read"
        private_destination_sync = run_command(
            private_destination_command, cwd=context.server_root, env=private_destination_env,
        )
        assert_contains(private_destination_sync.output, "result=SYNCED")
        private_destination_again = run_command(
            private_destination_command, cwd=context.server_root, env=private_destination_env,
        )
        assert_contains(private_destination_again.output, "result=SKIP reason=already-valid")
        context.pass_message("private destination Sync requires separate read and publish tokens")

        invalid_watch = run_command(
            (context.server, "sync-watch", "http://127.0.0.1:39501",
             "http://127.0.0.1:39502", manifest, "0"),
            cwd=context.server_root, env=sync_env, expect_success=False,
        )
        assert_contains(invalid_watch.output, "watch interval must be an integer")
        watch_manifest = context.temp_root / "watch-manifest.txt"
        watch_manifest.write_text("meshdep 1.0.0\n", encoding="utf-8")
        watch_mirror_storage = context.temp_root / "watch-mirror-storage"
        watch_mirror_env = dict(mirror_env)
        watch_mirror_env["CJREPO_STORAGE"] = str(watch_mirror_storage)
        watch_mirror_env["CJREPO_UPSTREAM_TOKEN"] = "source-read-token"
        mirror_watch = processes.start(
            (context.server, "mirror-watch", "http://127.0.0.1:39501", watch_manifest, "1"),
            cwd=context.server_root, env=watch_mirror_env,
            output_path=context.temp_root / "mirror-watch.log",
        )
        watch_artifact_root = watch_mirror_storage / "artifacts" / "default" / "meshdep"
        for version in ("1.0.0", "2.0.0"):
            if version == "2.0.0":
                watch_manifest.write_text("meshdep 1.0.0\nmeshdep 2.0.0\n", encoding="utf-8")
            artifact = watch_artifact_root / version / f"meshdep-{version}.cjp"
            for _ in range(120):
                if artifact.exists():
                    break
                if mirror_watch.poll() is not None:
                    raise TestFailure(f"mirror-watch exited early: {mirror_watch.returncode}")
                time.sleep(0.25)
            else:
                raise TestFailure(f"mirror-watch did not mirror {version}")
        processes.stop(mirror_watch)

        _start_server(
            context, processes, port=39504, storage=context.temp_root / "watch-destination-storage",
            publish_token="watch-token", output_name="sync-watch-destination.log",
        )
        watch_manifest.write_text("meshdep 1.0.0\n", encoding="utf-8")
        watch_sync_env = dict(sync_env)
        watch_sync_env["CJREPO_SYNC_DESTINATION_TOKEN"] = "watch-token"
        sync_watch = processes.start(
            (context.server, "sync-watch", "http://127.0.0.1:39501",
             "http://127.0.0.1:39504", watch_manifest, "1"),
            cwd=context.server_root, env=watch_sync_env,
            output_path=context.temp_root / "sync-watch.log",
        )
        for version in ("1.0.0", "2.0.0"):
            if version == "2.0.0":
                watch_manifest.write_text("meshdep 1.0.0\nmeshdep 2.0.0\n", encoding="utf-8")
            artifact_url = f"http://127.0.0.1:39504/pkg/meshdep/{version}"
            for _ in range(120):
                if http_request("GET", artifact_url).status == 200:
                    break
                if sync_watch.poll() is not None:
                    raise TestFailure(f"sync-watch exited early: {sync_watch.returncode}")
                time.sleep(0.25)
            else:
                raise TestFailure(f"sync-watch did not transfer {version}")
        processes.stop(sync_watch)
        context.pass_message("watchers rerun changed manifests, synchronize new versions, and stop cleanly")

        org_package = context.tests_root / "hosted-server" / "org-package"
        context.reset_app(org_package)
        context.cjpm_command(org_package, "bundle")
        org_metadata = (org_package / "target" / "meta-data.json").read_bytes()
        org_artifact = (org_package / "target" / "orgmeshdep-1.0.0.cjp").read_bytes()
        assert_equal(
            http_request("POST", "http://127.0.0.1:39501/pkg/orgmeshdep?organization=meshcorp",
                         headers={"Authorization": "source-publish-token"},
                         body=publish_frame(org_metadata, org_artifact)).status,
            200, label="organization source publish",
        )
        org_mirror_env = dict(mirror_env)
        org_mirror_env["CJREPO_UPSTREAM_TOKEN"] = "source-read-token"
        org_mirror = run_command(
            (context.server, "mirror-manifest", "http://127.0.0.1:39501", org_manifest),
            cwd=context.server_root, env=org_mirror_env,
        )
        assert_contains(org_mirror.output, "total=1 succeeded=1 failed=0")
        if not (mirror_storage / "artifacts" / "meshcorp" / "orgmeshdep" / "1.0.0" /
                "orgmeshdep-1.0.0.cjp").exists():
            raise TestFailure("Mirror organization artifact was not isolated")
        org_mirror_again = run_command(
            (context.server, "mirror-manifest", "http://127.0.0.1:39501", org_manifest),
            cwd=context.server_root, env=org_mirror_env,
        )
        assert_contains(org_mirror_again.output, "result=SKIP")
        org_sync = run_command((*sync_command, org_manifest), cwd=context.server_root, env=sync_env)
        assert_contains(org_sync.output, "total=1 succeeded=1 failed=0")
        org_sync_again = run_command((*sync_command, org_manifest), cwd=context.server_root, env=sync_env)
        assert_contains(org_sync_again.output, "result=SKIP")
        context.pass_message("organization Mirror and Sync manifests isolate storage and remain idempotent")

        processes.stop(source)
        result = context.cjpm_command(app, "run")
        assert_contains(result.output, "low-2.0.0")
        result = context.cjpm_command(org_app, "run")
        assert_contains(result.output, "meshcorp-1.0.0")
        context.pass_message("default and organization destination builds while the source is offline")
    wait_for_ports_closed(ports)


SUITES: dict[str, tuple[str, Callable[[TestContext], None]]] = {
    "multirepo": ("Multi-repository cjpm", run_multirepo),
    "hosted": ("Hosted repository", run_hosted),
    "proxy": ("Proxy repository", run_proxy),
    "sync": ("Repository sync", run_sync),
}
