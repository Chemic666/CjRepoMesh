# CjRepo Server

仓颉原生的 CjRepoMesh 私有中心仓服务端。当前已提供健康检查，以及默认仓和命名 organization 的 Hosted Registry 发布、索引和制品下载。发布过程兼容 cjpm framing，并校验令牌、包身份、SHA-256 和重复版本。

## 本地运行

先加载仓颉环境并设置 `CANGJIE_STDX_PATH`，然后执行：

```powershell
cjpm run
```

默认监听 `127.0.0.1:8080`，可通过 `CJREPO_ADDRESS` 和 `CJREPO_PORT` 修改地址与端口。容器部署使用 `CJREPO_ADDRESS=0.0.0.0`，直接运行时仍默认只接受本机连接。存储目录默认为当前目录下的 `storage`，可通过 `CJREPO_STORAGE` 修改。设置 `CJREPO_PUBLISH_TOKEN` 后，发布请求必须携带相同的 `Authorization` 值。

可选设置 `CJREPO_READ_TOKEN` 启用私有读取：`/index/...` 和 `/pkg/<包名>/<版本>` 在 Hosted 与 Proxy 模式下均要求 `Authorization` 与令牌完全相同，且在检查磁盘缓存或访问上游之前拒绝无效请求；`/health` 仍公开用于健康检查。未设置时保持原来的公开读取行为。开启读取鉴权时必须同时设置 `CJREPO_PUBLISH_TOKEN`，否则服务拒绝启动，避免“读私有、写匿名”。增强版 cjpm 可用仓库配置中的 `token-env` 发送该令牌；CjRepo-to-CjRepo Sync 从私有源仓读取时可用 `CJREPO_UPSTREAM_TOKEN`。当前使用与 cjpm 兼容的原始令牌头值，不自动添加 `Bearer` 前缀；公网部署仍需 TLS 和入口层防护。

Hosted 与 Proxy 端点接受 cjpm 使用的 `?organization=<组织名>`，并按组织隔离索引和制品；不带查询参数使用默认仓。组织名必须符合 3–64 字符的仓颉标识符格式，其他查询参数、空值、编码别名和显式 `organization=default` 均返回 400，避免误读为默认仓。私有读取仍先鉴权（无令牌为 401）。Mirror 和 Sync 当前只处理默认仓。

健康检查：

```text
GET /health
```

## Hosted Registry 布局

```text
storage/
├── index/<default 或组织名>/<前两字符>/<随后字符>/<包名>
└── artifacts/<default 或组织名>/<包名>/<版本>/<包名>-<版本>.cjp
```

当前兼容的 cjpm 请求：

```text
POST /pkg/<包名>
GET /index/<前两字符>/<随后字符>/<包名>
GET /pkg/<包名>/<版本>
```

命名组织仓使用相同路径并追加 `?organization=<组织名>`；发布元数据和索引中的 `organization` 必须与查询参数一致。默认仓的元数据组织名为空字符串。

服务端会拒绝包含危险路径片段的请求；不存在的索引或制品返回 404。发布制品和索引均采用临时文件原子替换，并在进程级存储锁内复查重复版本；相同版本并发发布只允许一个成功。

## Proxy Repository

设置上游地址后，同一组 cjpm 查询和下载 API 自动变为按需代理：

```powershell
$env:CJREPO_UPSTREAM = "https://upstream.example.com"
$env:CJREPO_UPSTREAM_TOKEN = "optional-upstream-token"
$env:CJREPO_PROXY_TTL_SECONDS = "86400"
```

Cache MISS 会从上游获取并原子落盘；制品必须与已缓存索引中的 SHA-256 一致才会写入。并发首次请求在存储锁内复查缓存，因此只由一个请求访问上游，其余请求等待后直接命中。索引默认 86400 秒过期，可通过 `CJREPO_PROXY_TTL_SECONDS` 调整；制品按版本与校验和视为不可变内容，不随索引 TTL 重复下载。Cache HIT 不访问上游，因此缓存完整时支持离线构建。上游非 200 状态会原样透传，网络异常或完整性错误返回 502。

命名组织查询会原样携带到上游，并存入独立组织缓存；上游索引的 `organization` 必须与请求一致，否则拒绝缓存。组织制品始终与对应组织的索引校验和核对。

## Mirror

主动拉取指定包和版本；命名组织仓可将包参数写成 `<组织名>::<包名>`：

```powershell
$env:CJREPO_STORAGE = "./storage"
main.exe mirror https://upstream.example.com meshdep 2.0.0
```

Mirror 会下载索引和制品、验证 SHA-256 后写入本地仓。若本地已有相同且校验正确的版本，则返回 `SKIP`，不访问上游。

批量镜像使用清单：

```text
# mirror.txt：每行一个 package/version，空行和注释会被忽略
meshdep 1.0.0
meshdep 2.0.0
meshcorp::orgmeshdep 1.0.0
```

```powershell
main.exe mirror-manifest https://upstream.example.com mirror.txt
```

命令会继续处理清单中的后续条目，并在结尾输出 `total`、`succeeded`、`failed` 汇总；任一条目失败或清单为空时返回非零状态。重复执行已经完整缓存的清单只输出 `SKIP`，不访问上游。

## Repository Sync

将一个 CjRepo 中的指定版本增量同步到另一个 CjRepo；命名组织仓同样使用 `<组织名>::<包名>`：

```powershell
$env:CJREPO_SYNC_DESTINATION_TOKEN = "destination-publish-token"
main.exe sync http://source:8080 http://destination:8080 meshdep 2.0.0
```

同步会从 Source 获取索引与制品、验证 SHA-256，再通过目标仓发布协议写入。目标版本已经存在时，409 被解释为幂等 `SKIP`。

批量同步复用 Mirror 的 `package version` 清单格式，包括可选的组织名前缀：

```powershell
$env:CJREPO_SYNC_DESTINATION_TOKEN = "destination-publish-token"
main.exe sync-manifest http://source:8080 http://destination:8080 mirror.txt
```

批量命令会继续执行后续条目并输出成功/失败汇总；任一条目失败或清单为空时返回非零状态。

当前限制：读取鉴权需显式配置，默认仍为公开读取；当前使用进程级全局存储锁，尚未细化为按包锁；Mirror/Sync 已支持默认仓和命名组织仓的显式批量清单，但尚无调度和断点续传。Docker Compose 部署入口见 [部署说明](../deployment/docker/README.md)。
