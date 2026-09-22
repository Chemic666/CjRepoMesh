// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjrepo

import std.collection.*
import std.fs.*
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

    public init(storage: String, upstream: String, upstreamToken: String, relative: String) {
        this.storage = storage
        this.upstream = upstream
        this.upstreamToken = upstreamToken
        this.relative = relative
    }

    public func handle(context: HttpContext): Unit {
        let requestPath = "/index/${relative}"
        println("[proxy] path=${requestPath} cache=MISS upstream=${upstream}")
        try {
            let (status, body) = fetchUpstream(upstream, upstreamToken, requestPath)
            if (status != 200) {
                proxyResponse(context, status, body)
                return
            }

            let segments = relative.split("/", removeEmpty: true)
            let expectedName = segments[segments.size - 1]
            let normalized = ArrayList<String>()
            for (line in String.fromUtf8(body).lines()) {
                if (line.trimAscii().isEmpty()) {
                    continue
                }
                let value = JsonValue.fromStr(line)
                let object = value.asObject()
                if (jsonString(object, "name") != expectedName ||
                    !jsonString(object, "organization").isEmpty() ||
                    jsonString(object, "version").isEmpty() ||
                    jsonString(object, "sha256sum").isEmpty()) {
                    throw Exception("upstream returned an invalid package index")
                }
                normalized.add(value.toJsonString().replace("\r", "").replace("\n", ""))
            }
            if (normalized.isEmpty()) {
                throw Exception("upstream returned an empty package index")
            }

            let cachePath = Path(storage).join("index").join("default").join(relative)
            ensureParent(cachePath)
            var cacheText = ""
            for (line in normalized) {
                cacheText += "${line}\n"
            }
            let cacheBody = cacheText.toArray()
            File.writeTo(cachePath, cacheBody)
            proxyResponse(context, 200, cacheBody)
        } catch (e: Exception) {
            respondError(context, 502, "proxy index fetch failed: ${e.message}")
        }
    }
}

class ProxyArtifactHandler <: HttpRequestHandler {
    private let storage: String
    private let upstream: String
    private let upstreamToken: String
    private let name: String
    private let version: String

    public init(storage: String, upstream: String, upstreamToken: String, name: String, version: String) {
        this.storage = storage
        this.upstream = upstream
        this.upstreamToken = upstreamToken
        this.name = name
        this.version = version
    }

    public func handle(context: HttpContext): Unit {
        let requestPath = "/pkg/${name}/${version}"
        println("[proxy] path=${requestPath} cache=MISS upstream=${upstream}")
        try {
            let (status, body) = fetchUpstream(upstream, upstreamToken, requestPath)
            if (status != 200) {
                proxyResponse(context, status, body)
                return
            }

            let expectedChecksum = checksumFromCachedIndex(storage, name, version)
            let sha256 = SHA256()
            sha256.write(body)
            let actualChecksum = toHexString(sha256.finish())
            if (actualChecksum != expectedChecksum) {
                throw Exception("upstream artifact SHA-256 does not match its cached index")
            }

            let cachePath = Path(storage)
                .join("artifacts")
                .join("default")
                .join(name)
                .join(version)
                .join("${name}-${version}.cjp")
            ensureParent(cachePath)
            File.writeTo(cachePath, body)
            proxyResponse(context, 200, body)
        } catch (e: Exception) {
            respondError(context, 502, "proxy artifact fetch failed: ${e.message}")
        }
    }
}

func fetchUpstream(upstream: String, token: String, path: String): (UInt16, Array<UInt8>) {
    let client = ClientBuilder().noProxy().build()
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

func checksumFromCachedIndex(storage: String, name: String, version: String): String {
    let firstLevel = name[..2]
    let secondLevel = if (name.size > 3) { name[2..4] } else { name[2..3] }
    let indexPath = Path(storage).join("index").join("default").join(firstLevel).join(secondLevel).join(name)
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

func ensureParent(path: Path): Unit {
    let parent = path.parent
    if (!exists(parent)) {
        Directory.create(parent, recursive: true)
    }
}

private func proxyResponse(context: HttpContext, status: UInt16, body: Array<UInt8>): Unit {
    context.responseBuilder
        .status(status)
        .header("Content-Type", "application/octet-stream")
        .body(body)
}
