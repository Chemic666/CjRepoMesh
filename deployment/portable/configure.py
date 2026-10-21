#!/usr/bin/env python3
"""Create private, per-installation credentials without a compiler or WSL."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import subprocess

from verify import verify_bundle


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


def configure(root: Path, port: int) -> str:
    verify_bundle(root)
    project = "cjrepomesh-" + secrets.token_hex(8)
    path = root / ".env"
    # Exclusive creation preserves an existing deployment and rejects symlinks.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        if os.name == "nt":
            protect_windows_file(path)
        lines = (f"COMPOSE_PROJECT_NAME={project}", f"CJREPO_HOST_PORT={port}",
                 "CJREPO_PUBLISH_TOKEN=" + secrets.token_hex(32),
                 "CJREPO_READ_TOKEN=" + secrets.token_hex(32))
        stream.write("\n".join(lines) + "\n")
    return project


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        project = configure(Path(__file__).resolve().parent, args.port)
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
