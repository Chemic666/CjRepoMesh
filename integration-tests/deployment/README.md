# One-command deployment integration test

`run.ps1` verifies the Windows deployment entrypoint without downloading or installing dependencies:

It copies the deployment scripts, built server, and package fixture into a unique directory under `integration-tests/.tmp`. It never stops the normal deployment or deletes its data. Port 39600 must be free. Successful runs clean up only their own directory; if stopping fails, the isolated state and logs remain available for inspection.

1. starts CjRepo with one command;
2. runs the deployment health diagnostics;
3. publishes a real bundled Cangjie package;
4. stops and restarts the server with the same storage;
5. downloads the persisted artifact and verifies its SHA-256.

Run from the repository root:

```powershell
integration-tests\deployment\run.ps1
```

Build the server first and load the installed Cangjie environment. The runner supports Windows PowerShell 5.1 and PowerShell 7.

Script-level regressions use Windows PowerShell and an existing Pester 3.4 installation. They simulate process and network operations and require no SDK or running service:

```cmd
powershell.exe -NoProfile -Command "Invoke-Pester -Script './integration-tests/deployment/*.Tests.ps1' -EnableExit"
```

The regressions cover inherited bind addresses, occupied ports, endpoint ownership, stale/reused PIDs, legacy state, stop timeouts, timestamp precision, and unsafe upstream URLs. These checks supplement the real deployment test above.
