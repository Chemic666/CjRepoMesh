// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjrepo

// Match the client's base-address safety boundary. These addresses can reach
// native startup logs and HTTP exceptions, so credentials belong in headers.
func validateRegistryEndpoint(address: String, role: String): Bool {
    if (safeRegistryEndpoint(address)) {
        return true
    }
    eprintln("Error: invalid ${role} URL; expected an absolute HTTP(S) base without credentials, " +
        "query, fragment, backslash or whitespace. Use token environment variables for authentication.")
    return false
}

private func safeRegistryEndpoint(address: String): Bool {
    let lower = address.toAsciiLower()
    let prefixSize = if (lower.startsWith("https://")) { 8 } else if (lower.startsWith("http://")) { 7 } else {
        return false
    }
    if (address.size <= prefixSize || address.contains("?") || address.contains("#") || address.contains("\\")) {
        return false
    }
    for (byte in address.toArray()) {
        if (byte <= 32 || byte == 127) {
            return false
        }
    }
    let authority = address[prefixSize..].split("/", removeEmpty: false)[0]
    return !authority.isEmpty() && !authority.contains("@") && !authority.contains("%")
}
