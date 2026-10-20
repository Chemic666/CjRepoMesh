// Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
// This source file is part of the Cangjie project, licensed under Apache-2.0
// with Runtime Library Exception.
//
// See https://cangjie-lang.cn/pages/LICENSE for license information.

package cjpm.config

import std.env.*
import std.fs.*
import std.collection.*
import std.convert.*
import std.sort.*
import stdx.serialization.serialization.*
import cjpm.toml.*
import cjpm.toml.Decoder as DecoderToml

public let REPO_CONFIG_FILE_NAME = "cangjie-repo.toml"
public let REPO_CACHE_NAME = "cache"
public let REPO_HOME_NAME = "home"
public let GLOBAL_STRICT_TLS = "strict-tls"
public let REPO_TOKEN_ENV = "token-env"
public let REPO_PRIORITY = "priority"
public let REPO_ENABLED = "enabled"
public let REPO_ROUTE = "route"

// Defaults apply only to absent fields. Mistyped routing/security settings must
// fail before the router can access a registry, rather than weaken its policy.
private func repositoryStringField(data: DataModelStruct, name: String, fallback: String): String {
    match (data.get(name)) {
        case _: DataModelNull => fallback
        case value: DataModelString => String.deserialize(value)
        case _ => throw Exception("repository configuration field '${name}' must be a string")
    }
}

private func repositoryBoolField(data: DataModelStruct, name: String, fallback: Bool): Bool {
    match (data.get(name)) {
        case _: DataModelNull => fallback
        case value: DataModelBool => Bool.deserialize(value)
        case _ => throw Exception("repository configuration field '${name}' must be a boolean")
    }
}

private func repositoryIntField(data: DataModelStruct, name: String, fallback: Int64): Int64 {
    match (data.get(name)) {
        case _: DataModelNull => fallback
        case value: DataModelInt => Int64.deserialize(value)
        case _ => throw Exception("repository configuration field '${name}' must be an integer")
    }
}

private func repositoryTableField(data: DataModelStruct, name: String): DataModelStruct {
    match (data.get(name)) {
        case _: DataModelNull => DataModelStruct()
        case value: DataModelStruct => value
        case _ => throw Exception("repository configuration field '${name}' must be a table")
    }
}

private func repositoryArrayField(data: DataModelStruct, name: String): DataModelSeq {
    match (data.get(name)) {
        case _: DataModelNull => DataModelSeq()
        case value: DataModelSeq => value
        case _ => throw Exception("repository configuration field '${name}' must be an array")
    }
}

private func requireRepositoryTomlString(table: TomlObject, name: String): Unit {
    if (let Some(value) <- table.get(name)) {
        if (!(value is TomlString)) {
            throw Exception("repository configuration field '${name}' must be a string")
        }
    }
}

// The shared converter represents TOML dates/times as strings for other cjpm
// configuration. Inspect repository string fields before that type information
// is lost; do not change conversion semantics for unrelated configuration.
private func validateRepositoryTomlStrings(root: TomlValue): Unit {
    let config = root.asObject()
    if (let Some(value) <- config.get("repository")) {
        if (let Some(repositories) <- (value as TomlObject)) {
            for ((_, entry) in repositories.value) {
                if (let Some(repository) <- (entry as TomlObject)) {
                    for (name in ["path", "registry", "token", REPO_TOKEN_ENV]) {
                        requireRepositoryTomlString(repository, name)
                    }
                }
            }
        }
    }
    if (let Some(value) <- config.get(REPO_ROUTE)) {
        if (let Some(routes) <- (value as TomlArray)) {
            for (entry in routes.value) {
                if (let Some(route) <- (entry as TomlObject)) {
                    requireRepositoryTomlString(route, "namespace")
                    requireRepositoryTomlString(route, "registry")
                }
            }
        }
    }
}

public class RepositoryRoute <: Serializable<RepositoryRoute> {
    public RepositoryRoute(
        public var namespace!: String = "",
        public var registry!: String = "",
        public var exclusive!: Bool = false
    ) {}

    public func serialize(): DataModel {
        return DataModelStruct()
    }

