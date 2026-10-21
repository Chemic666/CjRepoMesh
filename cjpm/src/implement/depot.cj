// Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
// This source file is part of the Cangjie project, licensed under Apache-2.0
// with Runtime Library Exception.
//
// See https://cangjie-lang.cn/pages/LICENSE for license information.

package cjpm.implement

import std.net.*
import std.io.*
import std.fs.*
import std.env.*
import std.collection.*
import std.regex.*
import stdx.net.http.*
import stdx.net.tls.common.*
import stdx.net.tls.*
import stdx.crypto.digest.*
import stdx.encoding.hex.*
import stdx.serialization.serialization.*
import stdx.encoding.json.*
import stdx.encoding.url.*
import cjpm.config.*
import stdx.crypto.common.CryptoException
import stdx.crypto.x509.X509Certificate

const CONNECT_TIMEOUT = 30
const READ_TIMEOUT = 60

let tcpSocketConnector = {
    sa: SocketAddress =>
        let socket = TcpSocket(sa)
        socket.connect(timeout: Duration.second * CONNECT_TIMEOUT)
        return socket
}

private func registryTlsConfiguration(address: String, strict: Bool): TlsClientConfig {
    var config = TlsClientConfig()
    if (!strict) {
        config.verifyMode = TrustAll
    } else {
        let url = URL.parse(address)
        if (url.scheme == "https" && IPAddress.tryParse(url.hostName).isNone()) {
            config.serverName = Some(url.hostName)
        }
    }
    return config
}

private func registrySocketConnector(address: String, strict: Bool,
    config: TlsClientConfig): (SocketAddress) -> StreamingSocket {
    let url = URL.parse(address)
    let ip = IPAddress.tryParse(url.hostName)
    if (!strict || url.scheme != "https" || ip.isNone()) {
        return tcpSocketConnector
    }
    let expected = ip.getOrThrow().getAddressBytes()
    return { sa: SocketAddress =>
        let socket = tcpSocketConnector(sa)
        let tls = try {
            TlsSocket.client(socket, clientConfig: config)
        } catch (e: Exception) {
            socket.close()
            throw e
        }
        try {
            // Keep OpenSSL's default chain, time and server-purpose checks.
            // stdx 1.1.3's serverName uses DNS-only set1_host, so IP identity
            // is checked against the authenticated leaf's binary IP SANs.
            let result = tls.handshake(timeout: Some(Duration.second * CONNECT_TIMEOUT))
            if (result.peerCertificate.isEmpty()) {
                throw TlsException("TLS server certificate is missing")
            }
            let certificate = result.peerCertificate[0] as X509Certificate ??
                throw TlsException("TLS server certificate type is unsupported")
            var matches = false
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
            return tls
        } catch (e: Exception) {
            tls.close()
            throw e
        }
    }
}

