# Multi-registry integration test

This fixture runs two local registries:

- `high` (priority 100): `meshdep` 1.0.0;
- `low` (priority 10): `meshdep` 1.0.0 and 2.0.0.

The application accepts versions in `[1.0.0, 3.0.0)`. The unchanged cjpm
version resolver must therefore choose 2.0.0 from `low`. If the requirement is
pinned to 1.0.0, the duplicate-version source must be `high`.

The suite also proves that cjpm's existing `[replace]` semantics remain in
force after multi-registry routing: a broad dependency is forced to 1.0.0,
the selected replacement follows repository priority and 404 fallback, and a
replacement version absent from every repository fails explicitly.

Two `meshbridge` versions add a cross-repository transitive-dependency matrix:

- A root requirement for `meshdep` 1.0.0 selects `meshbridge` 1.0.0 from `low`
  and `meshdep` 1.0.0 from `high`, even though `high` offers an incompatible
  `meshbridge` 2.0.0.
- Broad root requirements select `meshbridge` 2.0.0 from `high` and its
  required `meshdep` 2.0.0 from `low`.
- Pinning `meshbridge` 1.0.0 alongside `meshdep` 2.0.0 fails explicitly.

Successful cases check runtime markers plus both selected versions, repository
names, and SHA-256 values in `cjpm-provenance.json`. The fixtures are bundled
against the local mock registry; the runner removes their build/cache outputs.
