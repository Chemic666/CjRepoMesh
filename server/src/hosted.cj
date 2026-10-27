// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjrepo

import std.collection.*
import std.fs.*
import std.io.*
import std.regex.*
import std.sync.*
import stdx.net.http.*
import stdx.crypto.digest.*
import stdx.encoding.hex.*
import stdx.encoding.json.*

private let FRAME_VERSION: UInt8 = 1
private let PUBLISH_ADMISSION_LOCK = Mutex()
private var activePublishes: Int64 = 0
private var inflightArtifactBytes: Int64 = 0

private func tryEnterPublish(limit: Int64): Bool {
    synchronized(PUBLISH_ADMISSION_LOCK) {
        if (activePublishes >= limit) { return false }
        activePublishes += 1
        return true
    }
}

private func leavePublish(): Unit {
    synchronized(PUBLISH_ADMISSION_LOCK) {
        activePublishes -= 1
    }
}

private class PublishBufferCapacityException <: Exception {
    public init() { super("publish capacity reached; retry later") }
}

// A lease stores only its owned count, never a payload or array reference.
private class PublishArtifactLease {
    private var ownedBytes: Int64 = 0

    public func reserve(length: Int64): Unit {
        let limit = maximumInflightArtifactBytes()
        ensurePayloadFits(0, length, limit)
        synchronized(PUBLISH_ADMISSION_LOCK) {
            if (length > limit - inflightArtifactBytes) {
                throw PublishBufferCapacityException()
            }
            inflightArtifactBytes += length
            ownedBytes = length
        }
    }

    public func release(): Unit {
        synchronized(PUBLISH_ADMISSION_LOCK) {
            if (ownedBytes > 0) {
                inflightArtifactBytes -= ownedBytes
                ownedBytes = 0
            }
        }
    }
}

private func respondPublishCapacity(context: HttpContext): Unit {
    context.responseBuilder.status(429)
        .header("Content-Type", "application/json; charset=utf-8")
        .header("Retry-After", "1")
        .header("Connection", "close")
        .body("{\"errors\":[{\"message\":\"publish capacity reached; retry later\"}]}")
}

// cjpm sends organization in a query parameter, while the HTTP distributor
// receives only the path. Accept exactly that one parameter to prevent aliases.
func requestedRegistryOrganization(context: HttpContext): String {
    if (let Some(raw) <- context.request.url.rawQuery) {
        if (!raw.startsWith("organization=")) {
            throw Exception("invalid registry organization query")
        }
        let organization = raw[13..]
        if (!isNamedRegistryOrganization(organization)) {
            throw Exception("invalid registry organization")
        }
        return organization
    }
    return "default"
}

func isNamedRegistryOrganization(organization: String): Bool {
    return organization.size >= 3 && organization.size <= 64 &&
        organization.toAsciiLower() != "default" &&
        Regex("^_*[A-Za-z][_A-Za-z0-9]*$").matches(organization)
}

func metadataOrganization(storageOrganization: String): String {
    return if (storageOrganization == "default") { "" } else { storageOrganization }
}

class PublishHandler <: HttpRequestHandler {
    private let storage: String
    private let routeName: String
    private let publishToken: String

    public init(storage: String, routeName: String, publishToken: String) {
        this.storage = storage
        this.routeName = routeName
        this.publishToken = publishToken
    }

    public func handle(context: HttpContext): Unit {
        if (context.request.method != "POST") {
            respondError(context, 400, "publish endpoint requires POST")
            return
        }
        if (!publishToken.isEmpty() &&
            (context.request.headers.getFirst("Authorization") ?? "") != publishToken) {
            respondError(context, 401, "authentication failed")
            return
        }

        var admitted = false
        let artifactLease = PublishArtifactLease()
        try {
            admitted = tryEnterPublish(maximumConcurrentPublishes())
            if (!admitted) {
                respondPublishCapacity(context)
                return
            }
            publish(context, artifactLease)
        } catch (e: PublishBufferCapacityException) {
            respondPublishCapacity(context)
        } catch (e: HostedIndexTooLargeException) {
            respondError(context, 413, e.message)
        } catch (e: PayloadTooLargeException) {
            respondError(context, 413, e.message)
        } catch (e: Exception) {
            respondError(context, 400, e.message)
        } finally {
            // The inner publish call has returned/unwound: its payload is no
            // longer rooted in this handler before another lease can be granted.
            artifactLease.release()
            if (admitted) { leavePublish() }
        }
    }

