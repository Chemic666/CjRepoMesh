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

不选CA时也会创建空trust目录，默认Hosted流程可用，HTTPS出站仍需信任证书。需要Proxy时，在本部署.env另设CJREPO_UPSTREAM及可选CJREPO_UPSTREAM_TOKEN，再用显式Compose命令启动；令牌不要写进URL。已有.env或trust一律保留并拒绝重新初始化，不提供就地CA轮换或自动迁移。新包清单声明 `caConfiguration=pem-directory-v1`；仍是七文件格式，旧包和既有部署不会自动更新。

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

制作端创建按完整镜像ID命名的本地别名并导出镜像，复制白名单文件，记录服务端及交付文件摘要。只接受新输出目录，不读取开发部署的 `.env`、SDK目录、客户端缓存或业务卷。生成目录包含 `image.tar`、`compose.yaml`、`configure.py`、`verify.py`、`README.md`、`LICENSE` 和 `manifest.json`；复制这七份文件即可交付。若制作失败，应保留失败输出供检查，新运行使用另一个空目录。

输出路径已存在时，包括悬空目录链接，应在访问Docker前拒绝；不通过解析链接将它当作新的目标路径。旧交付归档不自动更新，领取新包时核对清单与归档摘要，保留原部署的配置和数据。

当前包为试点交付，未提供自动升级、自动备份、故障切换或容量保证。实际执行记录以源码仓库的验证报告为准。
