// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjrepo

import std.env.*
import std.convert.*
import std.fs.*
import std.collection.*
import stdx.net.http.*

private func configuredPort(): UInt16 {
    if (let Some(raw) <- getVariable("CJREPO_PORT")) {
        return UInt16.parse(raw)
    }
    return 8080
}

private func configuredAddress(): String {
    return getVariable("CJREPO_ADDRESS") ?? "127.0.0.1"
}

private func configuredStorage(): String {
    return getVariable("CJREPO_STORAGE") ?? Path(".").join("storage").toString()
}

private func configuredPublishToken(): String {
    return getVariable("CJREPO_PUBLISH_TOKEN") ?? ""
}

private func configuredReadToken(): String {
    return getVariable("CJREPO_READ_TOKEN") ?? ""
}

private func configuredUpstream(): String {
    return getVariable("CJREPO_UPSTREAM") ?? ""
}

private func configuredUpstreamToken(): String {
    return getVariable("CJREPO_UPSTREAM_TOKEN") ?? ""
}

private func configuredProxyTtlSeconds(): Int64 {
    let raw = getVariable("CJREPO_PROXY_TTL_SECONDS") ?? "86400"
    try {
        let value = Int64.parse(raw)
        if (value < 0) {
            throw Exception("TTL cannot be negative")
        }
        return value
    } catch (_: Exception) {
        eprintln("Warning: invalid CJREPO_PROXY_TTL_SECONDS, using 86400")
        return 86400
    }
}

// Check the client credential before touching local cache or upstream state.
private class ReadAuthorizationHandler <: HttpRequestHandler {
    private let handler: HttpRequestHandler
    private let token: String

    public init(handler: HttpRequestHandler, token: String) {
        this.handler = handler
        this.token = token
    }

    public func handle(context: HttpContext): Unit {
        if ((context.request.headers.getFirst("Authorization") ?? "") != token) {
            respondError(context, 401, "authentication failed")
            return
        }
        handler.handle(context)
    }
}

private class HostedIndexHandler <: HttpRequestHandler {
    private let storage: String
    private let relative: String

    public init(storage: String, relative: String) {
        this.storage = storage
        this.relative = relative
    }

    public func handle(context: HttpContext): Unit {
        try {
            let organization = requestedRegistryOrganization(context)
            let indexPath = Path(storage).join("index").join(organization).join(relative).toString()
            FileHandler(indexPath).handle(context)
        } catch (e: Exception) {
            respondError(context, 400, e.message)
        }
    }
}

private class ArtifactReadHandler <: HttpRequestHandler {
    private let storage: String
    private let upstream: String
    private let upstreamToken: String
    private let name: String
    private let version: String
    private let requestPath: String

    public init(storage: String, upstream: String, upstreamToken: String, name: String, version: String,
        requestPath: String) {
        this.storage = storage
        this.upstream = upstream
        this.upstreamToken = upstreamToken
        this.name = name
        this.version = version
        this.requestPath = requestPath
    }

    public func handle(context: HttpContext): Unit {
        var organization = "default"
        try {
            organization = requestedRegistryOrganization(context)
        } catch (e: Exception) {
            respondError(context, 400, e.message)
            return
        }
        let artifactPath = Path(storage)
            .join("artifacts")
            .join(organization)
            .join(name)
            .join(version)
            .join("${name}-${version}.cjp")
            .toString()
        if (exists(artifactPath)) {
            if (upstream.isEmpty()) {
                FileHandler(artifactPath).handle(context)
            } else {
                CacheHitHandler(artifactPath, requestPath).handle(context)
            }
        } else if (!upstream.isEmpty()) {
            ProxyArtifactHandler(storage, upstream, upstreamToken, name, version, organization).handle(context)
        } else {
            FileHandler(artifactPath).handle(context)
        }
    }
}

/**
 * Resolves the cjpm registry routes without changing cjpm's wire contract.
 *
 * Hosted and Proxy storage are partitioned by organization.
 */
private class RegistryDistributor <: HttpRequestDistributor {
    private let storage: String
    private let upstream: String
    private let upstreamToken: String
    private let readToken: String
    private let proxyTtlSeconds: Int64
    private let exactHandlers = HashMap<String, HttpRequestHandler>()

    public init(storage: String, upstream: String, upstreamToken: String, readToken: String,
        proxyTtlSeconds: Int64) {
        this.storage = storage
        this.upstream = upstream
        this.upstreamToken = upstreamToken
        this.readToken = readToken
        this.proxyTtlSeconds = proxyTtlSeconds
    }

    private func protectedRead(handler: HttpRequestHandler): HttpRequestHandler {
        return if (readToken.isEmpty()) { handler } else { ReadAuthorizationHandler(handler, readToken) }
    }

