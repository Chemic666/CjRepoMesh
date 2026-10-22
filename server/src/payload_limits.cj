// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjrepo

import std.env.*
import std.convert.*

let MAX_PUBLISH_METADATA_BYTES: Int64 = 1024 * 1024

private func configuredPayloadLimit(name: String, fallback: Int64, maximum: Int64): Int64 {
    if (let Some(raw) <- getVariable(name)) {
        try {
            let value = Int64.parse(raw)
            if (value < 1 || value > maximum) {
                throw Exception("out of range")
            }
            return value
        } catch (_: Exception) {
            throw Exception("${name} must be an integer between 1 and ${maximum}")
        }
    }
    return fallback
}

func maximumArtifactBytes(): Int64 {
    return configuredPayloadLimit("CJREPO_MAX_ARTIFACT_BYTES", 128 * 1024 * 1024, 1024 * 1024 * 1024)
}

func maximumIndexBytes(): Int64 {
    return configuredPayloadLimit("CJREPO_MAX_INDEX_BYTES", 4 * 1024 * 1024, 64 * 1024 * 1024)
}

class PayloadTooLargeException <: Exception {
    public init() {
        super("payload exceeds configured byte limit")
    }
}

func ensurePayloadFits(current: Int64, incoming: Int64, limit: Int64): Unit {
    if (incoming > limit - current) {
        throw PayloadTooLargeException()
    }
}
