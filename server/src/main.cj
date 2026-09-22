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

/**
 * Resolves the cjpm registry routes without changing cjpm's wire contract.
 *
 * The first hosted slice intentionally serves only the default organization.
 * Organization-aware routing and publishing are the next protocol slices.
 */
private class RegistryDistributor <: HttpRequestDistributor {
    private let storage: String
    private let exactHandlers = HashMap<String, HttpRequestHandler>()

    public init(storage: String) {
        this.storage = storage
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
                return FileHandler(indexPath)
            }
        }

        if (path.startsWith("/pkg/")) {
            let relative = path[5..]
            let segments = relative.split("/", removeEmpty: true)
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
        return !segment.isEmpty() && segment != "." && segment != ".." &&
            !segment.contains("\\") && !segment.contains(":")
    }
}

main() {
    let distributor = RegistryDistributor(configuredStorage())
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
    server.serve()
}
