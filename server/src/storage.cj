// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjrepo

import std.fs.*
import std.sync.*

// The first server slice uses one process-wide storage lock. It favors
// correctness and deterministic evidence over maximum write throughput.
let STORAGE_WRITE_MUTEX: Mutex = Mutex()

func writeFileAtomically(path: Path, body: Array<UInt8>): Unit {
    let temporary = Path(path.toString() + ".tmp")
    try {
        File.writeTo(temporary, body)
        rename(temporary, to: path, overwrite: true)
    } catch (e: Exception) {
        removeIfExists(temporary)
        throw e
    }
}