    public func register(path: String, handler: HttpRequestHandler): Unit {
        exactHandlers[path] = handler
    }

    public func distribute(path: String): HttpRequestHandler {
        if (exactHandlers.contains(path)) {
            return exactHandlers[path]
        }

        if (path.startsWith("/index/")) {
            let relative = path[7..]
            if (isSafeIndexPath(relative)) {
                if (!upstream.isEmpty()) {
                    return protectedRead(ProxyIndexHandler(storage, upstream,
                        upstreamToken, relative, proxyTtlSeconds))
                }
                return protectedRead(HostedIndexHandler(storage, relative))
            }
        }

        if (path.startsWith("/pkg/")) {
            let relative = path[5..]
            let segments = relative.split("/", removeEmpty: true)
            if (segments.size == 1 && isSafeSegment(segments[0])) {
                return PublishHandler(storage, segments[0], configuredPublishToken())
            }
            if (segments.size == 2 && isSafeSegment(segments[0]) && isSafeSegment(segments[1])) {
                let name = segments[0]
                let version = segments[1]
                return protectedRead(ArtifactReadHandler(storage, upstream,
                    upstreamToken, name, version, path))
            }
        }

        return NotFoundHandler()
    }

    private func isSafeIndexPath(relative: String): Bool {
        let segments = relative.split("/", removeEmpty: true)
        return segments.size == 3 && segments.all({ segment => isSafeSegment(segment) })
    }

    private func isSafeSegment(segment: String): Bool {
        return isSafePackageSegment(segment)
    }
}

main(): Int64 {
    try {
        let _ = outboundConnectTimeoutSeconds()
        let _ = maximumArtifactBytes()
        let _ = maximumIndexBytes()
        let _ = maximumHostedIndexBytes()
        let _ = maximumConcurrentPublishes()
    } catch (e: Exception) {
        eprintln("Error: ${e.message}")
        return 2
    }
    let arguments = getCommandLine()[1..]
    if (!arguments.isEmpty()) {
        match (arguments[0]) {
            case "mirror" => return if (runMirror(arguments[1..])) { 0 } else { 1 }
            case "mirror-manifest" => return if (runMirrorManifest(arguments[1..])) { 0 } else { 1 }
            case "mirror-watch" => return if (runMirrorWatch(arguments[1..])) { 0 } else { 1 }
            case "sync" => return if (runSync(arguments[1..])) { 0 } else { 1 }
            case "sync-manifest" => return if (runSyncManifest(arguments[1..])) { 0 } else { 1 }
            case "sync-watch" => return if (runSyncWatch(arguments[1..])) { 0 } else { 1 }
            case _ =>
                eprintln("Usage: cjrepo [mirror <upstream> <package> <version> | mirror-manifest <upstream> <file> | mirror-watch <upstream> <file> <interval-seconds> | sync <source> <destination> <package> <version> | sync-manifest <source> <destination> <file> | sync-watch <source> <destination> <file> <interval-seconds>]")
                return 2
        }
    }

    let rawUpstream = configuredUpstream()
    if (!rawUpstream.isEmpty() && !validateRegistryEndpoint(rawUpstream, "CJREPO_UPSTREAM")) {
        return 2
    }
    let upstream = if (rawUpstream.endsWith("/")) { rawUpstream[..rawUpstream.size - 1] } else { rawUpstream }
    let readToken = configuredReadToken()
    if (!readToken.isEmpty() && configuredPublishToken().isEmpty()) {
        eprintln("Error: CJREPO_PUBLISH_TOKEN is required when CJREPO_READ_TOKEN is set")
        return 2
    }
    let distributor = RegistryDistributor(configuredStorage(), upstream, configuredUpstreamToken(),
        readToken, configuredProxyTtlSeconds())
    distributor.register("/health", { context =>
        context.responseBuilder
            .header("Content-Type", "application/json; charset=utf-8")
            .body("{\"status\":\"ok\",\"service\":\"cjrepo\"}")
    })

    let address = configuredAddress()
    let server = ServerBuilder()
        .addr(address)
        .port(configuredPort())
        .maxRequestBodySize(maximumArtifactBytes() + MAX_PUBLISH_METADATA_BYTES + 10)
        .distributor(distributor)
        .build()

    println("CjRepo Server listening on http://${address}:${server.port}")
    println("CjRepo storage: ${configuredStorage()}")
    if (!upstream.isEmpty()) {
        println("CjRepo proxy upstream: ${upstream}")
        println("CjRepo proxy index TTL: ${configuredProxyTtlSeconds()} seconds")
    }
    server.serve()
    return 0
}
