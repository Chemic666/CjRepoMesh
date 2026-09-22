// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjrepo

import std.collection.*
import std.fs.*
import std.io.*
import std.regex.*
import stdx.net.http.*
import stdx.crypto.digest.*
import stdx.encoding.hex.*
import stdx.encoding.json.*

private let FRAME_VERSION: UInt8 = 1

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
            let organization = requiredString(metadata, "organization")
            if (name != routeName) {
                throw Exception("request package name does not match metadata")
            }
            if (!organization.isEmpty()) {
                throw Exception("organization publishing is not supported by this server slice")
            }
            if (!isSafePackageSegment(name) || !isSafePackageSegment(version) || name.size < 3) {
                throw Exception("invalid package name or version")
            }

            let indexValue = metadata.get("index") ?? throw Exception("metadata is missing index")
            let indexObject = indexValue.asObject()
            if (requiredString(indexObject, "name") != name ||
                requiredString(indexObject, "version") != version ||
                !requiredString(indexObject, "organization").isEmpty()) {
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
                .join("default")
                .join(name)
                .join(version)
            let artifactPath = artifactDir.join("${name}-${version}.cjp")
            if (exists(artifactPath)) {
                respondError(context, 409, "artifact with the same name and version already exists")
                return
            }

            let firstLevel = name[..2]
            let secondLevel = if (name.size > 3) { name[2..4] } else { name[2..3] }
            let indexDir = Path(storage).join("index").join("default").join(firstLevel).join(secondLevel)
            let indexPath = indexDir.join(name)

            if (!exists(artifactDir)) {
                Directory.create(artifactDir, recursive: true)
            }
            if (!exists(indexDir)) {
                Directory.create(indexDir, recursive: true)
            }

            File.writeTo(artifactPath, payload.artifact)
            try {
                let indexLine = indexValue.toJsonString().replace("\r", "").replace("\n", "")
                File.appendTo(indexPath, "${indexLine}\n".toArray())
            } catch (e: Exception) {
                removeIfExists(artifactPath)
                throw e
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
