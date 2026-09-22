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

private func configuredStorage(): String {
    return getVariable("CJREPO_STORAGE") ?? Path(".").join("storage").toString()
}

private func configuredPublishToken(): String {
    return getVariable("CJREPO_PUBLISH_TOKEN") ?? ""
}

private func configuredUpstream(): String {
    let value = getVariable("CJREPO_UPSTREAM") ?? ""
    return if (value.endsWith("/")) { value[..value.size - 1] } else { value }
}

private func configuredUpstreamToken(): String {
    return getVariable("CJREPO_UPSTREAM_TOKEN") ?? ""
}

/**
 * Resolves the cjpm registry routes without changing cjpm's wire contract.
 *
 * The first hosted slice intentionally serves only the default organization.
 * Organization-aware routing and publishing are the next protocol slices.
 */
private class RegistryDistributor <: HttpRequestDistributor {
    private let storage: String
    private let upstream: String
    private let upstreamToken: String
    private let exactHandlers = HashMap<String, HttpRequestHandler>()

    public init(storage: String, upstream: String, upstreamToken: String) {
        this.storage = storage
        this.upstream = upstream
        this.upstreamToken = upstreamToken
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
                let indexPath = Path(storage).join("index").join("default").join(relative).toString()
                if (exists(indexPath)) {
                    return if (upstream.isEmpty()) { FileHandler(indexPath) } else { CacheHitHandler(indexPath, path) }
                }
                if (!upstream.isEmpty()) {
                    return ProxyIndexHandler(storage, upstream, upstreamToken, relative)
                }
                return FileHandler(indexPath)
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
                let artifactPath = Path(storage)
                    .join("artifacts")
                    .join("default")
                    .join(name)
                    .join(version)
                    .join("${name}-${version}.cjp")
                    .toString()
                if (exists(artifactPath)) {
                    return if (upstream.isEmpty()) { FileHandler(artifactPath) } else { CacheHitHandler(artifactPath, path) }
                }
                if (!upstream.isEmpty()) {
                    return ProxyArtifactHandler(storage, upstream, upstreamToken, name, version)
                }
                return FileHandler(artifactPath)
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

main() {
    let distributor = RegistryDistributor(configuredStorage(), configuredUpstream(), configuredUpstreamToken())
    distributor.register("/health", { context =>
        context.responseBuilder
            .header("Content-Type", "application/json; charset=utf-8")
            .body("{\"status\":\"ok\",\"service\":\"cjrepo\"}")
    })

    let server = ServerBuilder()
        .addr("127.0.0.1")
        .port(configuredPort())
        .distributor(distributor)
        .build()

    println("CjRepo Server listening on http://127.0.0.1:${server.port}")
    println("CjRepo storage: ${configuredStorage()}")
    if (!configuredUpstream().isEmpty()) {
        println("CjRepo proxy upstream: ${configuredUpstream()}")
    }
    server.serve()
}
