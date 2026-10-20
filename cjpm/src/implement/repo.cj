// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjpm.implement

import std.collection.*
import std.fs.*
import std.sort.*
import cjpm.config.*

private func directRequirement(tomlInfo: TomlInfo, fullName: String): (String, Bool) {
    if (let Some(dep) <- tomlInfo.dependencies.get(fullName)) {
        if (let Some(version) <- dep.version) {
            return (version, true)
        }
    }
    if (let Some(dep) <- tomlInfo.testDependencies.get(fullName)) {
        if (let Some(version) <- dep.version) {
            return (version, true)
        }
    }
    if (let Some(dep) <- tomlInfo.scriptDependencies.get(fullName)) {
        if (let Some(version) <- dep.version) {
            return (version, true)
        }
    }
    return ("(,)", false)
}

private func inferredDoctorPackage(): Option<String> {
    if (!fileExists(Path(DIR_CURRENT).join(CONFIG_FILE_NAME))) {
        return None
    }
    let tomlInfo = loadModuleFile(DIR_CURRENT) ?? return None
    let names = ArrayList<String>()
    for ((name, dep) in tomlInfo.dependencies) {
        if (dep.version.isSome()) {
            names.add(name)
        }
    }
    let ordered = names.toArray()
    sort(ordered)
    return if (ordered.isEmpty()) { None } else { Some(ordered[0]) }
}

public func doRepoDoctor(packageArgument: Option<String>): Bool {
    let fullName = match (packageArgument) {
        case Some(name) => name
        case None =>
            match (inferredDoctorPackage()) {
                case Some(name) => name
                case None =>
                    eprintln("Error: no direct repository dependency is available; use 'cjpm repo doctor <package>'")
                    return false
            }
    }
    if (!dependenciesNameCheck(fullName, "argument to 'cjpm repo doctor'")) {
        return false
    }

    println("Repository Diagnostics")
    println("Package: ${fullName}")
    let router = RepositoryRouter.new() ?? return false
    let candidates = router.getDepots(fullName)
    var allPassed = true
    for (depot in candidates) {
        let priority = FINAL_CJPM_CONFIG_INFO.repository[depot.registryName].priority
        println("")
        println("${depot.registryName}")
        println("  Configuration  PASS  priority=${priority}")
        let (org, name) = splitFullName(fullName)
        let (passed, output) = try {
            depot.updateIndexWithOutput(name, org)
        } catch (e: Exception) {
            (false, e.message)
        }
        if (passed) {
            println("  Metadata API   PASS  status=${depot.lastResponseStatus}")
        } else {
            allPassed = false
            println("  Metadata API   FAIL  status=${depot.lastResponseStatus}")
            println("  Detail         ${output}")
            println("  Fallback       ${if (RepositoryRouter.canContinueAfter(depot.lastResponseStatus)) { "ALLOWED" } else { "BLOCKED" }}")
        }
    }
    println("")
    println("Overall: ${if (allPassed) { "PASS" } else { "FAIL" }}")
    return allPassed
}

public func doRepoExplainRecorded(fullName: String): Bool {
    if (!dependenciesNameCheck(fullName, "argument to 'cjpm repo explain'")) {
        return false
    }
    let provenance = match (loadRepositoryProvenance(DIR_CURRENT)) {
        case Some(value) => value
        case None =>
            eprintln("Error: '${REPOSITORY_PROVENANCE_FILE_NAME}' does not exist or is invalid; run cjpm build first")
            return false
    }
    for (entry in provenance.packages) {
        if (entry.packageName == fullName) {
            if (!safeRegistryAddress(entry.registry)) {
                eprintln("Error: recorded registry URL is unsafe; regenerate provenance using a " +
                    "credential-free HTTP(S) registry address and token-env")
                return false
            }
            println("Recorded resolution:")
            println("  package: ${entry.packageName}")
            println("  version: ${entry.version}")
            println("  repository: ${entry.repository}")
            println("  registry: ${entry.registry}")
            println("  checksum: sha256:${entry.sha256}")
            println("  source: ${REPOSITORY_PROVENANCE_FILE_NAME}")
            return true
        }
    }
    eprintln("Error: package '${fullName}' is not recorded in '${REPOSITORY_PROVENANCE_FILE_NAME}'")
    return false
}

public func doRepoExplain(fullName: String): Bool {
    if (!dependenciesNameCheck(fullName, "argument to 'cjpm repo explain'")) {
        return false
    }

    var requested = "(,)"
    var isDeclared = false
    var effective = requested
    var overrideVersion = ""
    var nonRepositoryOverride = false

    if (fileExists(Path(DIR_CURRENT).join(CONFIG_FILE_NAME))) {
        let tomlInfo = loadModuleFile(DIR_CURRENT) ?? return false
        (requested, isDeclared) = directRequirement(tomlInfo, fullName)
        effective = requested
        if (let Some(replacement) <- tomlInfo.replaceDeps.get(fullName)) {
            if (let Some(version) <- replacement.version) {
                overrideVersion = version
                effective = version
            } else {
                nonRepositoryOverride = true
            }
        }
    }

    println("Package:")
    println("  ${fullName}")
    println("Requested:")
    println(if (isDeclared) { "  ${requested}" } else { "  any version (package is not a direct repository dependency)" })

    if (nonRepositoryOverride) {
        println("Override:")
        println("  applied: local or Git replacement; repository resolution is not used")
        return true
    }

    println("Override:")
    println(if (overrideVersion.isEmpty()) { "  none" } else { "  applied: ${requested} -> ${overrideVersion}" })

    var matchedRoute = false
    for (route in FINAL_CJPM_CONFIG_INFO.routes) {
        if (route.matches(fullName)) {
            println("Matched namespace rule:")
            println("  ${route.namespace} -> ${route.registry} (exclusive=${route.exclusive})")
            matchedRoute = true
            break
        }
    }
    if (!matchedRoute) {
        println("Matched namespace rule:")
        println("  none")
    }

    let router = RepositoryRouter.new() ?? return false
    let candidates = router.getDepots(fullName)
    println("Allowed repositories:")
    var position = 1
    for (depot in candidates) {
        let priority = FINAL_CJPM_CONFIG_INFO.repository[depot.registryName].priority
        println("  ${position}. ${depot.registryName} (priority=${priority}, registry=${depot.baseUrl})")
        position++
    }

    let indexMap = HashMap<String, HashMap<String, ArtifactIndex>>()
    let sourceDepotMap = HashMap<String, HashMap<String, Depot>>()
    let resolvedRecord = try {
        DepRecord(fullName, effective, OutputType.Unknown(""), router, indexMap, sourceDepotMap)
    } catch (e: Exception) {
        eprintln("Error: ${e.message}")
        return false
    }
    let selectedVersion = resolvedRecord.getNextAvailable(HashMap<String, String>())
    if (selectedVersion.isEmpty() || !sourceDepotMap.contains(fullName) ||
        !sourceDepotMap[fullName].contains(selectedVersion)) {
        eprintln("Error: no repository source was selected for '${fullName}'")
        return false
    }

    let selectedDepot = sourceDepotMap[fullName][selectedVersion]
    let checksum = indexMap[fullName][selectedVersion].sha256sum
    println("Resolution:")
    println("  effective requirement: ${effective}")
    println("  available versions: ${String.join(resolvedRecord.available.toArray(), delimiter: ", ")}")
    println("  selected version: ${selectedVersion}")
    println("  repository: ${selectedDepot.registryName}")
    println("  checksum: sha256:${checksum}")
    println("  reason: existing cjpm version selection, then repository priority for the exact version")
    return true
}