    public static func deserialize(dm: DataModel): RepositoryRoute {
        let dms = match (dm) {
            case data: DataModelStruct => data
            case _ => throw Exception("repository route is not a table")
        }
        return RepositoryRoute(
            namespace: repositoryStringField(dms, "namespace", ""),
            registry: repositoryStringField(dms, "registry", ""),
            exclusive: repositoryBoolField(dms, "exclusive", false)
        )
    }

    public func matches(fullName: String): Bool {
        if (this.namespace.endsWith("::*")) {
            return fullName.startsWith(this.namespace.removeSuffix("*"))
        }
        return fullName == this.namespace
    }
}

public class RepositoryInfo <: Serializable<RepositoryInfo> {
    public RepositoryInfo(
        public var path!: String = "",
        public var registry!: String = "",
        public var token!: String = "",
        public var tokenEnv!: String = "",
        public var priority!: Int64 = 0,
        public var enabled!: Bool = true
    ) {}

    public func serialize(): DataModel {
        return DataModelStruct()
    }

    public static func deserialize(dm: DataModel): RepositoryInfo {
        var dms = match (dm) {
            case data: DataModelStruct => data
            case _ => throw Exception("this data is not DataModelStruct")
        }
        var result = RepositoryInfo()
        result.path = repositoryStringField(dms, "path", "")
        result.registry = repositoryStringField(dms, "registry", "")
        result.token = repositoryStringField(dms, "token", "")
        result.tokenEnv = repositoryStringField(dms, REPO_TOKEN_ENV, "")
        result.priority = repositoryIntField(dms, REPO_PRIORITY, 0)
        result.enabled = repositoryBoolField(dms, REPO_ENABLED, true)
        return result
    }
}

public class GlobalRepoConfig <: Serializable<GlobalRepoConfig> {
    public var strictTls: Bool = true

    public func serialize(): DataModel {
        return DataModelStruct()
    }

    public static func deserialize(dm: DataModel): GlobalRepoConfig {
        var dms = match (dm) {
            case data: DataModelStruct => data
            case _ => throw Exception("Wrong format of GlobalRepoConfig")
        }
        var result = GlobalRepoConfig()
        result.strictTls = repositoryBoolField(dms, GLOBAL_STRICT_TLS, true)
        return result
    }
}

public class SettingsConfig <: Serializable<SettingsConfig> {
    public var repository: HashMap<String, RepositoryInfo> = HashMap<String, RepositoryInfo>()
    public var routes: ArrayList<RepositoryRoute> = ArrayList<RepositoryRoute>()
    public var global: GlobalRepoConfig = GlobalRepoConfig()
    public var isValid: Bool = true

    public init() {
        this.repository.add(REPO_CACHE_NAME, RepositoryInfo())
        this.repository[REPO_CACHE_NAME].path = Path(DEFAULT_CONFIG_LOCATION).join(".cjpm").toString()
        this.repository.add(REPO_HOME_NAME, RepositoryInfo())
    }

    // Return enabled registries in deterministic priority order.
    // The cache entry is configuration for local storage, not a remote registry.
    public func getRegistryNames(): Array<String> {
        let names = ArrayList<String>()
        for ((name, info) in this.repository) {
            if (name == REPO_CACHE_NAME || !info.enabled || info.registry.isEmpty()) {
                continue
            }
            names.add(name)
        }

        let result = names.toArray()
        sort(result, by: { left: String, right: String =>
            let leftPriority = this.repository[left].priority
            let rightPriority = this.repository[right].priority
            if (leftPriority > rightPriority) {
                return Ordering.LT
            }
            if (leftPriority < rightPriority) {
                return Ordering.GT
            }
            return left.compare(right)
        }, stable: true)
        return result
    }

    public func serialize(): DataModel {
        return DataModelStruct()
    }

    public static func deserialize(dm: DataModel): SettingsConfig {
        let dms = match (dm) {
            case data: DataModelStruct => data
            case _ => throw Exception("this data is not DataModelStruct")
        }
        var result = SettingsConfig()
        result.global = GlobalRepoConfig.deserialize(repositoryTableField(dms, "global"))
        result.repository = HashMap<String, RepositoryInfo>.deserialize(repositoryTableField(dms, "repository"))
        result.routes = ArrayList<RepositoryRoute>.deserialize(repositoryArrayField(dms, REPO_ROUTE))

        if (!result.repository.contains(REPO_CACHE_NAME)) {
            result.repository.add(REPO_CACHE_NAME, RepositoryInfo())
            result.repository[REPO_CACHE_NAME].path = Path(DEFAULT_CONFIG_LOCATION).join(".cjpm").toString()
        }

        if (!result.repository.contains(REPO_HOME_NAME)) {
            result.repository.add(REPO_HOME_NAME, RepositoryInfo())
        }

        return result
    }
}