    private func publish(context: HttpContext, artifactLease: PublishArtifactLease): Unit {
        let storageOrganization = requestedRegistryOrganization(context)
        let payload = parsePublishFrame(context.request.body, artifactLease)
        let metadataJson = String.fromUtf8(payload.metadata)
        let metadata = JsonValue.fromStr(metadataJson).asObject()
        let name = requiredString(metadata, "name")
        let version = requiredString(metadata, "version")
        let packageOrganization = requiredString(metadata, "organization")
        if (name != routeName) {
            throw Exception("request package name does not match metadata")
        }
        if (!isSafePackageSegment(name) || !isSafePackageSegment(version) || name.size < 3) {
            throw Exception("invalid package name or version")
        }

        let indexValue = metadata.get("index") ?? throw Exception("metadata is missing index")
        let indexObject = indexValue.asObject()
        if (requiredString(indexObject, "name") != name ||
            requiredString(indexObject, "version") != version ||
            requiredString(indexObject, "organization") != metadataOrganization(storageOrganization) ||
            packageOrganization != metadataOrganization(storageOrganization)) {
            throw Exception("metadata index identity does not match package identity")
        }

        let expectedChecksum = requiredString(indexObject, "sha256sum")
        let sha256 = SHA256()
        sha256.write(payload.artifact)
        let actualChecksum = toHexString(sha256.finish())
        if (actualChecksum != expectedChecksum) {
            throw Exception("artifact SHA-256 does not match metadata")
        }

        let artifactDir = Path(storage)
            .join("artifacts")
            .join(storageOrganization)
            .join(name)
            .join(version)
        let artifactPath = artifactDir.join("${name}-${version}.cjp")
        let firstLevel = name[..2]
        let secondLevel = if (name.size > 3) { name[2..4] } else { name[2..3] }
        let indexDir = Path(storage).join("index").join(storageOrganization).join(firstLevel).join(secondLevel)
        let indexPath = indexDir.join(name)

        let indexLine = indexValue.toJsonString().replace("\r", "").replace("\n", "")
        let hostedIndexLimit = maximumHostedIndexBytes()
        var duplicate = false
        var recovered = false
        synchronized(packageStorageLock(storage, storageOrganization, name)) {
            // Recheck while holding the lock so concurrent publishes cannot
            // interleave records or race another retry repairing crash state.
            let previousIndex = if (exists(indexPath)) {
                readHostedIndex(indexPath, hostedIndexLimit)
            } else {
                ""
            }
            let indexedChecksum = storedHostedChecksum(previousIndex, storageOrganization, name, version)
            if (let Some(storedChecksum) <- indexedChecksum) {
                if (storedChecksum != expectedChecksum || exists(artifactPath)) {
                    duplicate = true
                } else {
                    // Restore only the missing artifact; published metadata
                    // remains byte-for-byte unchanged, including dependencies.
                    ensureParent(artifactPath)
                    writeFileAtomically(artifactPath, payload.artifact)
                    recovered = true
                }
            } else if (exists(artifactPath)) {
                // An abrupt exit can leave verified bytes without an index.
                // Never replace those bytes merely because metadata is absent.
                if (!storedArtifactMatches(artifactPath, payload.artifact.size, expectedChecksum)) {
                    duplicate = true
                } else {
                    let nextIndex = appendHostedIndex(previousIndex, indexLine, hostedIndexLimit)
                    ensureParent(indexPath)
                    writeFileAtomically(indexPath, nextIndex)
                    recovered = true
                }
            } else {
                // Refuse an over-capacity append before creating parents or
                // writing a new artifact that would otherwise need rollback.
                let nextIndex = appendHostedIndex(previousIndex, indexLine, hostedIndexLimit)
                ensureParent(artifactPath)
                ensureParent(indexPath)

                writeFileAtomically(artifactPath, payload.artifact)
                try {
                    writeFileAtomically(indexPath, nextIndex)
                } catch (e: Exception) {
                    removeIfExists(artifactPath)
                    throw e
                }
            }
        }
        if (duplicate) {
            respondError(context, 409, "artifact with the same name and version already exists")
            return
        }
        if (recovered) {
            println("[hosted] organization=${storageOrganization} package=${name} version=${version} result=RECOVERED")
        }

        context.responseBuilder
            .status(200)
            .header("Content-Type", "application/json; charset=utf-8")
            .body("{\"status\":\"published\",\"name\":\"${name}\",\"version\":\"${version}\"}")
    }
}

