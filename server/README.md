# CjRepo Server

仓颉原生的 CjRepoMesh 私有中心仓服务端。当前已提供健康检查，以及默认仓和命名 organization 的 Hosted Registry 发布、索引和制品下载。发布过程兼容 cjpm framing，并校验令牌、包身份、SHA-256 和重复版本。

Hosted、Proxy 与 Mirror/Sync 的目录创建共用进程内短时锁，避免不同包同时递归创建共享父目录时失败；包下载和文件写入仍使用原有包锁，不在目录锁内进行网络请求。不支持多个服务进程共用同一存储目录。

## 本地运行

先加载仓颉环境并设置 `CANGJIE_STDX_PATH`，然后执行：

```powershell
cjpm run
```

默认监听 `127.0.0.1:8080`，可通过 `CJREPO_ADDRESS` 和 `CJREPO_PORT` 修改地址与端口。容器部署使用 `CJREPO_ADDRESS=0.0.0.0`，直接运行时仍默认只接受本机连接。存储目录默认为当前目录下的 `storage`，可通过 `CJREPO_STORAGE` 修改。设置 `CJREPO_PUBLISH_TOKEN` 后，发布请求必须携带相同的 `Authorization` 值。

Proxy/Mirror/Sync共享出站TCP建连期限：`CJREPO_CONNECT_TIMEOUT_SECONDS` 默认30秒，接受整数1–300，涵盖上游读取及Sync发布。原生部署在启动进程前设置该环境变量；容器部署见[离线包说明](../deployment/portable/README.md)。非法值（包括显式空值）在主入口返回退出码2，不发请求、不回显原值。建连失败关闭socket，Proxy返回502，Mirror/Sync沿用非零失败处理；网络恢复后可以重试。此期限按单次TCP连接计算，原stdx的15秒读写超时不变，不是DNS、TLS握手或整个命令的总时限。

HTTPS上游与Sync目标在发送HTTP前验证证书链、服务器用途以及URL的DNS名称或IP SAN；身份错误拒绝连接，不改用HTTP或跳过验证。Linux原生进程可通过 `SSL_CERT_FILE` 指向团队可信CA文件，不修改系统信任库；容器还须保证CA文件在容器内可读，见[CA说明](../docs/https-client.md)。握手使用stdx的30秒读写等待设置，它不是整个握手的绝对截止，也不由TCP选项调节；慢速分片和整个操作总预算尚未验收。本服务的监听入口仍为HTTP，不等于已经提供入站HTTPS网关。

原生入口也会检查仓库基地址：`CJREPO_UPSTREAM`、Mirror 上游及 Sync 源/目标只能使用 HTTP(S) 基地址，拒绝内嵌凭据、查询参数、片段、反斜线、ASCII 控制/空白和 authority 中的百分号编码。认证使用 `CJREPO_UPSTREAM_TOKEN`、`CJREPO_SYNC_DESTINATION_TOKEN` 及 `CJREPO_SYNC_DESTINATION_READ_TOKEN`，不要写进 URL。非法地址的诊断只指出字段/角色，不回显地址值。原始空 `CJREPO_UPSTREAM` 仍关闭 Proxy；`/` 等非法相对地址不会被当成空配置。

可选设置 `CJREPO_READ_TOKEN` 启用私有读取：`/index/...` 和 `/pkg/<包名>/<版本>` 在 Hosted 与 Proxy 模式下均要求 `Authorization` 与令牌完全相同，且在检查磁盘缓存或访问上游之前拒绝无效请求；`/health` 仍公开用于健康检查。未设置时保持原来的公开读取行为。开启读取鉴权时必须同时设置 `CJREPO_PUBLISH_TOKEN`，否则服务拒绝启动，避免“读私有、写匿名”。增强版 cjpm 可用仓库配置中的 `token-env` 发送该令牌；CjRepo-to-CjRepo Sync 从私有源仓读取时可用 `CJREPO_UPSTREAM_TOKEN`。当前使用与 cjpm 兼容的原始令牌头值，不自动添加 `Bearer` 前缀；公网部署仍需 TLS 和入口层防护。

Hosted 与 Proxy 端点接受 cjpm 使用的 `?organization=<组织名>`，并按组织隔离索引和制品；不带查询参数使用默认仓。组织名必须符合 3–64 字符的仓颉标识符格式，其他查询参数、空值、编码别名和显式 `organization=default` 均返回 400，避免误读为默认仓。私有读取仍先鉴权（无令牌为 401）。Mirror 和 Sync 支持默认仓及 `组织名::包名`。

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

