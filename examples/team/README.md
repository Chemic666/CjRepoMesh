# 开发者发布与只读CI接入示例

已获得声明 `teamPreparation=single-use-cold-v1` 的完整客户端团队包时，可离线执行 `python3 /path/to/client-bundle/prepare-team.py` 并传入下文相同参数，无需检出源码。该入口先校验整个包，只创建包外新目录；下文的 `examples/team/prepare.py` 是源码仓库路径，用工具包时替换为上述入口。实际编译仍需已有SDK/stdx，任务凭据及独立来源批准继续由外部提供。

本例提供可复制的私有库发布任务与消费任务；首次接收当前固定双包时，先按[完整接入顺序](../../docs/operations.md#固定双包的首次接入)核对包、角色凭据和独立批准。服务端可用[离线服务端包](../../deployment/portable/README.md)启动；任务执行机仍需现有Linux仓颉SDK（含cjlint）、匹配的增强版cjpm及本机归档/链接工具和开发链接文件（如ar、ld、GCC/系统启动对象）。准备目录只需要Python 3.10+，`run.sh`为Linux/Bash任务入口，不安装工具链、不下载依赖。Windows原生仓颉执行当前暂停，真实编译分别在Linux/WSL或Linux容器中验收，范围见对应记录。

## 任务角色

发布者构建并发布 `company::teamhello 1.0.0`，使用发布令牌；消费端以独占路由读取该私有包，编译运行应用，只使用读取令牌。本版凭据是实例级读写区分，不提供逐用户或逐组织授权。只读CI不应配置发布凭据。

## 准备发布目录

在源码根目录运行；Linux将 `python` 换成 `python3`。地址按实际接入填写，这里假定服务与任务在同机：

```console
python examples/team/prepare.py --role publisher --registry http://127.0.0.1:8080 --output ../team-publisher
```

通过CI的受保护变量或本机受保护会话设置 `CJREPO_PUBLISH_TOKEN`，并将 `CJREPOMESH_CJPM` 设置为已有增强版可执行文件路径。加载现有SDK环境后，在生成目录执行：

```bash
bash run.sh
```

任务会执行真实 `bundle` 与 `publish`。再次发布同一版本会返回冲突；需要改代码时应修改包版本和消费依赖，不把冲突当成发布成功。不要将发布令牌放在URL或命令行参数中。

`--output`必须是尚不存在的新路径。已有文件、目录和链接（包括悬空符号链接或Windows目录联接）均会拒绝，不跟随该输出名称去创建目标。保留旧任务，重新准备时选另一个新目录；这不提供父目录链接或恶意并发替换隔离。

准备器完成CA、源码、配置和元数据后，才从同目录临时文件生成最终 `run.sh`。准备失败会返回非零，保留已写文件和可能的 `.run.sh.tmp`，不会留下最终运行入口。保留现场并选另一个新目录重试，不运行临时文件或手工补出入口；`workspace.json`本身不代表准备成功。这不是断电持久性或对恶意修改的保证。

使用[完整客户端交付包](../../deployment/client/README.md)时，将 `CJREPOMESH_CJPM` 设置为包内 `run.sh` 的完整路径即可，例如 `/opt/cjrepomesh-client/run.sh`。不要只复制其中的cjpm或启动器；启动器每次先校验整个包，再执行客户端，因此任务环境还须有Python 3。完整SDK、cjlint和系统链接工具仍由任务机提供，服务端最小镜像本身不提供这些工具。

## 准备独立消费任务

需要强制每次CI使用新目录时，可显式加 `--single-use`，仅支持consumer：

```console
python examples/team/prepare.py --role consumer --registry https://registry.example --single-use --output ../team-ci-once
```

私有CA仍按下文提供 `--ca-file`/`--ca-sha256`。运行前必须注入非空 `CJREPOMESH_SOURCE_BASELINE`，批准文件继续由外部独立审核；然后按原方式加载SDK、读取令牌和可信客户端，执行生成目录的 `bash run.sh`。默认不加此选项时保持原任务行为。

此模式额外复制 `job.py`，将生成时仓库配置的实际字节SHA-256写入运行入口与workspace.json。CA/能力检查后、build前，守卫要求配置仍匹配、`.home`为普通空目录，cache、target、build、build-script-cache、lockfile、来源输出/临时文件及build.cj.bak均不存在，包括悬空链接。随后原子创建 `.cjrepomesh-job-started`；同一目录的正常并发启动最多一个进入构建。检查前置失败保留已有内容，不创建领取标记；一旦领取，成功、来源拒绝或编译/应用失败均保留标记和现场。

不要删除标记或清缓存后重跑同一任务；用prepare选择另一个新目录。移动任务时复制完整目录并保持配置原字节。workspace.json仍不代表准备成功，最终run.sh只在所有准备步骤完成后生成；守卫复制失败也不会暴露运行入口。新功能属于新源码准备器及新生成任务，旧任务、客户端包和服务端包不会自动获得此模式。

守卫防止正常CI误复用旧状态，不重新验证已解包缓存，也不固定全部源码/工具链或阻止恶意修改任务、环境及并发替换文件；不提供脚本沙箱、分布式租约或断电事务保证。自定义build.cj仍可能在主图拒绝前执行，并在本次命令内部生成缓存；来源准入仍按每次实际分析执行。

```console
python examples/team/prepare.py --role consumer --registry http://127.0.0.1:8080 --output ../team-ci-job
```

在消费任务的受保护变量中仅配置 `CJREPO_READ_TOKEN` 和增强版 `CJREPOMESH_CJPM` 路径，加载SDK环境，然后在生成目录执行：

```bash
bash run.sh
```

任务先执行 `cjpm build`，再直接运行本例默认产物 `target/release/bin/main`；两步均成功后才离线解释解析记录，输出应含 `CjRepoMesh team 1.0.0: CI`。直接执行产物可精确保留应用退出码；修订后的增强客户端 `cjpm run` 将应用非零映射为1，旧af35及此前客户端仍有忽略失败的问题，示例兼容两者。每个任务拥有自己的 `.home` 和 `cache`；不同任务使用不同新目录。目录准备器不读取令牌，不生成凭据文件，不覆盖已有目录；脚本关闭命令回显并移除本例另一个角色的令牌变量。

## HTTPS与已批准的私有CA

HTTPS使用私有CA时，可在准备阶段传入公开PEM和独立核对的摘要，消费端无需再手工设置SSL环境变量：

```console
python examples/team/prepare.py --role consumer --registry https://repo.example.invalid:8443 --ca-file receiver-ca.pem --ca-sha256 <独立批准的64位SHA-256> --output ../team-https-ci
```

发布任务同样支持这两个参数，将role改为publisher即可。`--ca-file`只接受HTTPS地址及不超过1MiB的普通、非链接、仅含证书的有效PEM，不接受私钥。`--ca-sha256`可选，但填写时必须匹配；未填写只固定本次读到的CA字节，不替代可信渠道对CA身份的审核。非法输入在创建任务目录前拒绝，不回显PEM内容；原HTTP用法及不指定CA的调用保持原行为。

任务目录保存公开 `trust/ca.pem`、空的 `trust/empty/` 和独立 `trust.py`。生成的run.sh在调用任何客户端命令前校验CA原字节及空信任目录，再为本进程设置 `SSL_CERT_FILE`、`SSL_CERT_DIR`；覆盖本任务继承的这两个值，不安装系统根证书、不关闭TLS校验、不修改代理或防火墙。目录可以整体移动，运行时不依赖源码仓库中的准备器或原CA文件。CA缺失/改动、目录混入其他根证书或别名链接会失败，不能删除信任元数据后自动回退到原设置。

继续按原方式注入对应读取/发布令牌及客户端路径，并先加载已有SDK，再执行 `bash run.sh`。`CJREPOMESH_SOURCE_BASELINE`的能力前置及独立批准语义保持；新仓库URL仍须独立批准，准备器不会生成来源批准文件、读取令牌或访问仓库。CA更新应使用重新批准的输入准备新目录，保留旧任务和证据。该机制处理正常任务的误配，不是针对恶意修改脚本、摘要、工具链或并发替换的沙箱/签名保证。

## 接入CI

在已经有工具链的自托管Linux任务机上，固定工具包方式直接通过包内prepare-team.py生成新消费目录，无需检出工具源码；仅源码方式需要检出本仓库并调用examples/team/prepare.py。由CI注入读取秘密及独立批准、加载SDK环境，再执行任务的 `bash run.sh`；普通项目源码仍由自己的构建流程提供。当前示例不依赖某家CI服务，也不创建远端流水线。让任务执行失败时直接保留非零退出状态。

可在CI内部保存锁文件、`cjpm-provenance.json`和编译日志以定位依赖来源；解析记录不证明整个编译成功，应同时检查任务退出状态和运行输出。报告和日志可能包含内部仓库地址与工作路径，按团队的内部材料保管。

需要限制本次实际选源时，可使用当前增强客户端，在受保护环境设置 `CJREPOMESH_SOURCE_BASELINE=/protected/team-source-baseline.json` 后执行同一 `bash run.sh`。本脚本保留该变量；批准文件应是独立审核、放在任务可写输出之外的来源记录副本，不在任务中自动生成或更新。检查在本次仓库制品下载前比较完整最终集合（含传递依赖和选中的替换项），失配即非零退出；索引访问可先发生。详见[来源基线的批准流程与边界](../../docs/repository-source-baseline.md)。

新版消费脚本在该变量已设置时（包括空值）先执行 `repo supports source-baseline-v1`，只接受退出0且stdout为精确标记；不支持、异常响应或调用失败在构建前退出2。完整包启动器的校验信息走stderr，兼容此检查。未设置基线变量时不增加查询，原流程保持。8da5已有基线功能但缺少能力查询，也会被新版受保护任务保守拒绝，需使用[当前客户端](../../docs/candidate-acceptance.md)。能力响应不能认证程序来源，仍须使用可信分发及完整包校验；直接调用旧版 `cjpm build` 不会由示例代做检查。

若自己的项目存在与主图不同的 `script-dependencies`，可同时设置 `CJREPOMESH_SCRIPT_SOURCE_BASELINE=/protected/script-source-baseline.json`，分别精确批准脚本图和主图。消费入口要求主批准已配置，并额外检查 `script-source-baseline-v1` 能力，旧客户端在build前拒绝。默认示例无脚本依赖，不需要新增变量；准备器也不会生成这两份批准。所有脚本分析共用脚本文件，已缓存/已重定位脚本不因此强制重分析；这不提供脚本沙箱或整命令原子拒绝。

默认同机地址不是跨主机方案。任务在容器网络内时可以使用该网络中的服务名地址；跨机器接入和HTTPS需另行设置及验证。本例不证明公有云CI、全新主机、容量或升级恢复已验收。
