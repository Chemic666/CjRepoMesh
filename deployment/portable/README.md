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

不选CA时也会创建空trust目录，默认Hosted流程可用，HTTPS出站仍需信任证书。需要Proxy时，在本部署.env另设CJREPO_UPSTREAM及可选CJREPO_UPSTREAM_TOKEN，再用显式Compose命令启动；令牌不要写进URL。已有.env或trust一律保留并拒绝重新初始化，不提供就地CA轮换或自动迁移。清单声明 `caConfiguration=pem-directory-v1`；当前带维护和依赖快照工具的包为九文件格式，旧包和既有部署不会自动更新。

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

制作端创建按完整镜像ID命名的本地别名并导出镜像，复制白名单文件，记录服务端及交付文件摘要。只接受新输出目录，不读取开发部署的 `.env`、SDK目录、客户端缓存或业务卷。生成目录包含 `image.tar`、`compose.yaml`、`configure.py`、`verify.py`、`maintenance.py`、`snapshot.py`、`README.md`、`LICENSE` 和 `manifest.json`；复制这九份文件即可交付。若制作失败，应保留失败输出供检查，新运行使用另一个空目录。

## 接收端停服备份与独立恢复

带维护工具的包在清单声明 `maintenance=cold-backup-v1`。维护前先核对可信清单和 `python verify.py --running`，暂停发布、Mirror/Sync及其他写入任务，再按上文显式Compose命令停服；工具不自动停止部署或切换入口。不要与其他Docker管理操作并发执行，也不要让多个进程共用可写数据卷。

在原安装目录执行，输出必须是尚不存在的新目录，父目录须已存在：

```console
python maintenance.py backup --output ../private-backup
python maintenance.py verify-backup --backup ../private-backup
```

备份核对固定镜像/服务端、配置与CA、数据卷标签及仍存在的停服容器身份/凭据；任何运行容器以可写方式挂载该卷都会拒绝，包括其他项目的容器。数据通过无网络、只读挂载的临时容器导出，逐项检查路径、类型、完整文件集合及SHA-256。配置在备份期间变化或末尾检查发现写入者时拒绝完成；这不是与Docker管理器共享锁的在线快照，操作者必须保持维护窗口。

备份目录包含 `backup.json`、`data.tar`、原 `.env` 及可选 `trust/ca.pem`，含私有制品和凭据，必须通过受保护渠道保管。工具在写入前建立Windows当前用户独占文件权限或Linux0600权限，不打印凭据，不将凭据写入命令行。`verify-backup`不需要Docker，只检查完整性，不认证发行者；通过可信渠道保管备份和清单，不能用可一并篡改的摘要代替信任。

首版配置只接受生成器样式的唯一字面量 `KEY=value` 行，以及空行/以 `#` 开头的注释。不接受插值、引号、转义、值内空白、重复键或额外Compose配置变量；读写令牌须非空且不同。遇到已有复杂配置时保持原部署，先独立审核如何转为等价字面量，工具不会自动改写或猜测其含义。

将同一可信完整包复制到另一个可写目录；该目录不能已有 `.env` 或 `trust`，不用先运行configure。导入并核对原固定镜像后，在这个新安装目录执行：

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

## 按批准集合制作依赖快照

当前九文件包声明 `dependencySnapshot=approved-origins-v2`，兼容旧 `approved-set-v1` 的单来源流程，也支持下节的多来源集合。单来源export从上节校验通过的停服备份中，导出一个独立批准的仓库依赖集合；与完整备份分开保存。该命令仍生成快照格式v1，要求非空的来源基线v1、每包唯一、所有条目使用同一个完全相同的仓库URL。仓库配置名、包/组织名、版本和CJP摘要均保留；URL禁止凭据、查询和fragment。不合并不同仓库地址，也不修改批准文件。

先在受保护位置独立审核完整来源基线，包含应用的传递依赖；不要以本次解析输出自动替代审批。保留该批准文件的原始字节。然后在新完整包目录执行：

```console
python snapshot.py export --backup ../private-backup --baseline ../approved/source.json --output ../private-dependency-snapshot
python snapshot.py verify --snapshot ../private-dependency-snapshot --baseline ../approved/source.json
```

新输出目录仅有 `snapshot.json` 与 `data.tar`，先建立私有文件权限再写数据。工具逐项比对真实CJP字节SHA-256与独立批准摘要，核对索引组织/包/版本/摘要并只保留选中版本，排除无关包、其他版本及运行配置/CA。索引中无条件的普通依赖必须出现在批准集合中；缺少传递项会在创建输出前拒绝。版本表达式、目标条件与替换仍交由原求解器判断，名称集合通过不等于版本约束满足。未增加多图脚本或测试构建支持。

验证始终需要外部批准文件，字节摘要须与导出时完全一致，连格式变化也须重新导出。它同时核对快照两文件、完整存储集合、选中索引及实际CJP摘要；链接、越界、重复/冲突路径、重复JSON字段、错误组织、重复索引版本或不匹配均拒绝。批准文件限制1MiB、清单16MiB、单包索引64MiB，制品与归档摘要以分块读取；没有总磁盘/包数量配额。快照仍含内部地址和源码，任意CJP/索引本身也可能含私密信息；导出不等于可以公开，需按内部依赖材料保管。

## 将依赖快照装入新的私有仓

