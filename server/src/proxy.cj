// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjrepo

import std.collection.*
import std.fs.*
import std.sync.*
import std.time.*
import stdx.net.http.*
import stdx.crypto.digest.*
import stdx.encoding.hex.*
import stdx.encoding.json.*

class CacheHitHandler <: HttpRequestHandler {
    private let path: String
    private let requestPath: String

    public init(path: String, requestPath: String) {
        this.path = path
        this.requestPath = requestPath
    }

    public func handle(context: HttpContext): Unit {
        println("[proxy] path=${requestPath} cache=HIT")
        FileHandler(path).handle(context)
    }
}

class ProxyIndexHandler <: HttpRequestHandler {
    private let storage: String
    private let upstream: String
    private let upstreamToken: String
    private let relative: String
    private let ttlSeconds: Int64

    public init(storage: String, upstream: String, upstreamToken: String, relative: String, ttlSeconds: Int64) {
        this.storage = storage
        this.upstream = upstream
        this.upstreamToken = upstreamToken
        this.relative = relative
        this.ttlSeconds = ttlSeconds
    }

    public func handle(context: HttpContext): Unit {
        let requestPath = "/index/${relative}"
        var organization = "default"
        try {
            organization = requestedRegistryOrganization(context)
        } catch (e: Exception) {
            respondError(context, 400, e.message)
            return
        }
        try {
            let upstreamPath = if (organization == "default") { requestPath } else {
                "${requestPath}?organization=${organization}"
            }
            println("[proxy] path=${upstreamPath} cache=MISS upstream=${upstream}")
            let cachePath = Path(storage).join("index").join(organization).join(relative)
            let segments = relative.split("/", removeEmpty: true)
            let expectedName = segments[segments.size - 1]
            var responseStatus: UInt16 = 200
            var responseBody = "".toArray()
            var cacheResult = "MISS"
            synchronized(packageStorageLock(storage, organization, expectedName)) {
                if (proxyCacheIsFresh(cachePath, ttlSeconds)) {
                    responseBody = File.readFrom(cachePath)
                    cacheResult = "HIT_AFTER_WAIT"
                } else {
                    let (upstreamStatus, upstreamBody) = fetchUpstream(upstream, upstreamToken, upstreamPath)
                    responseStatus = upstreamStatus
                    responseBody = upstreamBody
                    if (upstreamStatus == 200) {
                        let normalized = ArrayList<String>()
                        for (line in String.fromUtf8(upstreamBody).lines()) {
                            if (line.trimAscii().isEmpty()) {
                                continue
                            }
                            let value = JsonValue.fromStr(line)
                            let object = value.asObject()
                            if (jsonString(object, "name") != expectedName ||
                                jsonString(object, "organization") != metadataOrganization(organization) ||
                                jsonString(object, "version").isEmpty() ||
                                jsonString(object, "sha256sum").isEmpty()) {
                                throw Exception("upstream returned an invalid package index")
                            }
                            normalized.add(value.toJsonString().replace("\r", "").replace("\n", ""))
                        }
                        if (normalized.isEmpty()) {
                            throw Exception("upstream returned an empty package index")
                        }
                        var cacheText = ""
                        for (line in normalized) {
                            cacheText += "${line}\n"
                        }
                        responseBody = cacheText.toArray()
                        ensureParent(cachePath)
                        writeFileAtomically(cachePath, responseBody)
                    }
                }
            }
            println("[proxy] path=${upstreamPath} fill=${cacheResult}")
            proxyResponse(context, responseStatus, responseBody)
        } catch (e: Exception) {
            respondError(context, 502, "proxy index fetch failed: ${e.message}")
        }
    }
}

func proxyCacheIsFresh(path: Path, ttlSeconds: Int64): Bool {
    if (!exists(path) || ttlSeconds == 0) {
        return false
    }
    let now = DateTime.now().toUnixTimeStamp().toSeconds()
    let modified = FileInfo(path).lastModificationTime.toUnixTimeStamp().toSeconds()
    return now - modified < ttlSeconds
}