private func storedArtifactMatches(path: Path, expectedLength: Int64, expectedChecksum: String): Bool {
    let digest = SHA256()
    // The upload already owns its artifact array. Never allocate a second
    // file-sized array while verifying a crash orphan under the package lock.
    let buffer = Array<UInt8>(64 * 1024, repeat: 0)
    var consumed: Int64 = 0
    try (file = File(path, Read)) {
        while (true) {
            let count = file.read(buffer)
            if (count == 0) { break }
            if (count > expectedLength - consumed) { return false }
            digest.write(buffer[..count])
            consumed += count
        }
    }
    return consumed == expectedLength && toHexString(digest.finish()) == expectedChecksum
}

private func readHostedIndex(path: Path, limit: Int64): String {
    let bytes = ArrayList<UInt8>()
    try (file = File(path, Read)) {
        while (true) {
            let remaining = limit - bytes.size
            let chunkSize = if (remaining < 64 * 1024) { remaining + 1 } else { 64 * 1024 }
            let buffer = Array<UInt8>(chunkSize, repeat: 0)
            let count = file.read(buffer)
            if (count == 0) { break }
            ensureHostedIndexFits(bytes.size, count, limit)
            bytes.add(all: buffer[..count])
        }
    }
    return String.fromUtf8(bytes.toArray())
}

private func appendHostedIndex(previous: String, line: String, limit: Int64): Array<UInt8> {
    let separator = if (previous.isEmpty() || previous.endsWith("\n")) { "" } else { "\n" }
    ensureHostedIndexFits(previous.toArray().size, separator.size + line.toArray().size + 1, limit)
    return "${previous}${separator}${line}\n".toArray()
}

private func storedHostedChecksum(index: String, organization: String, name: String,
    version: String): Option<String> {
    var selected: Option<String> = None
    let versions = HashSet<String>()
    for (line in index.lines()) {
        if (line.trimAscii().isEmpty()) {
            continue
        }
        let object = JsonValue.fromStr(line).asObject()
        let recordedVersion = requiredString(object, "version")
        let recordedChecksum = requiredString(object, "sha256sum")
        if (requiredString(object, "name") != name ||
            requiredString(object, "organization") != metadataOrganization(organization) ||
            !isSafePackageSegment(recordedVersion) ||
            !Regex("^[0-9a-fA-F]{64}$").matches(recordedChecksum)) {
            throw Exception("stored package index has invalid identity, version or SHA-256")
        }
        if (versions.contains(recordedVersion)) {
            throw Exception("stored package index contains duplicate version")
        }
        versions.add(recordedVersion)
        if (recordedVersion == version) {
            selected = Some(recordedChecksum)
        }
    }
    return selected
}

private class PublishPayload {
    public let metadata: Array<UInt8>
    public let artifact: Array<UInt8>

