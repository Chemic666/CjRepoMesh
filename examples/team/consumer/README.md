# Read-only CI consumer

This app consumes only `company::teamhello 1.0.0` using the private namespace
route. A successful run prints `CjRepoMesh team 1.0.0: CI`.

When `CJREPOMESH_SOURCE_BASELINE` is set, `run.sh` first requires a successful
`repo supports source-baseline-v1` response with exactly that stdout marker.
An unsupported client or malformed response exits 2 before building. Use the
current verified client delivery; 8da5 has baseline admission but lacks this
query and is conservatively refused. Without the variable, the original flow
is retained. Capability discovery is not binary authentication or baseline approval.

For an HTTPS registry with a private CA, use the preparer's `--ca-file` and
optional independently approved `--ca-sha256`. The generated task pins its
public CA and empty additional trust directory before invoking any client,
then sets only process-level SSL trust. Move the complete task directory;
do not delete or modify its trust files. No system certificate is installed.
The source baseline remains independently approved and is not generated here.