HTTP监听器的请求体上限与既有发布帧上限一致：`CJREPO_MAX_ARTIFACT_BYTES + 1MiB元数据 + 10字节帧头`。应用层继续校验实际制品/元数据长度及发布准入；该配置不是预分配内存或并发内存保证。此前fa00/f640服务未显式设置HTTP层上限，Content-Length大包可能先被stdx默认上限拒绝；仅调整应用环境变量不能修复旧二进制。

当前兼容的 cjpm 请求：

新增`CJREPO_MAX_INFLIGHT_ARTIFACT_BYTES`，默认134217728（128MiB）、范围1–1073741824（1GiB）；空/非法配置入口退出2。它按单进程跨组织/包累计已预留的Hosted制品数组声明字节，与`CJREPO_MAX_ARTIFACT_BYTES`单请求上限及`CJREPO_MAX_CONCURRENT_PUBLISHES`处理器名额独立。合法制品头读取后、分配数组前原子预留：单个超过总预算413，已有预留导致暂时不足429（`Retry-After: 1`、`Connection: close`），不排队；只有该请求拥有的预留在成功、失败或断连后释放。持有payload的内部方法先返回/退栈，外层再释放，仍不保证GC立即回收。

这不是总堆/RSS保证：不计元数据、响应读取、Proxy或运行时开销，显式提高预算也须结合实际堆与容器资源验证。孤立制品恢复现在以固定64KiB缓冲逐块校验长度和SHA-256，长度超出本次已验证上传即停止并返回409；不再额外整文件分配，原制品不改写。该修复不提供跨进程存储协调或磁盘读取总期限。HTTP层可能在完整请求体排空后才发送429，不承诺只发请求头/首字节立即收到响应。旧5749/aa4a及更早服务不支持字节预算，旧8b34/722f仍使用整文件孤立校验；添加变量或替换说明不能改变旧二进制。


Hosted接收按两段5字节帧头校验长度，在各自上限内分配metadata/artifact数组并循环精确读取，不再同时保留整帧累积列表和整帧副本；短读、截断、尾随字节及实际累计总帧限制仍校验，错误帧的有界丢弃保留原413优先级。哈希、包锁、索引容量和原子提交顺序保持。它仍在内存中持有完整制品，按声明长度提前分配，不是流式落盘，也不是覆盖所有分配的进程内存上限；发布名额不能换算为任意包大小下的RSS保证。

```text
POST /pkg/<包名>
GET /index/<前两字符>/<随后字符>/<包名>
GET /pkg/<包名>/<版本>
```

命名组织仓使用相同路径并追加 `?organization=<组织名>`；发布元数据和索引中的 `organization` 必须与查询参数一致。默认仓的元数据组织名为空字符串。

服务端会拒绝包含危险路径片段的请求；不存在的索引或制品返回 404。发布制品和索引均采用临时文件原子替换，并在按仓库、组织和包名定位的固定锁分片内复查重复版本；相同版本并发发布只允许一个成功。固定 256 个分片避免公开代理请求导致锁对象无限增长；不同包若哈希碰撞，仍可能串行执行。

发布中断后可重发同一包及版本：只有制品时，服务端会复核磁盘字节的 SHA-256，一致才补索引且不重写已有制品；只有索引时，只有上传字节与原索引 SHA-256 一致才补制品，原索引记录保持不变。请求仍须通过发布鉴权和上传校验。恢复成功返回兼容的 200 响应，并记录 `result=RECOVERED`；完整版本或校验和冲突仍返回 409，不能借恢复改写已发布版本。无法解析、身份不符、版本/SHA-256 格式非法或有重复版本的已有索引会被拒绝，不自动改写。此行为不等于已有制品损坏时自动覆盖修复，也不提供跨进程共享存储事务。

内部临时文件使用 `.<文件名>.tmp`，与合法包索引的命名空间分开，不能通过 Registry API 读取，避免发布 `pkg` 时覆盖 `pkg.tmp` 的索引。旧版遗留的 `<包名>.tmp` 不自动清理，因为它也可能是合法包索引；应保留证据后核对其内容和实际用途。恢复与中断测试见 [专项说明](../integration-tests/recovery/README.md)。

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

