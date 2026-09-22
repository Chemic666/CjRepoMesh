// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjrepo

import std.collection.*
import std.env.*
import std.fs.*
import stdx.net.http.*
import stdx.crypto.digest.*
import stdx.encoding.hex.*
import stdx.encoding.json.*

func runMirror(arguments: Array<String>): Bool {
    if (arguments.size != 3) {
        eprintln("Usage: cjrepo mirror <upstream> <package> <version>")
        return false
    }
    let upstream = trimTrailingSlash(arguments[0])
    let name = arguments[1]
    let version = arguments[2]
    if (!isSafePackageSegment(name) || !isSafePackageSegment(version) || name.size < 3) {
        eprintln("Error: invalid package name or version")
        return false
    }

    let storage = getVariable("CJREPO_STORAGE") ?? Path(".").join("storage").toString()
    let token = getVariable("CJREPO_UPSTREAM_TOKEN") ?? ""
    try {
        if (cachedArtifactIsValid(storage, name, version)) {
            println("[mirror] package=${name} version=${version} result=SKIP reason=already-valid")
            return true
        }
        let (indexBody, _, expectedChecksum) = fetchIndexVersion(upstream, token, name, version)
        let (artifactStatus, artifact) = fetchUpstream(upstream, token, "/pkg/${name}/${version}")
        if (artifactStatus != 200) {
            throw Exception("upstream artifact returned status ${artifactStatus}")
        }
        verifyChecksum(artifact, expectedChecksum)

        let indexPath = indexCachePath(storage, name)
        let artifactPath = artifactCachePath(storage, name, version)
        ensureParent(indexPath)
        ensureParent(artifactPath)
        File.writeTo(indexPath, indexBody)
        File.writeTo(artifactPath, artifact)
        println("[mirror] package=${name} version=${version} result=SYNCED checksum=${expectedChecksum}")
        return true
    } catch (e: Exception) {
        eprintln("Error: mirror failed: ${e.message}")
        return false
    }
}

func runSync(arguments: Array<String>): Bool {
    if (arguments.size != 4) {
        eprintln("Usage: cjrepo sync <source> <destination> <package> <version>")
        return false
    }
    let source = trimTrailingSlash(arguments[0])
    let destination = trimTrailingSlash(arguments[1])
    let name = arguments[2]
    let version = arguments[3]
    if (!isSafePackageSegment(name) || !isSafePackageSegment(version) || name.size < 3) {
        eprintln("Error: invalid package name or version")
        return false
    }

    let sourceToken = getVariable("CJREPO_UPSTREAM_TOKEN") ?? ""
    let destinationToken = getVariable("CJREPO_SYNC_DESTINATION_TOKEN") ?? ""
    try {
        let (_, indexLine, expectedChecksum) = fetchIndexVersion(source, sourceToken, name, version)
        let (artifactStatus, artifact) = fetchUpstream(source, sourceToken, "/pkg/${name}/${version}")
        if (artifactStatus != 200) {
            throw Exception("source artifact returned status ${artifactStatus}")
        }
        verifyChecksum(artifact, expectedChecksum)

        let metadata = "{\"organization\":\"\",\"name\":\"${name}\",\"version\":\"${version}\",\"index\":${indexLine}}".toArray()
        let frame = ArrayList<UInt8>()
        frame.add(1)
        frame.add(all: encodeLittleEndianSize(metadata.size))
        frame.add(all: metadata)
        frame.add(1)
        frame.add(all: encodeLittleEndianSize(artifact.size))
        frame.add(all: artifact)

        let client = ClientBuilder().noProxy().build()
        try {
            let requestBuilder = HttpRequestBuilder()
                .method("POST")
                .url("${destination}/pkg/${name}")
                .body(frame.toArray())
            if (!destinationToken.isEmpty()) {
                requestBuilder.header("Authorization", destinationToken)
            }
            let response = client.send(requestBuilder.build())
            drain(response)
            if (response.status == 200) {
                println("[sync] package=${name} version=${version} result=SYNCED")
                return true
            }
            if (response.status == 409) {
                println("[sync] package=${name} version=${version} result=SKIP reason=already-exists")
                return true
            }
            throw Exception("destination returned status ${response.status}")
        } finally {
            client.close()
        }
    } catch (e: Exception) {
        eprintln("Error: repository sync failed: ${e.message}")
        return false
    }
}

private func fetchIndexVersion(upstream: String, token: String, name: String, version: String): (Array<UInt8>, String, String) {
    let path = indexRequestPath(name)
    let (status, body) = fetchUpstream(upstream, token, path)
    if (status != 200) {
        throw Exception("upstream index returned status ${status}")
    }
    var selectedLine = ""
    var expectedChecksum = ""
    for (line in String.fromUtf8(body).lines()) {
        if (line.trimAscii().isEmpty()) {
            continue
        }
        let value = JsonValue.fromStr(line)
        let object = value.asObject()
        if (jsonString(object, "name") != name || !jsonString(object, "organization").isEmpty()) {
            throw Exception("upstream returned an invalid package index")
        }
        if (jsonString(object, "version") == version) {
            selectedLine = value.toJsonString().replace("\r", "").replace("\n", "")
            expectedChecksum = jsonString(object, "sha256sum")
        }
    }
    if (selectedLine.isEmpty() || expectedChecksum.isEmpty()) {
        throw Exception("requested version is missing from upstream index")
    }
    return (body, selectedLine, expectedChecksum)
}

private func cachedArtifactIsValid(storage: String, name: String, version: String): Bool {
    let indexPath = indexCachePath(storage, name)
    let artifactPath = artifactCachePath(storage, name, version)
    if (!exists(indexPath) || !exists(artifactPath)) {
        return false
    }
    try {
        let expectedChecksum = checksumFromCachedIndex(storage, name, version)
        let sha256 = SHA256()
        sha256.write(File.readFrom(artifactPath))
        return toHexString(sha256.finish()) == expectedChecksum
    } catch (_: Exception) {
        return false
    }
}

private func verifyChecksum(artifact: Array<UInt8>, expected: String): Unit {
    let sha256 = SHA256()
    sha256.write(artifact)
    if (toHexString(sha256.finish()) != expected) {
        throw Exception("artifact SHA-256 does not match source index")
    }
}

private func indexRequestPath(name: String): String {
    let firstLevel = name[..2]
    let secondLevel = if (name.size > 3) { name[2..4] } else { name[2..3] }
    return "/index/${firstLevel}/${secondLevel}/${name}"
}

private func indexCachePath(storage: String, name: String): Path {
    return Path(storage).join("index").join("default").join(indexRequestPath(name)[7..])
}

private func artifactCachePath(storage: String, name: String, version: String): Path {
    return Path(storage).join("artifacts").join("default").join(name).join(version).join("${name}-${version}.cjp")
}

private func encodeLittleEndianSize(size: Int64): Array<UInt8> {
    return [
        UInt8(size % 256),
        UInt8((size / 256) % 256),
        UInt8((size / 65536) % 256),
        UInt8((size / 16777216) % 256)
    ]
}

private func drain(response: HttpResponse): Unit {
    while (true) {
        let buffer = Array<UInt8>(4096, repeat: 0)
        if (response.body.read(buffer) == 0) {
            return
        }
    }
}

private func trimTrailingSlash(value: String): String {
    return if (value.endsWith("/")) { value[..value.size - 1] } else { value }
}
