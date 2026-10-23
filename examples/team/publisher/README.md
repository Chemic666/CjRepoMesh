# Private team package

The sample publishes `company::teamhello 1.0.0`. Use a new version for changes;
an already published version is immutable and a repeated publish is rejected.

For a private HTTPS CA, prepare this task with `--ca-file` and optionally
`--ca-sha256` from an independent approval. The generated script verifies
its copied public trust before invoking the client and configures only
process-level SSL trust. Keep the complete task directory together.
Credentials remain environment references; no CA private key is required.
