// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjrepo

import std.env.*
import std.convert.*
import std.net.*
import stdx.net.http.*
import stdx.net.tls.*
import stdx.net.tls.common.*
import stdx.encoding.url.*
import stdx.crypto.x509.X509Certificate

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

func outboundHttpClient(address: String): Client {
    let timeout = Duration.second * outboundConnectTimeoutSeconds()
    let url = URL.parse(address)
    let https = url.scheme.toAsciiLower() == "https"
    let ip = IPAddress.tryParse(url.hostName)
    var config = TlsClientConfig()
    if (https && ip.isNone()) {
        config.serverName = Some(url.hostName)
    }
    return ClientBuilder().noProxy().autoRedirect(false).tlsConfig(config)
        .connector(outboundSocketConnector(https, ip, config, timeout)).build()
}

private func outboundSocketConnector(https: Bool, ip: Option<IPAddress>, config: TlsClientConfig,
    timeout: Duration): (SocketAddress) -> StreamingSocket {
    return { address: SocketAddress =>
        let socket = TcpSocket(address)
        try {
            socket.connect(timeout: timeout)
        } catch (e: Exception) {
            socket.close()
            throw e
        }
        if (!https) {
            return socket
        }
        let tls = try {
            TlsSocket.client(socket, clientConfig: config)
        } catch (e: Exception) {
            socket.close()
            throw e
        }
        try {
            // Separate handshake I/O waits; the configurable option remains TCP-only.
            let result = tls.handshake(timeout: Some(Duration.second * 30))
            if (let Some(expectedIp) <- ip) {
                if (result.peerCertificate.isEmpty()) {
                    throw TlsException("TLS server certificate is missing")
                }
                let certificate = result.peerCertificate[0] as X509Certificate ??
                    throw TlsException("TLS server certificate type is unsupported")
                let expected = expectedIp.getAddressBytes()
                var matches = false
                // stdx's serverName is DNS-only. Compare authenticated IP SAN bytes
                // after default chain, time and server-purpose verification.
                for (candidate in certificate.IPAddresses) {
                    if (candidate.size == expected.size) {
                        var equal = true
                        for (i in 0..expected.size) {
                            if (candidate[i] != expected[i]) {
                                equal = false
                                break
                            }
                        }
                        matches = matches || equal
                    }
                }
                if (!matches) {
                    throw TlsException("TLS server IP identity mismatch")
                }
            }
            return tls
        } catch (e: Exception) {
            tls.close()
            throw e
        }
    }
}