在另一个可信完整包目录，先按首次启动说明加载并核对固定镜像，再生成这个接收者自己的读写凭据。此处需要先configure，与完整备份restore保留旧配置的流程不同。保持Hosted默认配置，不设置上游，也不先启动Compose或创建数据卷：

```console
python configure.py --port 8081
python snapshot.py seed --snapshot ../private-dependency-snapshot --baseline ../approved/source.json
docker compose -f compose.yaml --env-file .env up -d --no-build --pull never
```

seed要求与快照完全相同的镜像/服务端，只创建本配置对应的新标签卷，拒绝已有卷/导入记录及Proxy配置；不改接收者凭据、CA或批准文件。输入损坏/失配在创建卷前拒绝；解包前再次校验，导入后再只读导出比较完整文件集合及摘要，成功写 `snapshot-import.json` 并保持服务停服。重复seed拒绝，不覆盖数据。失败时保留新卷、校验归档和已有配置，不把半完成目录当成功部署；用新目录、新配置重试，按归属检查失败资源。辅助容器诊断沿用维护工具的保留规则。

启动后先检查实际私有读取、未选中版本不可用，并用当前可信完整客户端、独立只读批准文件和空缓存编译运行预期应用。来源基线绑定原始URL；新地址不会自动匹配。需要稳定受控入口或独立审核目标地址；本工具不改写来源批准、不自动设置DNS或切流。

要声称依赖离线可用，须在原仓库/上游不可达且消费任务没有其他仓库网络出口的隔离环境实际冷构建。快照本身不证明项目所有输入离线：SDK/stdx、客户端、项目源码、Git/本地依赖及脚本外部输入仍须独立提供和约束。它不认证发布者或索引作者，不解包CJP校验内部依赖声明，不重新验真旧源码缓存；快照清单摘要仍需可信渠道核对，没有签名、构建沙箱、完整主机气隙或任意跨主机迁移保证。

新验证器保留真实旧七文件包及仅有维护能力的旧八文件包的精确集合检查，未知快照能力拒绝；不要向旧包手工添加工具或能力字段。

## 多来源依赖快照集合

一个项目的内部包与传递依赖来自不同仓库时，使用 `export-set` 保留每个原始URL的数据分片。外部批准文件仍是独立审核后的完整来源图，格式不变；所有分片和集合绑定同一文件的原始字节摘要。CI继续使用这一完整文件，不生成或改用按本次求解结果缩小的批准文件。

先暂停各原仓库的写入，在各自可信交付目录分别完成上文停服备份。一个批准仓库配置名只能关联一个完全相同的URL；一个URL可有多个配置别名，使用其中一个名称指定该来源的一份备份即可。`--source`后的两个参数分别是批准中的配置名和已有备份目录，可重复指定：

```console
python snapshot.py export-set --source internal ../private-internal-backup --source home ../private-home-backup --baseline ../approved/full-source.json --output ../private-snapshot-set
python snapshot.py verify-set --snapshot-set ../private-snapshot-set --baseline ../approved/full-source.json
```

工具先核对全部来源映射、完整备份及选中索引/CJP，全部通过才创建输出。缺少、额外或重复的来源，后一个备份的制品失配，以及将输出放在任一源备份内部，均拒绝；不改变原备份。导出开始后的失败保留部分输出供检查，重试需新目录。

集合只有 `snapshot-set.json` 和若干 `origin-0001` 这样的目录，每个目录仍只有 `snapshot.json`、`data.tar`。集合清单记录每个原始URL、分片目录和清单摘要；分片格式v2显式记录 `selection=exact-registry-v1`，包含该URL下的全部批准项，保留完整批准字节摘要。无条件依赖名称检查使用完整批准图，因此允许一个原URL的parent依赖另一个原URL的meshdep；不把两个仓库存储内容合并。版本/目标/替换仍由原客户端决定。

`verify-set`要求完整覆盖批准中的全部原URL、精确目录集合及分片绑定，逐个重新检查索引和实际CJP摘要。即使重算集合清单，也不能通过删掉来源、交换URL绑定、扩展分片包集合或替换批准文件来改变准入范围。分片的单独verify/seed只确认该分片的内容；其余来源是否已部署仍须整集合检查和实际冷构建确认。

按 `snapshot-set.json` 的URL映射，在每个原URL对应的独立新接收目录分别configure和seed；每个接收实例继续沿用既有单实例服务。目录编号只是内部标识，不表示固定角色，不要凭编号猜来源。示例中的一个分片：

```console
python configure.py --port 8081
python snapshot.py seed --snapshot ../private-snapshot-set/origin-0001 --baseline ../approved/full-source.json
```

seed保持相同镜像、新Hosted配置、新卷、接收者自己的凭据及导入后停服的契约。全部必要来源准备好后，由操作者核对原受控地址、身份及配置，再分别启动和执行完整批准图的隔离冷构建。工具不自动部署/启动多个服务，不自动切换DNS、地址、凭据或业务入口；地址变化需要独立审核，不能通过缩小批准集合或放宽URL比较绕过。

新版包读取单来源v1和分片v2；真实旧 `approved-set-v1` 包仍只处理单来源v1，会拒绝新分片。新增能力需领取完整可信新包，不能零散替换文件或添加字段。签名、索引作者认证、CJP内部依赖检查、旧缓存再验真、恶意并发替换、磁盘配额和全部外部构建输入离线等边界保持前述限制；集合不是完整仓库灾难备份。
