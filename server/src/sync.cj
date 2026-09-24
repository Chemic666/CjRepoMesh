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
    let packageSpec = arguments[1]
    let version = arguments[2]
    let (organization, name) = try {
        parseMirrorPackage(packageSpec)
    } catch (e: Exception) {
        eprintln("Error: ${e.message}")
        return false
    }
    if (!isSafePackageSegment(version)) {
        eprintln("Error: invalid package name or version")
        return false
    }

    let storage = getVariable("CJREPO_STORAGE") ?? Path(".").join("storage").toString()
    let token = getVariable("CJREPO_UPSTREAM_TOKEN") ?? ""
    try {
        if (cachedArtifactIsValid(storage, organization, name, version)) {
            println("[mirror] package=${packageSpec} version=${version} result=SKIP reason=already-valid")
            return true
        }
        let (indexBody, _, expectedChecksum) = fetchIndexVersion(upstream, token, organization, name, version)
        let (artifactStatus, artifact) = fetchUpstream(upstream, token,
            organizationRequestPath("/pkg/${name}/${version}", organization))
        if (artifactStatus != 200) {
            throw Exception("upstream artifact returned status ${artifactStatus}")
        }
        verifyChecksum(artifact, expectedChecksum)

        let indexPath = indexCachePath(storage, organization, name)
        let artifactPath = artifactCachePath(storage, organization, name, version)
        ensureParent(indexPath)
        ensureParent(artifactPath)
        File.writeTo(indexPath, indexBody)
        File.writeTo(artifactPath, artifact)
        println("[mirror] package=${packageSpec} version=${version} result=SYNCED checksum=${expectedChecksum}")
        return true
    } catch (e: Exception) {
        eprintln("Error: mirror failed: ${e.message}")
        return false
    }
}

/**
 * Mirrors every package/version pair in a plain-text manifest.
 *
 * Blank lines and lines beginning with '#' are ignored. Each remaining line
 * must contain exactly two space-separated fields: package and version. The
 * package may be organization-qualified as organization::package. A bad entry
 * does not prevent later entries from being attempted; the final status is
 * unsuccessful if any entry failed.
 */
func runMirrorManifest(arguments: Array<String>): Bool {
    if (arguments.size != 2) {
        eprintln("Usage: cjrepo mirror-manifest <upstream> <file>")
        return false
    }

    let upstream = trimTrailingSlash(arguments[0])
    let manifestPath = arguments[1]
    var total: Int64 = 0
    var succeeded: Int64 = 0
    var failed: Int64 = 0

    try {
        let content = String.fromUtf8(File.readFrom(manifestPath))
        var lineNumber: Int64 = 0
        for (rawLine in content.lines()) {
            lineNumber += 1
            let line = rawLine.trimAscii()
            if (line.isEmpty() || line.startsWith("#")) {
                continue
            }

            total += 1
            let fields = line.split(" ", removeEmpty: true)
            if (fields.size != 2) {
                failed += 1
                eprintln("[mirror-manifest] line=${lineNumber} result=FAILED reason=expected-package-and-version")
                continue
            }

            if (runMirror([upstream, fields[0], fields[1]])) {
                succeeded += 1
            } else {
                failed += 1
                eprintln("[mirror-manifest] line=${lineNumber} package=${fields[0]} version=${fields[1]} result=FAILED")
            }
        }
    } catch (e: Exception) {
        eprintln("Error: cannot read mirror manifest '${manifestPath}': ${e.message}")
        return false
    }

    println("[mirror-manifest] total=${total} succeeded=${succeeded} failed=${failed}")
    if (total == 0) {
        eprintln("Error: mirror manifest contains no package entries")
        return false
    }
    return failed == 0
}

