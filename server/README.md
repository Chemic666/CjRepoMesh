# CjRepo Server

仓颉原生的 CjRepoMesh 私有中心仓服务端。当前已提供健康检查，以及默认 organization 的 Hosted Registry 发布、索引和制品下载。发布过程兼容 cjpm framing，并校验令牌、包身份、SHA-256 和重复版本。

## 本地运行

先加载仓颉环境并设置 `CANGJIE_STDX_PATH`，然后执行：

```powershell
cjpm run
```

默认监听 `127.0.0.1:8080`，可通过 `CJREPO_PORT` 修改端口。存储目录默认为当前目录下的 `storage`，可通过 `CJREPO_STORAGE` 修改。设置 `CJREPO_PUBLISH_TOKEN` 后，发布请求必须携带相同的 `Authorization` 值。

健康检查：

```text
GET /health
```

## Hosted Registry 布局

```text
storage/
├── index/default/<前两字符>/<随后字符>/<包名>
└── artifacts/default/<包名>/<版本>/<包名>-<版本>.cjp
```

当前兼容的 cjpm 请求：

```text
POST /pkg/<包名>
GET /index/<前两字符>/<随后字符>/<包名>
GET /pkg/<包名>/<版本>
```

服务端会拒绝包含危险路径片段的请求；不存在的索引或制品返回 404。发布制品和索引均采用临时文件原子替换，并在进程级存储锁内复查重复版本；相同版本并发发布只允许一个成功。

## Proxy Repository

设置上游地址后，同一组 cjpm 查询和下载 API 自动变为按需代理：

```powershell
$env:CJREPO_UPSTREAM = "https://upstream.example.com"
$env:CJREPO_UPSTREAM_TOKEN = "optional-upstream-token"
$env:CJREPO_PROXY_TTL_SECONDS = "86400"
```

Cache MISS 会从上游获取并原子落盘；制品必须与已缓存索引中的 SHA-256 一致才会写入。并发首次请求在存储锁内复查缓存，因此只由一个请求访问上游，其余请求等待后直接命中。索引默认 86400 秒过期，可通过 `CJREPO_PROXY_TTL_SECONDS` 调整；制品按版本与校验和视为不可变内容，不随索引 TTL 重复下载。Cache HIT 不访问上游，因此缓存完整时支持离线构建。上游非 200 状态会原样透传，网络异常或完整性错误返回 502。

## Mirror

主动拉取指定包和版本：

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
```

```powershell
main.exe mirror-manifest https://upstream.example.com mirror.txt
```

命令会继续处理清单中的后续条目，并在结尾输出 `total`、`succeeded`、`failed` 汇总；任一条目失败或清单为空时返回非零状态。重复执行已经完整缓存的清单只输出 `SKIP`，不访问上游。

## Repository Sync

将一个 CjRepo 中的指定版本增量同步到另一个 CjRepo：

```powershell
$env:CJREPO_SYNC_DESTINATION_TOKEN = "destination-publish-token"
main.exe sync http://source:8080 http://destination:8080 meshdep 2.0.0
```

同步会从 Source 获取索引与制品、验证 SHA-256，再通过目标仓发布协议写入。目标版本已经存在时，409 被解释为幂等 `SKIP`。

当前限制：仅支持默认 organization；读取端尚未鉴权；当前使用进程级全局存储锁，尚未细化为按包锁；Mirror 已支持批量清单但尚无调度，Sync 仍以显式包和版本为粒度，二者均尚无断点续传；尚未提供 Docker 部署。
