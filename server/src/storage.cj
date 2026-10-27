// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjrepo

import std.collection.*
import std.convert.*
import std.env.*
import std.fs.*
import std.sync.*

// Fixed-size lock striping prevents unbounded lock allocation from arbitrary
// public proxy requests. Operations for the same package always share a lock;
// unrelated packages only serialize if their hashes collide.
private let STORAGE_LOCKS: Array<Mutex> = createStorageLocks()
// Recursive mkdir can race on shared ancestors even for different packages.
// Serialize only directory creation, never network fetches or artifact writes.
private let DIRECTORY_CREATION_LOCK = Mutex()
// One server/CLI process exclusively owns its configured storage directory.
// This lock covers only managed file changes, never network I/O or package locks.
private let STORAGE_QUOTA_LOCK = Mutex()
private var storageQuotaBytes: Int64 = 0
private var storageUsedBytes: Int64 = 0
private var storageAccountingFailed = false

class StorageQuotaExceededException <: Exception {
    public init() { super("storage byte quota reached") }
}

func configuredStorageQuotaBytes(): Int64 {
    let raw = getVariable("CJREPO_STORAGE_QUOTA_BYTES") ?? "0"
    try {
        let bytes = Int64.parse(raw)
        if (bytes < 0) { throw Exception("out of range") }
        return bytes
    } catch (_: Exception) {
        throw Exception("CJREPO_STORAGE_QUOTA_BYTES must be an integer between 0 and ${Int64.Max}")
    }
}

private func addStorageBytes(current: Int64, incoming: Int64): Int64 {
    if (current < 0 || incoming < 0 || incoming > Int64.Max - current) {
        throw Exception("managed storage exceeds byte accounting range")
    }
    return current + incoming
}

private func storageFileBytes(path: Path): Int64 {
    if (!exists(path)) { return 0 }
    let info = FileInfo(path)
    if (info.isSymbolicLink() || !info.isRegular()) {
        throw Exception("storage quota requires ordinary managed files")
    }
    return info.size
}

private func storageTreeBytes(path: Path): Int64 {
    if (!exists(path)) { return 0 }
    let info = FileInfo(path)
    if (info.isSymbolicLink()) {
        throw Exception("storage quota cannot account for symbolic links")
    }
    if (info.isRegular()) { return info.size }
    if (!info.isDirectory()) {
        throw Exception("storage quota requires ordinary managed files and directories")
    }
    let total = Array<Int64>(1, repeat: 0)
    // Directory.walk visits direct children only; recurse without collecting the tree.
    Directory.walk(path) { entry =>
        total[0] = addStorageBytes(total[0], storageTreeBytes(entry.path))
        true
    }
    return total[0]
}

func initializeStorageQuota(storage: String): Unit {
    let quota = configuredStorageQuotaBytes()
    synchronized(STORAGE_QUOTA_LOCK) {
        storageQuotaBytes = quota
        storageUsedBytes = 0
        storageAccountingFailed = false
        if (quota > 0) {
            let root = Path(storage)
            if (exists(root) && FileInfo(root).isSymbolicLink()) {
                throw Exception("storage quota cannot account for symbolic links")
            }
            // Include existing crash temporaries; never delete data to satisfy a quota.
            storageUsedBytes = addStorageBytes(storageTreeBytes(root.join("index")),
                storageTreeBytes(root.join("artifacts")))
        }
    }
}

private func ensureStorageAccounting(): Unit {
    if (storageAccountingFailed) {
        throw Exception("storage byte accounting unavailable; restart after inspecting managed storage")
    }
}

// Reconcile both touched names after success, failed write, or failed cleanup.
// Any metadata failure closes admission instead of trusting an inaccurate counter.
private func reconcileStorageBytes(path: Path, temporary: Path, previous: Int64): Unit {
    try {
        let current = addStorageBytes(storageFileBytes(path), storageFileBytes(temporary))
        storageUsedBytes = addStorageBytes(storageUsedBytes - previous, current)
    } catch (_: Exception) {
        storageAccountingFailed = true
        throw Exception("storage byte accounting unavailable; restart after inspecting managed storage")
    }
}

func ensureParent(path: Path): Unit {
    synchronized(DIRECTORY_CREATION_LOCK) {
        let parent = path.parent
        if (!exists(parent)) {
            Directory.create(parent, recursive: true)
        }
    }
}

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
    if (storageQuotaBytes == 0) {
        writeStorageFileAtomically(path, body)
        return
    }
    synchronized(STORAGE_QUOTA_LOCK) {
        ensureStorageAccounting()
        // Atomic replacement temporarily needs the entire new file in addition
        // to every existing managed byte, not merely its eventual size increase.
        if (storageUsedBytes > storageQuotaBytes || body.size > storageQuotaBytes - storageUsedBytes) {
            throw StorageQuotaExceededException()
        }
        let temporary = path.parent.join(".${path.fileName}.tmp")
        let previous = addStorageBytes(storageFileBytes(path), storageFileBytes(temporary))
        try {
            writeStorageFileAtomically(path, body)
        } finally {
            reconcileStorageBytes(path, temporary, previous)
        }
    }
}

func removeStorageFile(path: Path): Unit {
    if (storageQuotaBytes == 0) {
        removeIfExists(path)
        return
    }
    synchronized(STORAGE_QUOTA_LOCK) {
        ensureStorageAccounting()
        let previous = storageFileBytes(path)
        try {
            removeIfExists(path)
        } finally {
            try {
                storageUsedBytes = addStorageBytes(storageUsedBytes - previous, storageFileBytes(path))
            } catch (_: Exception) {
                storageAccountingFailed = true
                throw Exception("storage byte accounting unavailable; restart after inspecting managed storage")
            }
        }
    }
}

private func writeStorageFileAtomically(path: Path, body: Array<UInt8>): Unit {
    // A public package may itself end in '.tmp'. Prefixing with '.' keeps
    // temporary index names outside the registry's accepted path segments.
    let temporary = path.parent.join(".${path.fileName}.tmp")
    try {
        File.writeTo(temporary, body)
        rename(temporary, to: path, overwrite: true)
    } catch (e: Exception) {
        removeIfExists(temporary)
        throw e
    }
}