public func readConfigToml(file: Path): SettingsConfig {
    var res = SettingsConfig()
    try {
        let de = DecoderToml(File.readFrom(file))
        let to = de.decode()
        validateRepositoryTomlStrings(to)
        res = SettingsConfig.deserialize(DataModel.fromToml(to))
    } catch (e: Exception) {
        eprintln(e.message)
        eprintln("Error: load file '${file}' failed.")
        res.isValid = false
        return res
    }

    if (res.repository.contains(REPO_CACHE_NAME) && !res.repository[REPO_CACHE_NAME].path.isEmpty()) {
        // Replace env vars and convert the path to an absolute path when path is relative path
        res.repository[REPO_CACHE_NAME].path = getPath(file.parent.toString(), replaceEnvVars(res.repository[REPO_CACHE_NAME].path))

    }

    if (res.repository.contains(REPO_CACHE_NAME) && res.repository[REPO_CACHE_NAME].path.isEmpty()) {
        // when path of [repository.cache] is empty, set $HOME/.cjpm or %USERPROFILE%/.cjpm as repository cache path
        res.repository[REPO_CACHE_NAME].path = Path(DEFAULT_CONFIG_LOCATION).join(".cjpm").toString()
    }

    return res
}

public func loadConfigInfo(): SettingsConfig {
    // Read the configuration file based on priority.
    if (fileExists(Path(DIR_CURRENT).join(REPO_CONFIG_FILE_NAME))) {
        return readConfigToml(Path(DIR_CURRENT).join(REPO_CONFIG_FILE_NAME))
    }

    if (fileExists(Path(DEFAULT_CONFIG_LOCATION).join(".cjpm").join(REPO_CONFIG_FILE_NAME))) {
        return readConfigToml(Path(DEFAULT_CONFIG_LOCATION).join(".cjpm").join(REPO_CONFIG_FILE_NAME))
    }

    var res = SettingsConfig()
    let cj_home: String = getVariable("CANGJIE_HOME") ?? return res
    if (fileExists(Path(cj_home).join("tools").join("config").join(REPO_CONFIG_FILE_NAME))) {
        res = readConfigToml(Path(cj_home).join("tools").join("config").join(REPO_CONFIG_FILE_NAME))
        let globalCjpmConfig = getVariable("CJPM_CONFIG") ?? return res
        println("Warning: the functionality of 'CJPM_CONFIG' will be deprecated, " +
            "please unset 'CJPM_CONFIG' and use cangjie-repo.toml to set the repository cache path")
        res.repository[REPO_CACHE_NAME].path = globalCjpmConfig
        return res
    }

    let globalCjpmConfig = getVariable("CJPM_CONFIG") ?? return res
    println("Warning: the functionality of 'CJPM_CONFIG' will be deprecated, " +
            "please unset 'CJPM_CONFIG' and use cangjie-repo.toml to set the repository cache path")
    res.repository[REPO_CACHE_NAME].path = globalCjpmConfig

    return res
}

public func verifyDependencyField(dep: DepInfo, name: String, path: String): Bool {
    let isPathDep = dep.path.isSome()
    let isGitDep = dep.git.isSome()
    let isRepoDep = dep.version.isSome()

    if (!isPathDep && !isGitDep && !isRepoDep) {
        eprintln("Error: one of 'git' or 'path' or 'version' fields must exist " +
            "in dependency ${name} in ${Path(path).join(CONFIG_FILE_NAME).toString()}")
        return false
    }
    if ((isPathDep && isGitDep) || (isPathDep && isRepoDep) || (isGitDep && isRepoDep)) {
        eprintln("Error: only one of 'git' or 'path' or 'version' fields can exist " +
            "in dependency ${name} in ${Path(path).join(CONFIG_FILE_NAME).toString()}")
        return false
    }

    if (let Some(version) <- dep.version) {
        return centralVersionCheck(name, version, Path(path).join(CONFIG_FILE_NAME).toString())
    }

    return true
}
