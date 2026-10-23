# CjRepoMesh 离线服务端交付包

适用于单实例、Linux amd64 容器。接收端需要 Python 3.10+、已运行的 Docker Engine 与 Docker Compose v2；启动服务不需要仓颉 SDK、源码仓库或开发机 WSL。开发者运行仓颉项目仍需匹配的 SDK/stdx 及增强版 cjpm，本包不包含客户端。

## 接收端首次启动

将完整交付目录复制到可写目录。在该目录执行以下命令；Linux 将 `python` 换成 `python3`：

```console
python verify.py
docker load --input image.tar
python verify.py --docker
python configure.py --port 8080
docker compose -f compose.yaml --env-file .env up -d --no-build --pull never
docker compose -f compose.yaml --env-file .env ps
```

等待容器变为 healthy，访问 `http://127.0.0.1:8080/health`。如果端口已占用，应先在初始化时选择其他端口。首次配置会生成独立的 Compose 项目名、发布令牌和读取令牌，保存至 `.env`，不输出令牌值。Windows 先设置并验证当前用户独占的文件权限，Linux 使用0600；不修改系统安全策略。再次配置会拒绝覆盖已有 `.env`，重启直接沿用原文件。

初始化失败时，助手只尝试清理本次独占创建且文件身份未变的文件，以及本次创建的空trust目录，不递归删除或替换其他内容。权限不足或发现其他文件时仍可能留下残余；应先确认.env是否为空、trust是否属于本次失败再处理，不能删除已有部署的配置。容器入口要求读写令牌均非空，缺失时拒绝启动，不会降级为匿名读写。

该包固定使用清单中的镜像，不构建、不自动拉取。校验包括全部交付文件的大小及SHA-256；`--docker`另核对已导入镜像身份和镜像内服务端摘要。完整性检查不证明发行者身份，应通过可信渠道确认清单摘要。附带 LICENSE 为项目许可；镜像包含Ubuntu用户空间及仓颉运行时，不包含完整SDK。

校验与初始化以当前调用脚本所在目录为准，已知交付文件必须是普通文件；不能用指向另一交付目录的 `verify.py` 或 `configure.py` 链接替代。这样可避免校验别的包或把新凭据写到别处。它不提供对恶意替换整个包或并发篡改的真实性保证。

默认只绑定本机回环地址，读取和发布均需相应令牌。此包先解决独立交付；跨机器访问、HTTPS入口及团队接入应另行配置和验证，不以本地健康检查代替。

本包服务端的Proxy/Mirror/Sync上游读取与Sync发布不自动跟随HTTP跳转。请配置直接提供索引、制品或发布响应的端点；遇到3xx先修正仓库/网关地址，不把另一个地址的响应当作原仓库成功，也不自动转发发布包体。需要重定向的服务必须先调整端点，本包不提供自动跨端点跳转兼容。

新服务端限制每次发布/上游读取的有效载荷：制品默认128MiB，`.env` 中 `CJREPO_MAX_ARTIFACT_BYTES` 可设1–1073741824字节；上游索引默认4MiB，`CJREPO_MAX_INDEX_BYTES` 可设1–67108864字节。发布元数据固定最多1MiB，总帧最多为制品上限+1MiB+10字节。非法/空配置启动退出2且不回显原值；修改后需重建容器以生效。发布实际累计或声明长度超限返回413，鉴权仍先于读取；上游按实际字节限制，含无Content-Length的分块响应，超限Proxy返回502、Mirror/Sync失败，不写入本次索引或制品。普通错误继续按原协议处理。

这些是单请求大小边界，仍会在限定大小内缓冲数据，不能换算为同等内存占用上限；本包没有提供流式落盘、并发配额、磁盘配额、Hosted累计索引大小限制或整个操作总期限。旧归档不会自动获得新限制，接收时核对完整包/镜像/服务端摘要。

出站TCP连接默认最多等待30秒/次。需要调整时，在本部署受保护的 `.env` 中加入 `CJREPO_CONNECT_TIMEOUT_SECONDS=10`，有效范围为整数1–300；省略时使用30，空值或非法值令服务启动失败，诊断不回显原值。Compose通过现有 `env_file` 将其传入容器，仅在宿主命令行设置变量不足以完成配置；修改后使用本页显式Compose命令重建服务以生效，并保留原项目名、凭据和数据卷。原库15秒读写超时不变；此选项只约束每次TCP建连，不约束DNS、TLS握手或完整同步总时长。

新服务端支持HTTPS上游读取与Sync发布，始终验证证书链及URL中的DNS名称或IP SAN，不提供跳过身份校验的选项。当前镜像有TLS运行库，没有预装公共根证书集合。新包首次初始化时，可用下面的命令替代前面的configure命令，导入团队通过可信渠道提供的PEM证书：

```console
python configure.py --port 8080 --ca-file "D:\trusted\team-ca.pem"
```