// Registry bases are also persisted in provenance and printed by repo explain.
// Keep credentials in the Authorization header rather than in those addresses.
public func safeRegistryAddress(address: String): Bool {
    let lower = address.toAsciiLower()
    let prefixSize = if (lower.startsWith("https://")) { 8 } else if (lower.startsWith("http://")) { 7 } else {
        return false
    }
    if (address.size <= prefixSize || address.contains("?") || address.contains("#") ||
        address.contains("\\")) {
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

public class Depot {
    public var registryName: String = REPO_HOME_NAME
    public var baseUrl: String = ""
    public var token: String = ""
    public var localRepo: String = ""
    public var lastResponseStatus: UInt16 = 0
    public var global: GlobalRepoConfig = GlobalRepoConfig()

    public func loadConfiguration(repositoryName!: String = REPO_HOME_NAME, isError!: Bool = true): Bool {
        let alertLevel =  if (isError) { "Error" } else { "Warning" }
        if (!FINAL_CJPM_CONFIG_INFO.repository.contains(repositoryName)) {
            eprintln("${alertLevel}: get data of [repository.${repositoryName}] failed, please check if cangjie-repo.toml is set up correctly")
            return false
        }
        if (repositoryName == REPO_CACHE_NAME ||
            !Regex("^[a-zA-Z][-_a-zA-Z0-9.]*$").matches(repositoryName)) {
            eprintln("${alertLevel}: invalid repository name '${repositoryName}'")
            return false
        }

        let repositoryInfo = FINAL_CJPM_CONFIG_INFO.repository[repositoryName]
        if (!repositoryInfo.enabled) {
            eprintln("${alertLevel}: repository '${repositoryName}' is disabled")
            return false
        }
        if (!repositoryInfo.token.isEmpty() && !repositoryInfo.tokenEnv.isEmpty()) {
            eprintln("${alertLevel}: only one of 'token' or 'token-env' can be set in [repository.${repositoryName}]")
            return false
        }

        this.registryName = repositoryName
        this.baseUrl = repositoryInfo.registry
        if (!repositoryInfo.tokenEnv.isEmpty()) {
            if (let Some(token) <- getVariable(repositoryInfo.tokenEnv)) {
                this.token = token
            } else {
                eprintln("${alertLevel}: environment variable '${repositoryInfo.tokenEnv}' configured by " +
                    "[repository.${repositoryName}].token-env is not set")
                return false
            }
        } else {
            this.token = repositoryInfo.token
        }
        if (baseUrl.isEmpty()) {
            eprintln("${alertLevel}: get registry of [repository.${repositoryName}] failed, please check if cangjie-repo.toml is set up correctly")
            return false
        }
        if (!safeRegistryAddress(baseUrl)) {
            eprintln("${alertLevel}: registry URL must use HTTP(S) without embedded credentials, " +
                "query parameters, fragments or whitespace in [repository.${repositoryName}]; " +
                "use token-env for authentication")
            return false
        }

        let repositoryRoot = Path(FINAL_CJPM_CONFIG_INFO.repository[REPO_CACHE_NAME].path).join("repository")
        let registryNames = FINAL_CJPM_CONFIG_INFO.getRegistryNames()
        this.localRepo = if (registryNames.size == 1 && repositoryName == REPO_HOME_NAME) {
            // Preserve the exact cache layout for existing single-registry users.
            repositoryRoot.toString()
        } else {
            // A configuration name can be repointed to another registry. Bind
            // both index and extracted source caches to its validated address.
            let addressHash = SHA256()
            addressHash.write(this.baseUrl.toArray())
            repositoryRoot.join("registries").join(repositoryName).
                join(toHexString(addressHash.finish())).toString()
        }

        this.global = FINAL_CJPM_CONFIG_INFO.global

        return true
    }

    public static func new(repositoryName!: String = REPO_HOME_NAME): Option<Depot> {
        let instance: Depot = Depot()
        if (instance.loadConfiguration(repositoryName: repositoryName)) {
            return Option<Depot>.Some(instance)
        }
        return Option<Depot>.None
    }

    // publish data to central repository
    public func publish(tomlInfo: TomlInfo, data: Array<Byte>): (Bool, String) {
        let name = tomlInfo.pkg.name
        let version = tomlInfo.pkg.version
        let org = tomlInfo.pkg.organization

        // check name and organization
        var flag = if (org.isEmpty()) { true } else { checkBundleName(org, "organization") }
        flag = checkBundleName(name, "module") && flag
        if (!flag) {
            return (false, "")
        }

        var publishUrl = baseUrl + "/pkg/${name}"
        var orgStr = ""
        if (!org.isEmpty()) {
            publishUrl += "?organization=${org}"
            orgStr = "to organization '${org}' "
        }

        // building client
        let tlsConfig = registryTlsConfiguration(this.baseUrl, this.global.strictTls)
        let client = ClientBuilder().
            connector(registrySocketConnector(this.baseUrl, this.global.strictTls, tlsConfig)).
            autoRedirect(false).
            noProxy().
            readTimeout(Duration.second * READ_TIMEOUT).
            tlsConfig(tlsConfig).
            build()

        // building https request
        var body = ByteBuffer()
        body.write(data)
        let request = HttpRequestBuilder().
            method("POST").
            url(publishUrl).
            header("Authorization", token).
            body(body).
            build()
        let resp = client.send(request)
        client.close()

        // verify response code
        match (resp.status) {
            case 200 => return (true, "${name}-${version} ${orgStr}publish success")
            case 400 =>
                let respMsg = extractErrorMessage(resp)
                return (false, "${name}-${version} ${orgStr}publish failed with status ${resp.status}: invalid parameters: ${respMsg}")
            case 401 => return (false, "${name}-${version} ${orgStr}publish failed with status ${resp.status}: authentication failed")
            case 403 => return (false, "${name}-${version} ${orgStr}publish failed with status ${resp.status}: permission denied or the artifact name already in use")
            case 404 => return (false, "${name}-${version} ${orgStr}publish failed with status ${resp.status}: file does not exist")
            case 409 => return (false, "${name}-${version} ${orgStr}publish failed with status ${resp.status}: artifact with the same name and verison already exists")
            case 429 => return (false, "${name}-${version} ${orgStr}publish failed with status ${resp.status}: rate limit exceeded, retry after one day")
            case s where (s >= 500) => return (false, "${name}-${version} ${orgStr}publish failed with status ${resp.status}: server error")
            case _ => return (false, "${name}-${version} ${orgStr}publish failed, unknown error with status ${resp.status}")
        }
    }

    // download package from central repository
    public func download(name: String, org: String, version: String): (Bool, String) {
        var downloadUrl = baseUrl + "/pkg/${name}/${version}"
        var orgStr = ""
        if (!org.isEmpty()) {
            downloadUrl += "?organization=${org}"
            orgStr = "from organization '${org}' "
        }

        // building client
        let tlsConfig = registryTlsConfiguration(this.baseUrl, this.global.strictTls)
        let client = ClientBuilder().
            connector(registrySocketConnector(this.baseUrl, this.global.strictTls, tlsConfig)).
            autoRedirect(false).
            noProxy().
            readTimeout(Duration.second * READ_TIMEOUT).
            tlsConfig(tlsConfig).
            build()

        // building https request
        let requestBuilder = HttpRequestBuilder().method("GET").url(downloadUrl)
        if (!token.isEmpty()) {
            requestBuilder.header("Authorization", token)
        }
        let request = requestBuilder.build()
        let resp = client.send(request)

        // verify response code
        var (flag, errLog) = (true, "")
        match (resp.status) {
            case 200 => ()
            case 400 =>
                let respMsg = extractErrorMessage(resp)
                (flag, errLog) = (false, "${name}-${version} ${orgStr}load failed with status ${resp.status}: invalid parameters: ${respMsg}")
            case 401 => (flag, errLog) = (false, "${name}-${version} ${orgStr}load failed with status ${resp.status}: authentication failed")
            case 403 => (flag, errLog) = (false, "${name}-${version} ${orgStr}load failed with status ${resp.status}: permission denied")
            case 404 => (flag, errLog) = (false, "${name}-${version} ${orgStr}load failed with status ${resp.status}: file does not exist")
            case 429 => (flag, errLog) = (false, "${name}-${version} ${orgStr}load failed with status ${resp.status}: rate limit exceeded, retry after one day")
            case s where (s >= 500) => (flag, errLog) = (false, "${name}-${version} ${orgStr}load failed with status ${resp.status}: server error")
            case _ => (flag, errLog) = (false, "${name}-${version} ${orgStr}load failed, unknown error with status ${resp.status}")
        }
        if (!flag) {
            client.close()
            return (flag, errLog)
        }

        let buf = Array<UInt8>(1024, repeat: 0)
        let buffer = ArrayList<UInt8>()
        var i = 0
        do {
            i = resp.body.read(buf)
            buffer.add(all: buf[..i])
        } while (i != 0)
        client.close()

        // check sha256sum
        try {
            let sha256Instance = SHA256()
            sha256Instance.write(buffer.toArray())
            let sha256sum = toHexString(sha256Instance.finish())
            let indexPath = this.getIndex(name, org)
            if (indexPath.isEmpty()) {
                return (false, "index error while downloading ${name}-${version} ${orgStr}")
            }

            var indexRawData = String.fromUtf8(File.readFrom(indexPath))
            var indexIter = indexRawData.lines()

            var checkSumFlag = false
            while (true) {
                match (indexIter.next()) {
                    case Some(indexStr) =>
                        try {
                            let index: ArtifactIndex = ArtifactIndex.deserialize(DataModel.fromJson(JsonValue.fromStr(indexStr)))
                            if (index.version != version) {
                                continue
                            }
                            if (index.sha256sum != sha256sum) {
                                return (false, "package was broken while downloading ${name}-${version} ${orgStr}, please try 'cjpm update'")
                            }
                            checkSumFlag = true
                            break
                        } catch (e: Exception) {
                            return (false, "index was broken while downloading ${name}-${version} ${orgStr}, please try 'cjpm update'")
                        }
                    case None => break
                }
            }

            if (!checkSumFlag) {
                return (false, "cannot find index data while downloading ${name}-${version} ${orgStr}, please try 'cjpm update'")
            }
        } catch (e: CryptoException) {
            eprintln("Error: ${e.message}")
            eprintln("Error: please ensure that openssl has been correctly installed and configured according to the \"Usage Instruction\" section of the documentation")
            return (false, "failed to check sha256 check-sum due to missing OpenSSL")
        } catch (e: Exception) {
            return (false, "failed to check sha256 check-sum while downloading ${name}-${version} ${orgStr}, please try 'cjpm update'")
        }

        // save, uncompress and delete cjp file
        return uncompressCjp(org, name, version, buffer.toArray(), this.localRepo)
    }

    // update local index for one module with output
    public func updateIndexWithOutput(name: String, org: String): (Bool, String) {
        this.lastResponseStatus = 0
        let firstLevel = name[..2]
        let secondLevel = if (name.size > 3) { name[2..4] } else { name[2..3] }
        var indexUrl = baseUrl + "/index/${firstLevel}/${secondLevel}/${name}"
        var orgStr = ""
        if (!org.isEmpty()) {
            indexUrl += "?organization=${org}"
            orgStr = " from organization '${org}'"
        }

        // building client
        let tlsConfig = registryTlsConfiguration(this.baseUrl, this.global.strictTls)
        let client = ClientBuilder().
            connector(registrySocketConnector(this.baseUrl, this.global.strictTls, tlsConfig)).
            autoRedirect(false).
            noProxy().
            readTimeout(Duration.second * READ_TIMEOUT).
            tlsConfig(tlsConfig).
            build()

        // building https request
        let requestBuilder = HttpRequestBuilder().method("GET").url(indexUrl)
        if (!token.isEmpty()) {
            requestBuilder.header("Authorization", token)
        }
        let request = requestBuilder.build()
        let resp = client.send(request)
        this.lastResponseStatus = resp.status

        // verify response code
        var (flag, errLog) = (true, "")
        match (resp.status) {
            case 200 => ()
            case 400 =>
                let respMsg = extractErrorMessage(resp)
                (flag, errLog) = (false, "index of module '${name}'${orgStr} load failed with status ${resp.status}: invalid parameters: ${respMsg}")
            case 401 =>
                (flag, errLog) = (false, "index of module '${name}'${orgStr} load failed with status ${resp.status}: authentication failed")
            case 403 =>
                (flag, errLog) = (false, "index of module '${name}'${orgStr} load failed with status ${resp.status}: permission denied")
            case 404 =>
                (flag, errLog) = (false, "index of module '${name}'${orgStr} load failed with status ${resp.status}: file does not exist")
            case s where (s >= 500) =>
                (flag, errLog) = (false, "index of module '${name}'${orgStr} load failed with status ${resp.status}: server error")
            case _ =>
                (flag, errLog) = (false, "index of module '${name}'${orgStr} load failed, unknown error with status ${resp.status}")
        }
        if (!flag) {
            client.close()
            return (flag, errLog)
        }

        let buf = Array<UInt8>(1024, repeat: 0)
        let buffer = ArrayList<UInt8>()
        var i = 0
        do {
            i = resp.body.read(buf)
            buffer.add(all: buf[..i])
        } while (i != 0)
        client.close()

        // save index file
        let indexDir = Path(this.localRepo).join("index").
            join(if (org.isEmpty()) { "default" } else { org }).
            join(firstLevel).
            join(secondLevel).
            toString()
        let indexPath = Path(indexDir).join(name)
        if (!createDirectory(indexDir)) {
            return (false, "cannot save index file for module '${name}'${orgStr}")
        }
        File.writeTo(indexPath, buffer.toArray())

        return (true, "")
    }

    // update local index for one module
    public func updateIndex(name: String, org: String): Bool {
        let (flag, output) = this.updateIndexWithOutput(name, org)
        if (!flag) {
            eprintln("Error: ${output}")
        }
        return flag
    }

    private func redactToken(message: String): String {
        return if (this.token.isEmpty()) { message } else { message.replace(this.token, "[REDACTED]") }
    }

    private func extractErrorMessage(resp: HttpResponse): String {
        let buffer = ArrayList<UInt8>()
        while (true) {
            let buf = Array<UInt8>(1024, repeat: 0)
            let readSize = resp.body.read(buf)
            if (readSize == 0) {
                break
            }
            buffer.add(all: buf[..readSize])
        }
        let respMsg = String.fromUtf8(buffer.toArray())
        try {
            if (let Some(errorsVal) <- JsonValue.fromStr(respMsg).asObject().get("errors")) {
                let errArray = errorsVal.asArray()
                for (idx in 0..errArray.size()) {
                    if (let Some(msgVal) <- errArray[idx].asObject().get("message")) {
                        return redactToken(msgVal.asString().getValue())
                    }
                }
            }
        } catch (e: Exception) {
            eprintln("Warning: failed to parse response: ${redactToken(e.message)}")
        }
        return redactToken(respMsg)
    }

    // get index file
    public func getIndex(name: String, org: String): String {
        let firstLevel = name[..2]
        let secondLevel = if (name.size > 3) { name[2..4] } else { name[2..3] }
        let indexPath = Path(this.localRepo).join("index").
            join(if (org.isEmpty()) { "default" } else { org }).
            join(firstLevel).
            join(secondLevel).
            join(name).toString()
        if (fileExists(indexPath)) {
            return indexPath
        }
        return ""
    }
}

// Ordered repository set used by dependency resolution. Version selection remains
// in DepRecord/DepAnalysisEngine; this class only owns repository identity/order.
public class RepositoryRouter {
    public let depots: ArrayList<Depot> = ArrayList<Depot>()

    public static func new(): Option<RepositoryRouter> {
        let instance = RepositoryRouter()
        let repositoryNames = FINAL_CJPM_CONFIG_INFO.getRegistryNames()
        for (repositoryName in repositoryNames) {
            let depot = Depot.new(repositoryName: repositoryName) ?? return None
            instance.depots.add(depot)
        }
        if (instance.depots.isEmpty()) {
            // Preserve the historical single-home diagnostic used by existing
            // cjpm callers and the upstream LLT when only home/cache exist.
            let legacyHome = FINAL_CJPM_CONFIG_INFO.repository[REPO_HOME_NAME]
            if (FINAL_CJPM_CONFIG_INFO.repository.size == 2 && legacyHome.enabled &&
                legacyHome.registry.isEmpty() && FINAL_CJPM_CONFIG_INFO.routes.isEmpty()) {
                eprintln("Error: get registry of [repository.home] failed, please check if cangjie-repo.toml is set up correctly")
            } else {
                eprintln("Error: no enabled repository with a non-empty registry is configured")
            }
            return None
        }
        for (route in FINAL_CJPM_CONFIG_INFO.routes) {
            if (route.namespace.isEmpty() || route.registry.isEmpty()) {
                eprintln("Error: repository route requires non-empty 'namespace' and 'registry'")
                return None
            }
            if (!repositoryNames.contains(route.registry)) {
                eprintln("Error: repository route '${route.namespace}' references unavailable registry " +
                    "'${route.registry}'")
                return None
            }
        }
        return Some(instance)
    }

    public func primary(): Depot {
        return this.depots[0]
    }

    public func getDepots(fullName: String): ArrayList<Depot> {
        for (route in FINAL_CJPM_CONFIG_INFO.routes) {
            if (!route.matches(fullName)) {
                continue
            }
            let routed = ArrayList<Depot>()
            for (depot in this.depots) {
                if (depot.registryName == route.registry) {
                    routed.add(depot)
                    break
                }
            }
            if (!route.exclusive) {
                for (depot in this.depots) {
                    if (depot.registryName != route.registry) {
                        routed.add(depot)
                    }
                }
            }
            return routed
        }
        return this.depots
    }

    // Authentication, authorization and malformed requests must never be hidden
    // by another registry. Missing content and server outages may try the next one.
    public static func canContinueAfter(status: UInt16): Bool {
        return status == 404 || status >= 500
    }
}
