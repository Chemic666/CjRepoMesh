// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjpm.implement

import std.collection.*
import std.fs.*

private func archiveBytesMatch(bytes: Array<UInt8>, start: Int64, text: String): Bool {
    let expected = text.toArray()
    if (start < 0 || start > bytes.size - expected.size) { return false }
    for (i in 0..expected.size) {
        if (bytes[start + i] != expected[i]) { return false }
    }
    return true
}

private func archiveDecimal(bytes: Array<UInt8>, start: Int64, end: Int64): ?Int64 {
    var value: Int64 = 0
    var digits = false
    var trailing = false
    for (i in start..end) {
        let byte = bytes[i]
        if (byte == 32) { trailing ||= digits; continue }
        if (trailing || byte < 48 || byte > 57) { return None }
        value = value * 10 + Int64(byte - 48)
        digits = true
    }
    return if (digits) { Some(value) } else { None }
}

private func archiveBigEndian32(bytes: Array<UInt8>, start: Int64): Int64 {
    var value: Int64 = 0
    for (i in start..start + 4) { value = value * 256 + Int64(bytes[i]) }
    return value
}

// Only cjc's ordinary, single-object GNU32 ELF archive is normalized. Unknown
// formats stay byte-for-byte intact; the consumer still hashes the whole file.
func normalizeIncrementalArchive(path: String, objectName: String): Unit {
    let coldName = objectName.toArray()
    if (!objectName.endsWith(".o") || coldName.isEmpty() || coldName.size > 255) { return }
    for (byte in coldName) {
        if (!((byte >= 48 && byte <= 57) || (byte >= 65 && byte <= 90) ||
            (byte >= 97 && byte <= 122) || byte == 46 || byte == 95 || byte == 64 || byte == 45)) { return }
    }
    try {
        // Bound the actual read, rather than trusting a pre-read file size.
        let collected = ArrayList<UInt8>()
        try (file = File(path, Read)) {
            let buffer = Array<UInt8>(65536, repeat: 0)
            while (true) {
                let count = file.read(buffer)
                if (count == 0) { break }
                if (collected.size + count > 64 * 1024 * 1024) { return }
                collected.add(all: buffer[..count])
            }
        }
        let bytes = collected.toArray()
        if (!archiveBytesMatch(bytes, 0, "!<arch>\n")) { return }
        let members = ArrayList<(Int64, Int64, String)>()
        var position: Int64 = 8
        while (position < bytes.size) {
            if (bytes.size - position < 60 || !archiveBytesMatch(bytes, position + 58, "`\n")) { return }
            for (i in position..position + 16) { if (bytes[i] < 32 || bytes[i] > 126) { return } }
            let size = match (archiveDecimal(bytes, position + 48, position + 58)) {
                case Some(value) => value
                case None => return
            }
            if (size > bytes.size - position - 60) { return }
            let name = String.fromUtf8(bytes[position..position + 16]).trimAscii()
            members.add((position, size, name))
            position += 60 + size
            if (size % 2 == 1) {
                if (position >= bytes.size || bytes[position] != 10) { return }
                position++
            }
            if (members.size > 3) { return }
        }
        if (members.size < 2 || members[0][2] != "/") { return }
        let (objectOffset, objectSize, rawName) = members[members.size - 1]
        var name = rawName.removeSuffix("/")
        if (members.size == 3) {
            let (tableOffset, tableSize, tableName) = members[1]
            if (tableName != "//" || rawName != "/0" || tableSize < 3) { return }
            let start = tableOffset + 60
            if (bytes[start + tableSize - 2] != 47 || bytes[start + tableSize - 1] != 10) { return }
            for (i in start..start + tableSize - 2) { if (bytes[i] < 33 || bytes[i] > 126) { return } }
            name = String.fromUtf8(bytes[start..start + tableSize - 2])
        } else if (rawName.startsWith("/") || !rawName.endsWith("/")) { return }
        if (name != objectName) {
            let cached = name.toArray()
            if (cached.size != 18 || !name.endsWith(".o")) { return }
            for (i in 0..16) {
                let byte = cached[i]
                if (!((byte >= 48 && byte <= 57) || (byte >= 97 && byte <= 102))) { return }
            }
        }
        let objectStart = objectOffset + 60
        if (objectSize < 20 || !archiveBytesMatch(bytes, objectStart, "\u{7f}ELF") ||
            (bytes[objectStart + 4] != 1 && bytes[objectStart + 4] != 2) || bytes[objectStart + 6] != 1) { return }
        let endian = bytes[objectStart + 5]
        if (!((endian == 1 && bytes[objectStart + 16] == 1 && bytes[objectStart + 17] == 0) ||
            (endian == 2 && bytes[objectStart + 16] == 0 && bytes[objectStart + 17] == 1))) { return }
        let indexSize = members[0][1]
        if (indexSize < 4) { return }
        let count = archiveBigEndian32(bytes, 68)
        if (count > (indexSize - 4) / 4) { return }
        var symbol: Int64 = 72 + count * 4
        for (i in 0..count) {
            if (archiveBigEndian32(bytes, 72 + i * 4) != objectOffset || symbol >= 68 + indexSize || bytes[symbol] == 0) { return }
            while (symbol < 68 + indexSize && bytes[symbol] != 0) { symbol++ }
            if (symbol == 68 + indexSize) { return }
            symbol++
        }
        for (i in symbol..68 + indexSize) { if (bytes[i] != 0) { return } }
        let longName = if (coldName.size > 15) { (objectName + "/\n").toArray() } else { Array<UInt8>() }
        let tableBytes = if (longName.isEmpty()) { 0 } else { 60 + longName.size + longName.size % 2 }
        let newOffset = 68 + indexSize + indexSize % 2 + tableBytes
        for (i in 0..count) {
            var offset = newOffset
            for (j in 0..4) { bytes[72 + i * 4 + 3 - j] = UInt8(offset % 256); offset /= 256 }
        }
        let output = ArrayList<UInt8>()
        output.add(all: bytes[..68 + indexSize + indexSize % 2])
        if (!longName.isEmpty()) {
            let header = Array<UInt8>(60, repeat: 32)
            header[0] = 47; header[1] = 47; header[58] = 96; header[59] = 10
            let sizeText = longName.size.toString().toArray()
            for (i in 0..sizeText.size) { header[48 + i] = sizeText[i] }
            output.add(all: header); output.add(all: longName)
            if (longName.size % 2 == 1) { output.add(10) }
        }
        let header = Array<UInt8>(60, repeat: 32)
        for (i in 16..60) { header[i] = bytes[objectOffset + i] }
        let storedName = if (longName.isEmpty()) { (objectName + "/").toArray() } else { "/0".toArray() }
        for (i in 0..storedName.size) { header[i] = storedName[i] }
        output.add(all: header); output.add(all: bytes[objectStart..])
        // No prior artifact is restored. Missing output and I/O errors remain failures.
        File.writeTo(path, output.toArray())
    } catch (e: Exception) {
        throw Exception("Failed to normalize compiler archive '${path}': ${e.message}")
    }
}
