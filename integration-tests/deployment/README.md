# One-command deployment integration test

`run.ps1` verifies the Windows deployment entrypoint without downloading or installing dependencies:

1. starts CjRepo with one command;
2. runs the deployment health diagnostics;
3. publishes a real bundled Cangjie package;
4. stops and restarts the server with the same storage;
5. downloads the persisted artifact and verifies its SHA-256.

Run from the repository root:

```powershell
integration-tests\deployment\run.ps1
```