本地镜像索引只列出已下载并通过 SHA-256 校验的版本，不照搬上游的其他版本。制品先原子落盘，之后索引才公开该版本；重新访问已验证缓存时，还会离线清理旧版镜像可能留下的“有索引、无制品”条目。

持续镜像清单可使用 `main.exe mirror-watch https://upstream.example.com mirror.txt 60`；末尾为 1–86400 秒的轮询间隔。每轮重新读取清单，新版本会镜像，已缓存版本跳过；失败轮次会在下一轮重试。用进程管理器托管此命令，停止进程即可停止轮询。

Mirror/Sync 的单项、清单与 watcher 在处理缓存、读取清单或发起请求前校验地址；Sync 会先检查源和目标两者。地址配置错误直接以非零状态退出，watcher 不进入轮询；合法地址的网络请求失败仍按已有轮询规则重试。URL 校验与实际协议/连接错误是不同检查，不代表已完成所有 URI、TLS 或远端错误文本的审计。

## Repository Sync

将一个 CjRepo 中的指定版本增量同步到另一个 CjRepo；命名组织仓同样使用 `<组织名>::<包名>`：

```powershell
$env:CJREPO_SYNC_DESTINATION_TOKEN = "destination-publish-token"
main.exe sync http://source:8080 http://destination:8080 meshdep 2.0.0
```

同步先读取 Source 与 Destination 的索引并比较指定版本的 SHA-256。目标索引匹配时还会读取并校验目标制品，确认完整后才 `SKIP`，无需下载源制品；这会增加一次目标制品读取。目标制品返回 404 时重新下载源制品并通过 Hosted 恢复补齐，保留原索引；目标制品损坏或读取被拒绝时明确失败，不报告成功，也不覆盖已有字节。同版本索引校验和不同仍报冲突。并发发布导致 409 时也会重新检查目标索引及制品，只有两者一致才视为幂等跳过。

如果目标仓启用了私有读取，还须另设 `CJREPO_SYNC_DESTINATION_READ_TOKEN`；它与用于写入的 `CJREPO_SYNC_DESTINATION_TOKEN` 是独立令牌。清单中途失败后可重新运行：已成功且校验和相同的版本会跳过制品传输；当前尚无持久化进度游标。

批量同步复用 Mirror 的 `package version` 清单格式，包括可选的组织名前缀：

```powershell
$env:CJREPO_SYNC_DESTINATION_TOKEN = "destination-publish-token"
main.exe sync-manifest http://source:8080 http://destination:8080 mirror.txt
```

批量命令会继续执行后续条目并输出成功/失败汇总；任一条目失败或清单为空时返回非零状态。

持续同步清单可使用 `main.exe sync-watch http://source:8080 http://destination:8080 mirror.txt 60`。它按间隔运行同一增量同步逻辑，每轮重新读取清单，失败轮次下轮重试；需由外部进程管理器负责开机启动和进程异常重启。多个 watcher 同时处理同一清单不提供分布式租约或协调。

当前限制：读取鉴权需显式配置，默认仍为公开读取；存储锁为按包键固定分片，并非每包独占锁；Mirror/Sync 已支持默认仓和命名组织仓的显式批量清单与单进程周期轮询，但无持久化游标、字节级断点续传或分布式协调。Docker Compose 部署入口见 [部署说明](../deployment/docker/README.md)。

可选的`CJREPO_STORAGE_QUOTA_BYTES`默认0；正值限制单实例受管`index/artifacts`普通文件逻辑字节，并计入遗留临时文件和原子替换的临时峰值。共享写入及回滚删除统一计费，Hosted超额507；已有超额数据可读但拒绝新写入，不自动删除。Mirror索引提交失败只回滚当次新建制品，保留先前数据。该功能要求存储由一个进程独占，不提供文件系统块、其他进程、备份日志或磁盘空闲空间保证。配置与运行边界见[离线包说明](../deployment/portable/README.md)。

本分支对Proxy/Mirror/Sync所有共享上游读取以及Sync发布显式禁用自动重定向，包括同源跳转。源/目标配置应直接返回仓库响应；Proxy转交上游非200状态且不填充缓存，Mirror/Sync将相关3xx作为失败返回，不把跳转后的内容或发布结果视为成功。先检查仓库或反向代理端点，不通过重新启用自动跳转兼容需要跳转的服务。

实际Linux HTTP回环的302索引、307制品/发布及正常直连结果见[验证记录](../docs/verification-report.md)。这些用例不等同TLS身份、跨主机或Windows原生验收。