class ProxyArtifactHandler <: HttpRequestHandler {
    private let storage: String
    private let upstream: String
    private let upstreamToken: String
    private let name: String
    private let version: String
    private let organization: String

    public init(storage: String, upstream: String, upstreamToken: String, name: String, version: String,
        organization: String) {
        this.storage = storage
        this.upstream = upstream
        this.upstreamToken = upstreamToken
        this.name = name
        this.version = version
        this.organization = organization
    }

    public func handle(context: HttpContext): Unit {
        let basePath = "/pkg/${name}/${version}"
        let requestPath = if (organization == "default") { basePath } else {
            "${basePath}?organization=${organization}"
        }
        println("[proxy] path=${requestPath} cache=MISS upstream=${upstream}")
        try {
            let cachePath = Path(storage)
                .join("artifacts")
                .join(organization)
                .join(name)
                .join(version)
                .join("${name}-${version}.cjp")
            var responseStatus: UInt16 = 200
            var responseBody = "".toArray()
            var cacheResult = "MISS"
            synchronized(packageStorageLock(storage, organization, name)) {
                if (exists(cachePath)) {
                    responseBody = File.readFrom(cachePath)
                    cacheResult = "HIT_AFTER_WAIT"
                } else {
                    let (upstreamStatus, upstreamBody) = fetchUpstream(upstream, upstreamToken, requestPath)
                    responseStatus = upstreamStatus
                    responseBody = upstreamBody
                    if (upstreamStatus == 200) {
                        let expectedChecksum = checksumFromCachedIndex(storage, organization, name, version)
                        let sha256 = SHA256()
                        sha256.write(upstreamBody)
                        let actualChecksum = toHexString(sha256.finish())
                        if (actualChecksum != expectedChecksum) {
                            throw Exception("upstream artifact SHA-256 does not match its cached index")
                        }
                        ensureParent(cachePath)
                        writeFileAtomically(cachePath, upstreamBody)
                    }
                }
            }
            println("[proxy] path=${requestPath} fill=${cacheResult}")
            proxyResponse(context, responseStatus, responseBody)
        } catch (e: Exception) {
            respondError(context, 502, "proxy artifact fetch failed: ${e.message}")
        }
    }
}

func fetchUpstream(upstream: String, token: String, path: String): (UInt16, Array<UInt8>) {
    let client = ClientBuilder().noProxy().autoRedirect(false).build()
    try {
        let requestBuilder = HttpRequestBuilder().method("GET").url("${upstream}${path}")
        if (!token.isEmpty()) {
            requestBuilder.header("Authorization", token)
        }
        let response = client.send(requestBuilder.build())
        let buffer = ArrayList<UInt8>()
        while (true) {
            let chunk = Array<UInt8>(64 * 1024, repeat: 0)
            let readSize = response.body.read(chunk)
            if (readSize == 0) {
                break
            }
            buffer.add(all: chunk[..readSize])
        }
        return (response.status, buffer.toArray())
    } finally {
        client.close()
    }
}

func checksumFromCachedIndex(storage: String, organization: String, name: String, version: String): String {
    let firstLevel = name[..2]
    let secondLevel = if (name.size > 3) { name[2..4] } else { name[2..3] }
    let indexPath = Path(storage).join("index").join(organization).join(firstLevel).join(secondLevel).join(name)
    if (!exists(indexPath)) {
        throw Exception("package index is not cached before artifact download")
    }
    for (line in String.fromUtf8(File.readFrom(indexPath)).lines()) {
        if (line.trimAscii().isEmpty()) {
            continue
        }
        let object = JsonValue.fromStr(line).asObject()
        if (jsonString(object, "version") == version) {
            return jsonString(object, "sha256sum")
        }
    }
    throw Exception("requested version is missing from the cached package index")
}

func jsonString(object: JsonObject, field: String): String {
    let value = object.get(field) ?? throw Exception("index is missing ${field}")
    return value.asString().getValue()
}

private func proxyResponse(context: HttpContext, status: UInt16, body: Array<UInt8>): Unit {
    context.responseBuilder
        .status(status)
        .header("Content-Type", "application/octet-stream")
        .body(body)
}