输入只允许普通文件、最大1MiB、一个或多个PEM CERTIFICATE块；私钥、其他内容、无效证书和链接文件均拒绝，不回显内容。助手复制证书到本安装的 `trust/ca.pem`，原文件保持；在.env记录摘要，Compose固定以只读bind挂载整个trust目录，并给服务进程设置容器内SSL_CERT_FILE路径。不安装系统CA，不修改宿主信任库。Linux新目录0755、证书0444以便非root容器读取；证书副本不含私钥，.env仍保持私有权限。

不选CA时也会创建空trust目录，默认Hosted流程可用，HTTPS出站仍需信任证书。需要Proxy时，在本部署.env另设CJREPO_UPSTREAM及可选CJREPO_UPSTREAM_TOKEN，再用显式Compose命令启动；令牌不要写进URL。已有.env或trust一律保留并拒绝重新初始化，不提供就地CA轮换或自动迁移。清单声明 `caConfiguration=pem-directory-v1`；当前带维护工具的包为八文件格式，旧包和既有部署不会自动更新。

## 运行中的部署诊断

服务healthy后，在原交付目录执行：

```console
python verify.py --running
```

此模式先校验交付文件，再从原 `.env` 读取项目名和端口；通过显式Compose文件定位唯一实例，核对运行/健康状态、镜像与容器内服务端摘要、项目/服务标签、数据卷名称及标签、非root/只读根/禁止额外capability与privileged等权限限制和精确回环端口绑定。最后只访问本机健康接口，不使用代理或跟随跳转，不回显Docker检查结果、令牌或错误正文。未启动/已停服、改了项目名或容器不匹配均失败，不把其他健康服务当作本部署。HTTP已能响应时Docker仍可能处于starting，应等待其健康检查完成后再运行。

诊断不创建、启停容器或修改配置/数据；容器内仅执行摘要/目录读取。本地还以相同显式Compose文件和.env运行只读 `config --format json`，按Compose实际解析的引号、插值及env_file结果，在内存中比对运行实例的读写令牌；缺失、重复、空值或不匹配均失败，不保存或输出配置正文、令牌或摘要。修改.env但未重建容器时会提示凭据不匹配，诊断不会自动应用修改；先核对本地变更，再按停止与重建流程操作。只有本次接收的新完整包具备此检查，旧包不会自动更新。

配置值相等仍不代表实际认证/读写成功，成功后须按团队示例验证发布、下载及真实构建。`--running`与`--docker`互斥：前者检查现有部署，后者检查已加载镜像并临时运行摘要命令；普通文件校验不需要Docker。不要把 `docker compose config` 的原始输出复制进公开日志，它含凭据。

对声明CA配置能力的新包，运行诊断还核对本地trust目录及证书、配置摘要、容器环境、只读bind挂载、容器内目录和证书实际摘要；无CA时两端目录均须为空。元数据丢失不能冒充旧包豁免。仅实际旧清单保留原诊断兼容。检查核对有效证书内容与只读属性，不比对Docker宿主Source路径或审计宿主ACL，不代替可信渠道确认CA来源；容器内还会执行只读的目录列举。

## 凭据与客户端

在受保护环境中读取 `.env`，将 `CJREPO_READ_TOKEN` 配到客户端进程环境变量，再由 `cangjie-repo.toml` 的 `token-env` 引用；发布操作使用 `CJREPO_PUBLISH_TOKEN`。开发与CI应分别使用自己的本地缓存；本版令牌为实例级读/写区分，不是逐用户或逐组织授权。

同机读取端的最小配置如下；发布时改为引用发布令牌所在的环境变量：

```toml
[repository.cache]
path = "./cjpm-cache"
[repository.home]
registry = "http://127.0.0.1:8080"
token-env = "CJREPO_READ_TOKEN"
```

不要上传 `.env` 或包含它的已初始化目录。Docker管理权限可以查看容器环境变量。Compose文件使用 `.env` 作为容器凭据来源；执行命令前核对当前进程没有覆盖 `COMPOSE_PROJECT_NAME`、`CJREPO_HOST_PORT` 的同名变量。所有命令显式使用 `-f compose.yaml`，防止同目录额外覆盖文件或 `COMPOSE_FILE` 改变已校验的镜像、端口和挂载配置。

## 停止与重建

```console
docker compose -f compose.yaml --env-file .env down
docker compose -f compose.yaml --env-file .env up -d --no-build --pull never
```

普通 `down` 保留命名数据卷；不要加 `-v`。保留 `.env` 中的项目名，重建才能重新连接该卷。不要重跑初始化、随意换项目名或让多个服务进程共用可写存储。只保留镜像不构成数据备份；应停服后另行备份完整数据卷、配置和凭据，恢复到新卷核对后再切换。

## 制作端

源码仓库中使用已构建的本地服务端镜像执行：

