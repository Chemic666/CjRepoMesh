// Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
// This source file is part of the Cangjie project, licensed under Apache-2.0
// with Runtime Library Exception.
//
// See https://cangjie-lang.cn/pages/LICENSE for license information.

package cjpm.implement

import std.fs.*
import cjpm.config.*
import stdx.crypto.common.CryptoException
import stdx.net.tls.common.TlsException

func processRepoDependencyModule(name: String, version: String, modulePath: String): (Bool, String) {
    if (version.isEmpty()) {
        eprintln("Error: the version can't be empty which is listed in 'dependencies' field " +
            "at ${Path(modulePath).join(CONFIG_FILE_NAME).toString()}")
        return (false, "")
    }
    let (result, output) = loadModuleFromRepo(name, version)
    if (!result) {
        if (!output.isEmpty()) {
            eprintln("Error: ${output}")
        }
        return (false, "")
    }
    return (true, output)
}

public func setRepoRoot(installConfig: InstallConfig, artifact: String): Bool {
    if (installConfig.verbose) {
        println("cjpm install: installing ${artifact} from central repository")
    }
    let params = artifact.split("-")
    let nameArr = params[0].split("::")
    let (org, name) = if (nameArr.size == 1) {
        ("", nameArr[0])
    } else {
        (nameArr[0], nameArr[1])
    }
    try {
        if (let Some(depot) <- Depot.new()) {
            installConfig.globalConfig.rootPath = Path(depot.localRepo)
                .join("source")
                .join(if (org.isEmpty()) { "default" } else { org })
                .join("${name}-${params[1]}")
                .toString()
            if (repositoryCacheEntryExists(Path(installConfig.globalConfig.rootPath))) {
                if (!depot.verifyCachedSource(name, org, params[1])) {
                    eprintln("Error: ${repositoryCacheIntegrityError()}")
                    return false
                }
                if (installConfig.verbose) {
                    println("cjpm install skip downloading ${artifact}: local files exist")
                }
            } else if (!downloadArtifact(depot, name, org, params[1], installConfig)) {
                return false
            }
            return prepareRepositoryInstallCopy(installConfig, depot.localRepo)
        } else {
            return false
        }
    } catch (e: CryptoException | TlsException) {
        eprintln("Error: ${e.message}")
        eprintln("Error: please ensure that openssl has been correctly installed and configured according to the \"Usage Instruction\" section of the documentation")
        return false
    } catch (e: Exception) {
        eprintln("Error: ${e.message}")
        if (e.message.contains("HttpEngine1#connect")) {
            eprintln("Error: unable to connect to https server.") 
        } else {
            eprintln("Error: load module failed with network connection error") 
        }
        return false
    }
}

// Repository source remains immutable: install writes target, lockfiles and
// provenance only in this newly owned work directory, never into the receipt's
// source tree. Directory.createTemp avoids deleting/reusing unknown old work.
private func prepareRepositoryInstallCopy(installConfig: InstallConfig, localRepo: String): Bool {
    let parent = Path(localRepo).join("install-work")
    if (repositoryCacheEntryExists(parent)) {
        let info = FileInfo(parent)
        if (info.isSymbolicLink() || !info.isDirectory()) {
            eprintln("Error: ${repositoryCacheIntegrityError()}")
            return false
        }
    }
    if (!createDirectory(parent.toString())) { return false }
    let work = Directory.createTemp(parent)
    try {
        let source = Path(installConfig.globalConfig.rootPath)
        let destination = work.join("package")
        copy(source, to: destination)
        installConfig.globalConfig.rootPath = destination.toString()
        installConfig.globalConfig.targetDir = destination.join(TARGET).toString()
        return true
    } catch (_: Exception) {
        deleteDirectory(work.toString())
        eprintln("Error: cannot prepare isolated repository installation")
        return false
    }
}

func downloadArtifact(depot: Depot, name: String, org: String, version: String, installConfig: InstallConfig): Bool {
    if (!depot.updateIndex(name, org)) {
        return false
    }
    let (result, output) = depot.download(name, org, version)
    if (!result) {
        eprintln("Error: ${output}")
        return false
    }
    if (installConfig.verbose) {
        println(output)
    }
    return true
}

func loadModuleFromRepo(name: String, version: String): (Bool, String) {
    if (let Some(depot) <- Depot.new()) {
        return loadModuleFromRepo(name, version, depot)
    }
    return (false, "wrong central repository configuration")
}

func loadModuleFromRepo(fullName: String, version: String, depot: Depot): (Bool, String) {
    let nameArr = fullName.split("::")
    let (org, name) = if (nameArr.size == 1) {
        ("", nameArr[0])
    } else {
        (nameArr[0], nameArr[1])
    }
    try {
        let dependencyPath = Path(depot.localRepo).join("source").
            join(if (org.isEmpty()) { "default" } else { org }).
            join("${name}-${version}").toString()
        if (repositoryCacheEntryExists(Path(dependencyPath))) {
            if (!depot.verifyCachedSource(name, org, version)) {
                return (false, repositoryCacheIntegrityError())
            }
            return (true, dependencyPath)
        }

        let (result, output) = depot.download(name, org, version)
        if (!result) {
            return (false, output)
        }
        return (true, dependencyPath)
    } catch (e: CryptoException | TlsException) {
        eprintln("Error: ${e.message}")
        eprintln("Error: please ensure that openssl has been correctly installed and configured according to the \"Usage Instruction\" section of the documentation")
        return (false, "catch exception while downloading ${name}-${version} from central repository")
    } catch (e: Exception) {
        eprintln("Error: ${e.message}")
        if (e.message.contains("HttpEngine1#connect")) {
            eprintln("Error: unable to connect to https server.")
        }
        return (false, "catch exception while downloading ${name}-${version} from central repository")
    }
}