    public init(metadata: Array<UInt8>, artifact: Array<UInt8>) {
        this.metadata = metadata
        this.artifact = artifact
    }
}

private class PublishFrameReader {
    private let input: InputStream
    private let maximumBytes: Int64
    private var consumed: Int64 = 0

    public init(input: InputStream) {
        this.input = input
        this.maximumBytes = maximumArtifactBytes() + MAX_PUBLISH_METADATA_BYTES + 10
    }

    private func readInto(buffer: Array<UInt8>): Int64 {
        let count = input.read(buffer)
        ensurePayloadFits(consumed, count, maximumBytes)
        consumed += count
        return count
    }

    public func readPart(length: Int64): Array<UInt8> {
        let bytes = Array<UInt8>(length, repeat: 0)
        var offset: Int64 = 0
        while (offset < length) {
            let count = readInto(bytes[offset..])
            if (count == 0) { throw Exception("truncated metadata or artifact frame") }
            offset += count
        }
        return bytes
    }

    public func requireEnd(): Unit {
        if (readInto(Array<UInt8>(1, repeat: 0)) != 0) {
            throw Exception("invalid artifact length")
        }
    }

    public func discardRemainder(): Unit {
        // Preserve the actual-total-byte 413 precedence for malformed chunked
        // bodies, without buffering that rejected content in memory.
        let chunk = Array<UInt8>(64 * 1024, repeat: 0)
        while (readInto(chunk) != 0) {}
    }
}

private func parsePublishFrame(input: InputStream, artifactLease: PublishArtifactLease): PublishPayload {
    let reader = PublishFrameReader(input)
    try {
        let metadataHeader = reader.readPart(5)
        if (metadataHeader[0] != FRAME_VERSION) { throw Exception("invalid metadata frame") }
        let metadataLength = decodeLittleEndianSize(metadataHeader, 1)
        ensurePayloadFits(0, metadataLength, MAX_PUBLISH_METADATA_BYTES)
        if (metadataLength <= 0) { throw Exception("invalid metadata length or artifact frame") }
        let metadata = reader.readPart(metadataLength)
        let artifactHeader = reader.readPart(5)
        if (artifactHeader[0] != FRAME_VERSION) { throw Exception("invalid artifact frame") }
        let artifactLength = decodeLittleEndianSize(artifactHeader, 1)
        ensurePayloadFits(0, artifactLength, maximumArtifactBytes())
        if (artifactLength <= 0) { throw Exception("invalid artifact length") }
        artifactLease.reserve(artifactLength)
        let artifact = reader.readPart(artifactLength)
        reader.requireEnd()
        return PublishPayload(metadata, artifact)
    } catch (e: PublishBufferCapacityException) {
        throw e
    } catch (e: PayloadTooLargeException) {
        throw e
    } catch (e: Exception) {
        reader.discardRemainder()
        throw e
    }
}

private func decodeLittleEndianSize(bytes: Array<UInt8>, offset: Int64): Int64 {
    return Int64(bytes[offset]) +
        Int64(bytes[offset + 1]) * 256 +
        Int64(bytes[offset + 2]) * 65536 +
        Int64(bytes[offset + 3]) * 16777216
}

private func requiredString(object: JsonObject, field: String): String {
    let value = object.get(field) ?? throw Exception("metadata is missing ${field}")
    return value.asString().getValue()
}

func isSafePackageSegment(segment: String): Bool {
    return Regex("^[A-Za-z0-9][A-Za-z0-9._+-]*$").matches(segment)
}

func respondError(context: HttpContext, status: UInt16, message: String): Unit {
    let safeMessage = message.replace("\\", "\\\\").replace("\"", "\\\"")
    context.responseBuilder
        .status(status)
        .header("Content-Type", "application/json; charset=utf-8")
        .body("{\"errors\":[{\"message\":\"${safeMessage}\"}]}")
}
