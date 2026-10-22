// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjrepo

import std.env.*
import std.convert.*
import std.net.*
import stdx.net.http.*

func outboundConnectTimeoutSeconds(): Int64 {
    let raw = getVariable("CJREPO_CONNECT_TIMEOUT_SECONDS") ?? "30"
    try {
        let seconds = Int64.parse(raw)
        if (seconds < 1 || seconds > 300) {
            throw Exception("out of range")
        }
        return seconds
    } catch (_: Exception) {
        // Configuration errors must never echo the environment value.
        throw Exception("CJREPO_CONNECT_TIMEOUT_SECONDS must be an integer between 1 and 300")
    }
}

func outboundHttpClient(): Client {
    let timeout = Duration.second * outboundConnectTimeoutSeconds()
    return ClientBuilder().noProxy().autoRedirect(false).connector({ address: SocketAddress =>
        let socket = TcpSocket(address)
        try {
            socket.connect(timeout: timeout)
            return socket
        } catch (e: Exception) {
            socket.close()
            throw e
        }
    }).build()
}
