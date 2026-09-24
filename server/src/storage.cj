// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjrepo

import std.collection.*
import std.fs.*
import std.sync.*

// Fixed-size lock striping prevents unbounded lock allocation from arbitrary
// public proxy requests. Operations for the same package always share a lock;
// unrelated packages only serialize if their hashes collide.
private let STORAGE_LOCKS: Array<Mutex> = createStorageLocks()

private func createStorageLocks(): Array<Mutex> {
    let locks = ArrayList<Mutex>()
    for (_ in 0..256) {
        locks.add(Mutex())
    }
    return locks.toArray()
}

func packageStorageLock(storage: String, organization: String, name: String): Mutex {
    var slot: Int64 = 0
    for (byte in "${storage}:${organization}:${name}".toArray()) {
        slot = (slot * 131 + Int64(byte)) % 256
    }
    return STORAGE_LOCKS[slot]
}

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
