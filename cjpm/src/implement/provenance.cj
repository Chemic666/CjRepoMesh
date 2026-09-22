// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjpm.implement

import std.collection.*
import std.fs.*
import std.sort.*
import stdx.serialization.serialization.*
import stdx.encoding.json.*
import cjpm.config.*

public let REPOSITORY_PROVENANCE_FILE_NAME = "cjpm-provenance.json"

public class RepositoryProvenanceEntry <: Serializable<RepositoryProvenanceEntry> {
    public RepositoryProvenanceEntry(
        public let packageName!: String = "",
        public let version!: String = "",
        public let repository!: String = "",
        public let registry!: String = "",
        public let sha256!: String = ""
    ) {}

    public func serialize(): DataModel {
        return DataModelStruct()
            .add(field<String>("package", this.packageName))
            .add(field<String>("version", this.version))
            .add(field<String>("repository", this.repository))
            .add(field<String>("registry", this.registry))
            .add(field<String>("sha256", this.sha256))
    }

    public static func deserialize(dm: DataModel): RepositoryProvenanceEntry {
        let dms = match (dm) {
            case data: DataModelStruct => data
            case _ => throw Exception("invalid repository provenance entry")
        }
        return RepositoryProvenanceEntry(
            packageName: String.deserialize(dms.get("package")),
            version: String.deserialize(dms.get("version")),
            repository: String.deserialize(dms.get("repository")),
            registry: String.deserialize(dms.get("registry")),
            sha256: String.deserialize(dms.get("sha256"))
        )
    }
}

public class RepositoryProvenance <: Serializable<RepositoryProvenance> {
    public RepositoryProvenance(
        public let formatVersion!: Int64 = 1,
        public let packages!: ArrayList<RepositoryProvenanceEntry> = ArrayList<RepositoryProvenanceEntry>()
    ) {}

    public func serialize(): DataModel {
        return DataModelStruct()
            .add(field<Int64>("formatVersion", this.formatVersion))
            .add(field<ArrayList<RepositoryProvenanceEntry>>("packages", this.packages))
    }

    public static func deserialize(dm: DataModel): RepositoryProvenance {
        let dms = match (dm) {
            case data: DataModelStruct => data
            case _ => throw Exception("invalid repository provenance document")
        }
        return RepositoryProvenance(
            formatVersion: Int64.deserialize(dms.get("formatVersion")),
            packages: ArrayList<RepositoryProvenanceEntry>.deserialize(dms.get("packages"))
        )
    }
}

public func writeRepositoryProvenance(rootPath: String,
    fixedVersions: HashMap<String, String>,
    indexMap: HashMap<String, HashMap<String, ArtifactIndex>>,
    sourceDepotMap: HashMap<String, HashMap<String, Depot>>): Bool {
    let names = fixedVersions.keys().toArray()
    sort(names)
    let document = RepositoryProvenance()

    for (fullName in names) {
        let version = fixedVersions[fullName]
        if (!indexMap.contains(fullName) || !indexMap[fullName].contains(version) ||
            !sourceDepotMap.contains(fullName) || !sourceDepotMap[fullName].contains(version)) {
            eprintln("Warning: repository provenance is incomplete for '${fullName}-${version}'")
            return false
        }
        let depot = sourceDepotMap[fullName][version]
        document.packages.add(RepositoryProvenanceEntry(
            packageName: fullName,
            version: version,
            repository: depot.registryName,
            registry: depot.baseUrl,
            sha256: indexMap[fullName][version].sha256sum
        ))
    }

    let finalPath = Path(rootPath).join(REPOSITORY_PROVENANCE_FILE_NAME).toString()
    let temporaryPath = finalPath + ".tmp"
    try {
        File.writeTo(temporaryPath, document.serialize().toJson().toJsonString().toArray())
        rename(temporaryPath, to: finalPath, overwrite: true)
        return true
    } catch (e: Exception) {
        eprintln("Warning: failed to write repository provenance '${finalPath}': ${e.message}")
        if (fileExists(temporaryPath)) {
            deleteFile(temporaryPath)
        }
        return false
    }
}

public func loadRepositoryProvenance(rootPath: String): Option<RepositoryProvenance> {
    let path = Path(rootPath).join(REPOSITORY_PROVENANCE_FILE_NAME).toString()
    if (!fileExists(path)) {
        return None
    }
    try {
        let content = String.fromUtf8(File.readFrom(path))
        return Some(RepositoryProvenance.deserialize(DataModel.fromJson(JsonValue.fromStr(content))))
    } catch (e: Exception) {
        eprintln("Error: failed to read repository provenance '${path}': ${e.message}")
        return None
    }
}
