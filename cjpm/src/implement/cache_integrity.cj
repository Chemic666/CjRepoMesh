// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjpm.implement

import std.collection.*
import std.fs.*
import std.sort.*
import stdx.crypto.digest.*
import stdx.encoding.hex.*
import cjpm.config.*

// This local receipt detects changes after an archive-verified extraction. It
// cannot authenticate a tree against an actor able to rewrite tree and receipt.
private let CACHE_INTEGRITY_FORMAT = "cjpm-extracted-cache-v1\n"

func repositoryCacheIntegrityError(): String {
    return "repository cache integrity check failed; existing files were preserved; " +
        "select a new [repository.cache].path and download again"
}

func repositoryCacheReceipt(source: Path): Path {
    return source.parent.join(source.fileName + ".cjpm-integrity")
}

// Unlike exists(), a parent entry lookup also observes dangling symbolic links.
// Never treat an occupied pathname as a fresh extraction destination.
func repositoryCacheEntryExists(path: Path): Bool {
    if (exists(path)) { return true }
    let parent = path.parent
    if (!directoryExists(parent.toString())) { return false }
    return Directory.readFrom(parent).iterator().any({ entry: FileInfo => entry.name == path.fileName })
}

func repositoryCacheParentsValid(localRepo: String, org: String): Bool {
    let root = Path(localRepo)
    for (path in [root, root.join("source"), root.join("source").join(
        if (org.isEmpty()) { "default" } else { org })]) {
        if (repositoryCacheEntryExists(path)) {
            let info = FileInfo(path)
            if (info.isSymbolicLink() || !info.isDirectory()) { return false }
        }
    }
    return true
}

private func repositoryCacheFileHash(path: Path): String {
    let hash = SHA256()
    try (file = File(path, Read)) {
        let buffer = Array<UInt8>(64 * 1024, repeat: 0)
        while (true) {
            let count = file.read(buffer)
            if (count == 0) { break }
            hash.write(buffer[..count])
        }
    }
    return toHexString(hash.finish())
}

private func repositoryCacheTreeEntries(path: Path, relative: String, entries: ArrayList<String>): Unit {
    let info = FileInfo(path)
    if (info.isSymbolicLink() || !info.isDirectory()) {
        throw Exception("unsupported extracted cache entry")
    }
    for (entry in Directory.readFrom(path)) {
        let child = if (relative.isEmpty()) { entry.name } else { relative + "/" + entry.name }
        // Hex encoding makes paths unambiguous even when they contain newlines,
        // colons or platform-specific separator bytes.
        let encoded = toHexString(child.toArray())
        if (entry.isSymbolicLink()) {
            throw Exception("unsupported extracted cache link")
        } else if (entry.isDirectory()) {
            entries.add("D:" + encoded + "\n")
            repositoryCacheTreeEntries(entry.path, child, entries)
        } else if (entry.isRegular()) {
            entries.add("F:" + encoded + ":" + repositoryCacheFileHash(entry.path) + "\n")
        } else {
            throw Exception("unsupported extracted cache entry")
        }
    }
}

private func repositoryCacheReceiptContent(source: Path, archiveSha: String): String {
    let entries = ArrayList<String>()
    repositoryCacheTreeEntries(source, "", entries)
    let sorted = entries.toArray()
    sort(sorted)
    let hash = SHA256()
    for (entry in sorted) { hash.write(entry.toArray()) }
    return CACHE_INTEGRITY_FORMAT + archiveSha + "\n" + toHexString(hash.finish()) + "\n"
}

func verifyRepositoryCache(source: Path, archiveSha: String): Bool {
    try {
        let receipt = repositoryCacheReceipt(source)
        let info = FileInfo(receipt)
        if (info.isSymbolicLink() || !info.isRegular()) { return false }
        let bytes = ArrayList<UInt8>()
        try (file = File(receipt, Read)) {
            // Read at most the limit plus one, including short-read streams.
            while (bytes.size <= 512) {
                let buffer = Array<UInt8>(513 - bytes.size, repeat: 0)
                let count = file.read(buffer)
                if (count == 0) { break }
                bytes.add(all: buffer[..count])
            }
        }
        if (bytes.size > 512) { return false }
        return String.fromUtf8(bytes.toArray()) == repositoryCacheReceiptContent(source, archiveSha)
    } catch (_: Exception) {
        return false
    }
}

// (admitted, downloadNeeded). Existing, incomplete or unreadable cache entries
// never become permission to overwrite or delete them.
func admitRepositoryCache(localRepo: String, org: String, source: Path, archiveSha: String): (Bool, Bool) {
    try {
        if (!repositoryCacheParentsValid(localRepo, org)) { return (false, false) }
        if (repositoryCacheEntryExists(source)) {
            return (verifyRepositoryCache(source, archiveSha), false)
        }
        if (repositoryCacheEntryExists(repositoryCacheReceipt(source)) ||
            repositoryCacheEntryExists(source.parent.join("temp-" + source.fileName))) {
            return (false, false)
        }
        return (true, true)
    } catch (_: Exception) {
        return (false, false)
    }
}

func writeRepositoryCacheReceipt(source: Path, archiveSha: String): Bool {
    try {
        let receipt = repositoryCacheReceipt(source)
        if (repositoryCacheEntryExists(receipt)) { return false }
        File.writeTo(receipt, repositoryCacheReceiptContent(source, archiveSha).toArray())
        return true
    } catch (_: Exception) {
        return false
    }
}
