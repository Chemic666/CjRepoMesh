#!/usr/bin/env python3
"""Create private, per-installation credentials without a compiler or WSL."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import secrets
import ssl
import subprocess

from verify import digest, regular_file, verify_bundle


def protect_windows_file(path: Path) -> None:
    # Apply and verify the same owner-only ACL contract as the existing Docker
    # deployment before writing any credential bytes. Only this new file changes.
    script = r"""
$ErrorActionPreference = 'Stop'
$path = $env:CJREPOMESH_NEW_CREDENTIAL_FILE
$item = Get-Item -LiteralPath $path -Force
if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point rejected' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$acl = Get-Acl -LiteralPath $path
if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $identity.User.Value) {
    throw 'Credential file owner mismatch'
}
$acl = [Security.AccessControl.FileSecurity]::new()
$acl.SetAccessRuleProtection($true, $false)
$rule = [Security.AccessControl.FileSystemAccessRule]::new($identity.User,
    [Security.AccessControl.FileSystemRights]::FullControl,
    [Security.AccessControl.AccessControlType]::Allow)
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $path -AclObject $acl
$applied = Get-Acl -LiteralPath $path
$rules = @($applied.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]))
if (-not $applied.AreAccessRulesProtected -or $rules.Count -ne 1 -or
    $rules[0].IdentityReference.Value -ne $identity.User.Value -or
    $rules[0].AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
    $rules[0].FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl) {
    throw 'Credential ACL verification failed'
}
"""
    environment = dict(os.environ, CJREPOMESH_NEW_CREDENTIAL_FILE=str(path))
    # PowerShell 7 can pass its module paths to Windows PowerShell 5.1, where
    # those incompatible modules prevent the built-in ACL commands from loading.
    environment = {key: value for key, value in environment.items() if key.upper() != "PSMODULEPATH"}
    result = subprocess.run(("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script),
                            env=environment, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError("could not protect the new credential file; no credentials were written")


def read_ca(path: Path) -> bytes:
    try:
        if not regular_file(path) or path.stat().st_size > 1024 * 1024:
            raise ValueError()
        with path.open('rb') as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError()
        text = data.decode('ascii')
        pattern = r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----'
        if not re.findall(pattern, text, re.DOTALL) or re.sub(pattern, '', text, flags=re.DOTALL).strip():
            raise ValueError()
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=text)
        return data
    except (OSError, ValueError, UnicodeError):
        raise ValueError('CA must be a regular PEM certificate-only file of at most 1 MiB; no private keys or links') from None


def configure(root: Path, port: int, ca_file: Path | None = None) -> str:
    verify_bundle(root)
    project = "cjrepomesh-" + secrets.token_hex(8)
    path = root / ".env"
    trust = root / 'trust'
    for target in (path, trust):
        try:
            target.lstat()
        except FileNotFoundError:
            continue
        if target == path:
            raise FileExistsError()
        raise RuntimeError('trust already exists; retain the existing deployment files')
    data = read_ca(ca_file) if ca_file is not None else None
    # Exclusive creation preserves an existing deployment and rejects symlinks.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    created = [(path, os.fstat(descriptor))]
    trust_identity = None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            if os.name == "nt":
                protect_windows_file(path)
            trust.mkdir(mode=0o755)
            trust_identity = trust.lstat()
            trust.chmod(0o755)
            if data is not None:
                ca = trust / 'ca.pem'
                with ca.open('xb') as output:
                    created.append((ca, os.fstat(output.fileno())))
                    output.write(data)
                ca.chmod(0o444)
            lines = (f"COMPOSE_PROJECT_NAME={project}", f"CJREPO_HOST_PORT={port}",
                     "CJREPO_PUBLISH_TOKEN=" + secrets.token_hex(32),
                     "CJREPO_READ_TOKEN=" + secrets.token_hex(32),
                     "CJREPO_CA_SHA256=" + (digest(trust/'ca.pem') if data is not None else ''))
            stream.write("\n".join(lines) + "\n")
    except Exception:
        # No recursive removal: only unlink files exclusively created here and
        # still carrying their original identity. Keep replacements/other files.
        for target, identity in reversed(created):
            try:
                if regular_file(target) and os.path.samestat(identity, target.lstat()):
                    try:
                        target.unlink()
                    except PermissionError:
                        target.chmod(0o600)
                        target.unlink()
            except OSError:
                pass
        if trust_identity is not None:
            try:
                if os.path.samestat(trust_identity, trust.lstat()):
                    trust.rmdir()
            except OSError:
                pass
        raise
    return project


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument('--ca-file', type=Path, help='optional trusted PEM certificate bundle; no private key')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        project = configure(Path(__file__).absolute().parent, args.port, args.ca_file)
        print(f"Configured project {project}; endpoint http://127.0.0.1:{args.port}")
        print("Private credentials are in .env; values are hidden. Keep this file for restarts.")
        return 0
    except FileExistsError:
        print("FAIL: .env already exists; keep the existing credentials and project identity")
        return 1
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print("FAIL: " + str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