```console
python deployment/portable/package.py --image cjrepomesh:delivery-20261021 --output ../CjRepoMesh-offline
```

制作端创建按完整镜像ID命名的本地别名并导出镜像，复制白名单文件，记录服务端及交付文件摘要。只接受新输出目录，不读取开发部署的 `.env`、SDK目录、客户端缓存或业务卷。生成目录包含 `image.tar`、`compose.yaml`、`configure.py`、`verify.py`、`maintenance.py`、`README.md`、`LICENSE` 和 `manifest.json`；复制这八份文件即可交付。若制作失败，应保留失败输出供检查，新运行使用另一个空目录。

## 接收端停服备份与独立恢复

当前八文件包在清单声明 `maintenance=cold-backup-v1`。维护前先核对可信清单和 `python verify.py --running`，暂停发布、Mirror/Sync及其他写入任务，再按上文显式Compose命令停服；工具不自动停止部署或切换入口。不要与其他Docker管理操作并发执行，也不要让多个进程共用可写数据卷。

在原安装目录执行，输出必须是尚不存在的新目录，父目录须已存在：

```console
python maintenance.py backup --output ../private-backup
python maintenance.py verify-backup --backup ../private-backup
```

备份核对固定镜像/服务端、配置与CA、数据卷标签及仍存在的停服容器身份/凭据；任何运行容器以可写方式挂载该卷都会拒绝，包括其他项目的容器。数据通过无网络、只读挂载的临时容器导出，逐项检查路径、类型、完整文件集合及SHA-256。配置在备份期间变化或末尾检查发现写入者时拒绝完成；这不是与Docker管理器共享锁的在线快照，操作者必须保持维护窗口。

备份目录包含 `backup.json`、`data.tar`、原 `.env` 及可选 `trust/ca.pem`，含私有制品和凭据，必须通过受保护渠道保管。工具在写入前建立Windows当前用户独占文件权限或Linux0600权限，不打印凭据，不将凭据写入命令行。`verify-backup`不需要Docker，只检查完整性，不认证发行者；通过可信渠道保管备份和清单，不能用可一并篡改的摘要代替信任。

首版配置只接受生成器样式的唯一字面量 `KEY=value` 行，以及空行/以 `#` 开头的注释。不接受插值、引号、转义、值内空白、重复键或额外Compose配置变量；读写令牌须非空且不同。遇到已有复杂配置时保持原部署，先独立审核如何转为等价字面量，工具不会自动改写或猜测其含义。

将同一可信八文件包复制到另一个可写目录；该目录不能已有 `.env` 或 `trust`，不用先运行configure。导入并核对原固定镜像后，在这个新安装目录执行：

```console
python maintenance.py restore --backup ../private-backup
python verify.py --docker
docker compose -f compose.yaml --env-file .env up -d --no-build --pull never
```

恢复只接受与备份完全相同的镜像/服务端身份。它校验全部输入后生成不同的项目名和新数据卷，拒绝已有卷；保留原配置字节及读写凭据，只改变项目名。若明确需要其他本机端口，在restore时加 `--port 8081`；工具不自动寻找端口。解包后再次导出并比较完整文件集合/摘要，成功生成 `restore.json`，服务仍保持停服，由操作者核对后启动。原实例、卷和备份不会删除或覆盖。

恢复失败时保留新配置、新卷和可能的 `restore-check-*.tar` 供本地排查，服务不会由本工具启动；不要在这个半完成目录重试或手工把它当作成功部署。保留证据，使用另一个未配置的完整包和新卷重新恢复。成功后仅清理本次有身份标签的临时容器；传输失败时核对身份，停止仍运行的辅助容器并保留它及Docker日志，提示其ID。辅助容器日志可能包含私有制品数据，继续按内部材料保管，排障后由操作者核对归属再清理。

等待恢复实例healthy后，运行 `python verify.py --running`，核对私有读取与发布权限、包摘要，并用独立消费任务完成空缓存构建/运行，再决定入口切换。使用来源基线时应保留经过审核的仓库URL；若迁移地址改变，需独立审核目标基线，工具不改批准文件。记录本身不证明构建成功。旧七文件包仍按原清单验证，不会自动获得维护工具；不要零散替换验证器或伪造能力字段。

本功能是停服快照和独立恢复，不提供自动升级、在线备份、CA/凭据轮换、断电持久性、恶意并发替换防护或跨主机入站HTTPS保证。解包只接受索引/制品目录下的普通文件和目录，链接、特殊文件、越界及冲突路径均拒绝；不将未校验归档直接交给宿主解包器。

输出路径已存在时，包括悬空目录链接，应在访问Docker前拒绝；不通过解析链接将它当作新的目标路径。旧交付归档不自动更新，领取新包时核对清单与归档摘要，保留原部署的配置和数据。

当前包为试点交付，未提供自动升级、自动备份、故障切换或容量保证。实际执行记录以源码仓库的验证报告为准。
