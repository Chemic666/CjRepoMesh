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

        try {
            let storageOrganization = requestedRegistryOrganization(context)
            let frameBuffer = ArrayList<UInt8>()
            while (true) {
                let chunk = Array<UInt8>(64 * 1024, repeat: 0)
                let readSize = context.request.body.read(chunk)
                if (readSize == 0) {
                    break
                }
                frameBuffer.add(all: chunk[..readSize])
            }
            let frame = frameBuffer.toArray()
            let payload = parsePublishFrame(frame)
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
            var duplicate = false
            var recovered = false
            synchronized(packageStorageLock(storage, storageOrganization, name)) {
                // Recheck while holding the lock so concurrent publishes cannot
                // interleave records or race another retry repairing crash state.
                let previousIndex = if (exists(indexPath)) {
                    String.fromUtf8(File.readFrom(indexPath))
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
                    let storedDigest = SHA256()
                    storedDigest.write(File.readFrom(artifactPath))
                    if (toHexString(storedDigest.finish()) != expectedChecksum) {
                        duplicate = true
                    } else {
                        ensureParent(indexPath)
                        writeFileAtomically(indexPath, appendHostedIndex(previousIndex, indexLine))
                        recovered = true
                    }
                } else {
                    ensureParent(artifactPath)
                    ensureParent(indexPath)

                    writeFileAtomically(artifactPath, payload.artifact)
                    try {
                        writeFileAtomically(indexPath, appendHostedIndex(previousIndex, indexLine))
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
        } catch (e: Exception) {
            respondError(context, 400, e.message)
        }
    }
}

private func appendHostedIndex(previous: String, line: String): Array<UInt8> {
    let separator = if (previous.isEmpty() || previous.endsWith("\n")) { "" } else { "\n" }
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

private func parsePublishFrame(frame: Array<UInt8>): PublishPayload {
    if (frame.size < 10 || frame[0] != FRAME_VERSION) {
        throw Exception("invalid metadata frame")
    }
    let metadataLength = decodeLittleEndianSize(frame, 1)
    let artifactHeader = 5 + metadataLength
    if (metadataLength <= 0 || artifactHeader + 5 > frame.size || frame[artifactHeader] != FRAME_VERSION) {
        throw Exception("invalid metadata length or artifact frame")
    }
    let artifactLength = decodeLittleEndianSize(frame, artifactHeader + 1)
    let artifactStart = artifactHeader + 5
    if (artifactLength <= 0 || artifactStart + artifactLength != frame.size) {
        throw Exception("invalid artifact length")
    }
    return PublishPayload(
        frame[5..artifactHeader],
        frame[artifactStart..artifactStart + artifactLength]
    )
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
