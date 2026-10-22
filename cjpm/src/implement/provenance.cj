// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjpm.implement

import std.collection.*
import std.env.*
import std.fs.*
import std.regex.*
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
        let formatVersion = Int64.deserialize(dms.get("formatVersion"))
        if (formatVersion != 1) {
            throw Exception("unsupported repository provenance format version; supported version is 1")
        }
        return RepositoryProvenance(
            formatVersion: formatVersion,
            packages: ArrayList<RepositoryProvenanceEntry>.deserialize(dms.get("packages"))
        )
    }
}

private func rejectRepositorySourceBaseline(reason: String): Bool {
    // Never echo the path, document, parser exception or untrusted field values.
    eprintln("Error: repository source baseline rejected: ${reason}")
    return false
}

// Opt-in admission of the selected repository graph. Metadata may already have
// been fetched; callers must invoke this before starting artifact downloads.
public func verifyRepositorySourceBaseline(rootPath: String,
    fixedVersions: HashMap<String, String>,
    indexMap: HashMap<String, HashMap<String, ArtifactIndex>>,
    sourceDepotMap: HashMap<String, HashMap<String, Depot>>): Bool {
    let setting = getVariable("CJREPOMESH_SOURCE_BASELINE") ?? return true
    if (setting.isEmpty()) {
        return rejectRepositorySourceBaseline("CJREPOMESH_SOURCE_BASELINE is empty")
    }
    try {
        let path = getPath(rootPath, setting)
        let outputPath = getPath(rootPath, REPOSITORY_PROVENANCE_FILE_NAME)
        let temporaryPath = getPath(rootPath, REPOSITORY_PROVENANCE_FILE_NAME + ".tmp")
        if (path == outputPath || path == temporaryPath) {
            return rejectRepositorySourceBaseline("use a separate independently approved file")
        }
        let bytes = ArrayList<UInt8>()
        try (file = File(path, Read)) {
            let buffer = Array<UInt8>(8192, repeat: 0)
            while (true) {
                let count = file.read(buffer)
                if (count == 0) { break }
                if (bytes.size + count > 1024 * 1024) {
                    return rejectRepositorySourceBaseline("document exceeds 1 MiB")
                }
                bytes.add(all: buffer[..count])
            }
        }
        let model = DataModel.fromJson(JsonValue.fromStr(String.fromUtf8(bytes.toArray())))
        let data = model as DataModelStruct ?? throw Exception("invalid baseline document")
        // Int64.deserialize also accepts other convertible models; a policy
        // version must be an actual JSON integer, never true or a numeric string.
        let format = data.get("formatVersion") as DataModelInt ?? throw Exception("invalid baseline version type")
        if (Int64.deserialize(format) != 1) {
            return rejectRepositorySourceBaseline("unsupported formatVersion; expected integer 1")
        }
        let packages = data.get("packages") as DataModelSeq ?? throw Exception("invalid baseline packages type")
        for (item in packages.getItems()) {
            let entry = item as DataModelStruct ?? throw Exception("invalid baseline package type")
            for (name in ["package", "version", "repository", "registry", "sha256"]) {
                if (!(entry.get(name) is DataModelString)) {
                    return rejectRepositorySourceBaseline("package fields must be strings")
                }
            }
        }
        let document = RepositoryProvenance.deserialize(model)
        let approved = HashMap<String, RepositoryProvenanceEntry>()
        for (entry in document.packages) {
            if (entry.packageName.isEmpty() || entry.version.isEmpty() || entry.repository.isEmpty() ||
                !safeRegistryAddress(entry.registry) || !Regex("^[0-9a-f]{64}$").matches(entry.sha256)) {
                return rejectRepositorySourceBaseline("invalid package fields, registry address or SHA-256")
            }
            if (approved.contains(entry.packageName)) {
                return rejectRepositorySourceBaseline("duplicate package")
            }
            approved.add(entry.packageName, entry)
        }
        if (approved.size != fixedVersions.size) {
            return rejectRepositorySourceBaseline("selected package set differs")
        }
        for ((name, version) in fixedVersions) {
            let entry = approved.get(name) ?? return rejectRepositorySourceBaseline("selected package set differs")
            if (entry.version != version) {
                return rejectRepositorySourceBaseline("selected version differs")
            }
            if (!indexMap.contains(name) || !indexMap[name].contains(version) ||
                !sourceDepotMap.contains(name) || !sourceDepotMap[name].contains(version)) {
                return rejectRepositorySourceBaseline("selected source metadata is incomplete")
            }
            let depot = sourceDepotMap[name][version]
            if (entry.repository != depot.registryName || entry.registry != depot.baseUrl) {
                return rejectRepositorySourceBaseline("selected repository or registry differs")
            }
            if (entry.sha256 != indexMap[name][version].sha256sum) {
                return rejectRepositorySourceBaseline("selected SHA-256 differs")
            }
        }
        return true
    } catch (_: Exception) {
        return rejectRepositorySourceBaseline("unreadable or invalid document")
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