func runSync(arguments: Array<String>): Bool {
    if (arguments.size != 4) {
        eprintln("Usage: cjrepo sync <source> <destination> <package> <version>")
        return false
    }
    let source = trimTrailingSlash(arguments[0])
    let destination = trimTrailingSlash(arguments[1])
    let packageSpec = arguments[2]
    let version = arguments[3]
    let (organization, name) = try {
        parseMirrorPackage(packageSpec)
    } catch (e: Exception) {
        eprintln("Error: ${e.message}")
        return false
    }
    if (!isSafePackageSegment(version)) {
        eprintln("Error: invalid package name or version")
        return false
    }

    let sourceToken = getVariable("CJREPO_UPSTREAM_TOKEN") ?? ""
    let destinationToken = getVariable("CJREPO_SYNC_DESTINATION_TOKEN") ?? ""
    let destinationReadToken = getVariable("CJREPO_SYNC_DESTINATION_READ_TOKEN") ?? ""
    try {
        let (_, indexLine, expectedChecksum) = fetchIndexVersion(source, sourceToken, organization, name, version)
        if (destinationHasVersion(destination, destinationReadToken, organization, name, version,
            expectedChecksum)) {
            println("[sync] package=${packageSpec} version=${version} result=SKIP reason=already-valid")
            return true
        }
        let (artifactStatus, artifact) = fetchUpstream(source, sourceToken,
            organizationRequestPath("/pkg/${name}/${version}", organization))
        if (artifactStatus != 200) {
            throw Exception("source artifact returned status ${artifactStatus}")
        }
        verifyChecksum(artifact, expectedChecksum)

        let metadata = "{\"organization\":\"${metadataOrganization(organization)}\",\"name\":\"${name}\",\"version\":\"${version}\",\"index\":${indexLine}}".toArray()
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
                .url("${destination}${organizationRequestPath("/pkg/${name}", organization)}")
                .body(frame.toArray())
            if (!destinationToken.isEmpty()) {
                requestBuilder.header("Authorization", destinationToken)
            }
            let response = client.send(requestBuilder.build())
            drain(response)
            if (response.status == 200) {
                println("[sync] package=${packageSpec} version=${version} result=SYNCED")
                return true
            }
            if (response.status == 409) {
                if (destinationHasVersion(destination, destinationReadToken, organization, name, version,
                    expectedChecksum)) {
                    println("[sync] package=${packageSpec} version=${version} result=SKIP reason=concurrent-publish")
                    return true
                }
                throw Exception("destination version conflicts with source checksum")
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

private func destinationHasVersion(destination: String, token: String, organization: String, name: String,
    version: String, expectedChecksum: String): Bool {
    let path = organizationRequestPath(indexRequestPath(name), organization)
    let (status, body) = fetchUpstream(destination, token, path)
    if (status == 404) {
        return false
    }
    if (status != 200) {
        throw Exception("destination index returned status ${status}")
    }
    var found = false
    var sawEntry = false
    for (line in String.fromUtf8(body).lines()) {
        if (line.trimAscii().isEmpty()) {
            continue
        }
        sawEntry = true
        let object = JsonValue.fromStr(line).asObject()
        if (jsonString(object, "name") != name ||
            jsonString(object, "organization") != metadataOrganization(organization)) {
            throw Exception("destination returned an invalid package index")
        }
        if (jsonString(object, "version") == version) {
            if (found) {
                throw Exception("destination index contains a duplicate version")
            }
            if (jsonString(object, "sha256sum") != expectedChecksum) {
                throw Exception("destination version conflicts with source checksum")
            }
            found = true
        }
    }
    if (!sawEntry) {
        throw Exception("destination returned an empty package index")
    }
    return found
}

/**
 * Synchronizes every package/version pair in a plain-text manifest.
 *
 * Parsing and summary behavior matches mirror-manifest: malformed or failed
 * entries are reported, later entries are still attempted, and any failure
 * makes the command return a non-zero status.
 */
func runSyncManifest(arguments: Array<String>): Bool {
    if (arguments.size != 3) {
        eprintln("Usage: cjrepo sync-manifest <source> <destination> <file>")
        return false
    }

    let source = trimTrailingSlash(arguments[0])
    let destination = trimTrailingSlash(arguments[1])
    let manifestPath = arguments[2]
    var total: Int64 = 0
    var succeeded: Int64 = 0
    var failed: Int64 = 0

    try {
        let content = String.fromUtf8(File.readFrom(manifestPath))
        var lineNumber: Int64 = 0
        for (rawLine in content.lines()) {
            lineNumber += 1
            let line = rawLine.trimAscii()
            if (line.isEmpty() || line.startsWith("#")) {
                continue
            }

            total += 1
            let fields = line.split(" ", removeEmpty: true)
            if (fields.size != 2) {
                failed += 1
                eprintln("[sync-manifest] line=${lineNumber} result=FAILED reason=expected-package-and-version")
                continue
            }

            if (runSync([source, destination, fields[0], fields[1]])) {
                succeeded += 1
            } else {
                failed += 1
                eprintln("[sync-manifest] line=${lineNumber} package=${fields[0]} version=${fields[1]} result=FAILED")
            }
        }
    } catch (e: Exception) {
        eprintln("Error: cannot read sync manifest '${manifestPath}': ${e.message}")
        return false
    }

    println("[sync-manifest] total=${total} succeeded=${succeeded} failed=${failed}")
    if (total == 0) {
        eprintln("Error: sync manifest contains no package entries")
        return false
    }
    return failed == 0
}

private func fetchIndexVersion(upstream: String, token: String, organization: String, name: String,
    version: String): (Array<UInt8>, String, String) {
    let path = organizationRequestPath(indexRequestPath(name), organization)
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
        if (jsonString(object, "name") != name ||
            jsonString(object, "organization") != metadataOrganization(organization)) {
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

private func cachedArtifactIsValid(storage: String, organization: String, name: String, version: String): Bool {
    let indexPath = indexCachePath(storage, organization, name)
    let artifactPath = artifactCachePath(storage, organization, name, version)
    if (!exists(indexPath) || !exists(artifactPath)) {
        return false
    }
    try {
        let expectedChecksum = checksumFromCachedIndex(storage, organization, name, version)
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

private func indexCachePath(storage: String, organization: String, name: String): Path {
    return Path(storage).join("index").join(organization).join(indexRequestPath(name)[7..])
}

private func artifactCachePath(storage: String, organization: String, name: String, version: String): Path {
    return Path(storage).join("artifacts").join(organization).join(name).join(version).join("${name}-${version}.cjp")
}

private func organizationRequestPath(path: String, organization: String): String {
    return if (organization == "default") { path } else { "${path}?organization=${organization}" }
}

private func parseMirrorPackage(spec: String): (String, String) {
    let parts = spec.split("::", removeEmpty: true)
    let organization = if (parts.size == 1 && parts[0] == spec) { "default" } else if (
        parts.size == 2 && spec == "${parts[0]}::${parts[1]}" && isNamedRegistryOrganization(parts[0])
    ) { parts[0] } else { throw Exception("invalid organization-qualified package") }
    let name = parts[parts.size - 1]
    if (!isSafePackageSegment(name) || name.size < 3) {
        throw Exception("invalid package name")
    }
    return (organization, name)
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
