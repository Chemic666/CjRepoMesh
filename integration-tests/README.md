# CjRepoMesh 端到端验证

四组核心测试由同一个 Python 标准库运行器编排，Windows 与 Linux 共用夹具、断言、安全边界和清理逻辑；PowerShell 与 Bash 仅负责加载平台环境。Windows 一键部署是平台专属的第五组。

核心入口失败时保留该次唯一 `.tmp/run-*` 目录及生成现场，并报告位置；成功仍按原流程清理。服务健康等待观察本次子进程早退码和对应日志位置，不打印日志正文。失败目录可能含内部地址和合成数据，应按内部证据保管；保留日志不等于已确定启动失败根因。合成回归入口为 `python -m unittest discover -s integration-tests -p test_harness_evidence.py`。

如果希望先理解完整使用场景，见[连贯企业依赖演练](showcase/README.md)。一个入口串起同名公共高版本对照、私有命名空间保护、错误令牌阻断、上游停服、私有副本与离线来源解释，使用真实包和全新客户端缓存。它不替代四组回归或官方测试。

固定客户端、服务端、交付包及同一产物的新执行/引用证据集中在[固定候选验收清单](../docs/candidate-acceptance.md)，其中仍未验收项单独列出。

在线来源解释回归：`python3 integration-tests/compatibility/explain_preview.py --cjpm <已有Linux客户端> --package-dir <真实默认组织meshdep-1.0.0的target目录> --evidence-dir <新目录>`。以合成双版本索引和真实1.0.0 CJP核对锁定构建/实际运行、候选预览2.0.0的范围提示、recorded1.0.0及锁/记录不变；第二版本只用于候选，不下载或冒充真实2.0.0构建。需先加载已有SDK/stdx，不执行Windows仓颉。

大小边界回归：`python3 integration-tests/compatibility/server_payload_limits.py --server <已有Linux服务端> --package-dir <同上真实CJP目录> --evidence-dir <新私有目录>`。24项覆盖非法配置、制品和元数据临界值、独立元数据声明/实际超限、分块总帧、鉴权优先、Proxy索引/分块制品超限及同实例恢复、Mirror/Sync索引/制品超限失败和无写入。合成上游制品有匹配摘要，不能仅靠摘要不符误判大小限制；日志落盘前脱敏、隐私断言使用原始内存值。仅操作自有进程/存储，不做耗尽内存、全量压力或Windows仓颉测试。

## Windows 全量入口

在已经安装仓颉 SDK、stdx 和 Windows 构建工具的环境中，从项目根目录运行：

```powershell
.\integration-tests\run-all.ps1
```

统一入口不会下载或安装任何依赖，会先运行四组共享核心测试，再运行 Windows 部署测试：

| 测试组 | 主要覆盖 |
| --- | --- |
| Multi-repository cjpm | 多仓聚合、优先级、跨仓传递依赖与冲突、`[replace]`、Explain、Doctor、Provenance、认证屏障、独占路由和旧配置兼容 |
| Hosted repository | 发布、索引、下载、私有读取鉴权、SHA-256、重复版本和并发原子写 |
| Proxy repository | MISS/HIT、私有读取拦截上游访问、并发填充合并、索引 TTL、离线缓存和损坏拒绝 |
| Repository sync | 批量 Mirror/Sync 清单、部分失败汇总；镜像只公开已验证的本地版本并离线清理旧索引；源/目标索引比较、已有制品跳过下载、校验和冲突拒绝；私有目标仓读写令牌分离、周期 watcher 清单变更、幂等和源仓离线构建 |
| Windows deployment | 一条命令构建启动、健康检查、持久化重启、诊断和安全停止 |

可显式指定增强版 cjpm 和环境脚本：

```powershell
.\integration-tests\run-all.ps1 `
  -Cjpm "D:\path\to\cjpm.exe" `
  -EnvSetup "D:\Apps\Cangjie\envsetup.ps1"
```

已有服务端二进制且只需复验运行链路时，可显式使用 `-SkipServerBuild`；正式全量回归不得使用该参数代替服务端编译。

## Linux / WSL 全量入口

先加载现有 Linux SDK 并指定 stdx；脚本不会自行下载、安装或解压依赖：

```bash
source /path/to/cangjie/envsetup.sh
export CANGJIE_STDX_PATH=/path/to/stdx/linux_x86_64_cjnative/static/stdx
./integration-tests/run-linux.sh
```

默认使用 `cjpm/dist/cjpm` 和 `server/target/release/bin/main`。路径不同时使用环境变量覆盖：

```bash
export CJREPOMESH_CJPM=/path/to/enhanced/cjpm
export CJREPOMESH_SERVER=/path/to/cjrepo
./integration-tests/run-linux.sh
```

可只运行单组：

```bash
./integration-tests/run-linux.sh --suite multirepo
./integration-tests/run-linux.sh --suite hosted
./integration-tests/run-linux.sh --suite proxy
./integration-tests/run-linux.sh --suite sync
```

运行器会在开始前拒绝已占用的固定测试端口，在每组结束时回收全部子进程并确认端口关闭。服务端仅构建一次，夹具产物、应用缓存、锁文件、Provenance 和请求日志会在成功或失败后统一清理；服务端测试存储使用被 Git 忽略的 `integration-tests/.tmp/`。

## 官方原版兼容性差分

服务端发布中断、残留临时文件、仓间同步与冷备份恢复另有 [恢复专项](recovery/README.md)：

```cmd
python integration-tests\recovery\run.py
python integration-tests\recovery\sync.py
python integration-tests\recovery\backup.py --cjpm cjpm\target\release\bin\cjpm.exe
python integration-tests\recovery\docker_backup.py --image cjrepomesh:local --cjpm cjpm\target\release\bin\cjpm.exe
```

仓库配置类型校验有独立的 Python 标准库回归入口，使用已有 SDK 环境和增强版 cjpm；只访问临时本机 HTTP 夹具，不需要公共仓服务：

```cmd
python integration-tests\compatibility\config_validation.py --cjpm cjpm\target\release\bin\cjpm.exe
```

它覆盖错误类型在网络请求前被拒绝、TOML 日期/时间不能冒充字符串、危险 URL 与历史来源记录的凭据回显阻断、合法独占路由和旧单仓缺省配置。来源格式用例保留版本1正例，要求拒绝负数、零、未来版本及Int64极大版本号；失败时无来源成功输出、无仓库请求且原记录字节不变。

HTTP400诊断令牌遮蔽使用独立入口：

```bash
python3 integration-tests/compatibility/diagnostic_redaction.py --cjpm /path/to/enhanced/cjpm --evidence-dir /path/to/new-report
```

仅使用本机HTTP夹具、合成令牌和独立HOME/应用/缓存。实际打包后检查JSON与纯文本在索引Explain、Doctor、下载和发布中的错误输出，另以普通详情、空令牌为对照；同时核对请求真实到达对应端点、认证内容正确、状态400保留、无成功来源记录。报告保留每项日志、请求路径及脚本/二进制摘要；成功只清理本次夹具，失败保留现场。该入口不证明编码令牌或全部日志路径已脱敏。

服务端原生入口有独立 URL 矩阵，覆盖启动配置及 Mirror/Sync 的单项、清单、watcher、缓存路径：

```cmd
python integration-tests\compatibility\server_urls.py --server server\target\release\bin\main.exe
```

运行前加载匹配的 SDK/stdx 环境。96 项检查使用自建本机 Registry、唯一存储和隔离 HOME/USERPROFILE；非法输入应及时非零退出、输出不含地址值的诊断、Registry 未收到 HTTP 请求且已有存储文件不变。合法上游路径与令牌头有实际 HTTP 对照；HTTPS、IPv6 等仅检查服务启动，不当作 TLS/上游连接验收。默认服务端端口为 `39650`，可用 `--port` 覆盖，`--evidence-dir` 指定新的日志目录。成功只清理自建夹具，失败保留证据。

多仓网络回退边界另用本机 HTTP 夹具验证；默认 14 项，加 `--include-timeout` 可覆盖真实客户端读取超时，额外耗时约 60 秒：

```cmd
python integration-tests\compatibility\network_boundaries.py --cjpm cjpm\target\release\bin\cjpm.exe
```

命名仓URL变更的缓存身份另有真实包专项，使用已经构建且加载匹配SDK/stdx环境的增强客户端：

```bash
python3 integration-tests/compatibility/cache_identity.py --cjpm /path/to/enhanced/cjpm
```

六个检查点包括同名同版本、不同内容的A/B仓切换，旧名称缓存保留但不误用，切回A停服后缓存复用，冷C仓401拒绝，以及旧单仓 `home` 布局和同地址离线复用。默认使用连续三个本机端口 `39760`～`39762`，`--port`可覆盖；`--evidence-dir`只接受新目录。运行器隔离HOME/USERPROFILE、应用与共享测试缓存，成功仅清理本次夹具，失败保留现场；复用连贯场景的无宿主代理HTTP夹具。`summary.json`记录二进制/脚本摘要，来源记录和真实HTTP请求可交叉检查。旧单仓改URL隔离、完整Maple及Windows本次运行不由这个Linux记录证明。

`--retain-builds` 保留应用 `target`、锁文件和原来源记录后再换仓。历史7项修订曾在Linux通过7/7、29.64s，后来独立接收又发现增量产物失效缺口，不能把一次通过视为稳定覆盖。解析401保留原记录；依赖解析成功后故意制造编译类型错误，构建失败但来源记录仍可更新为本次解析来源，因此记录不能单独证明编译成功。

Linux可增加以下受控条件，分别执行并保存到不同的全新证据目录：

```bash
python3 integration-tests/compatibility/cache_identity.py --cjpm /path/to/enhanced/cjpm \
  --retain-builds --coarse-source-times --evidence-dir /path/to/new-source-evidence
python3 integration-tests/compatibility/cache_identity.py --cjpm /path/to/enhanced/cjpm \
  --retain-builds --coarse-artifact-times --evidence-dir /path/to/new-artifact-evidence
python3 integration-tests/compatibility/cache_identity.py --cjpm /path/to/enhanced/cjpm \
  --retain-builds --coarse-source-times --coarse-artifact-times --transitive \
  --evidence-dir /path/to/new-transitive-evidence
```

源码模式只规范真实测试CJP的tar时间戳，并同步索引SHA-256；产物模式转发给真实cjc，在成功后仅规范本次自建根目录内CJO的时间戳，不伪造编译器输出、版本或退出码。`--transitive`使用固定本地静态bridge，使应用经中间库依赖换仓的leaf；保留源码/产物前后摘要。三个选项属于合成回归控制，不修改SDK、系统时钟、真实项目或仓库。实际固定产物与结果见[验证记录](../docs/verification-report.md)。

Linux增强客户端的独立交付入口见[客户端交付说明](../deployment/client/README.md)。Python合成检查为 `python -m unittest discover -s integration-tests/deployment -p test_client_bundle.py -v`，不执行合成ELF；接收方大部分cjpm命令仍需已加载匹配SDK。

离线来源查看有独立的Linux无SDK验收：

```bash
python3 integration-tests/compatibility/recorded_without_sdk.py --cjpm /path/to/enhanced/cjpm \
  --library-path /path/to/matching/runtime/lib --evidence-dir /path/to/new-recorded-evidence
```

使用完整交付包时，`--cjpm` 指向 `run.sh`，省略 `--library-path`。入口为子进程只保留标准系统PATH和独立HOME，确认cjc不可发现，不传SDK环境；raw二进制仅提供匹配运行库路径。13项覆盖默认/组织包、只读记录、配置错误、缺失/损坏/未知格式、不安全地址、包名及在线/构建/运行仍需SDK的对照；逐项核对测试目录文件集合和字节未变，记录地址指向本机HTTP计数夹具且GET请求数须为0。它只验证读取记录，不把记录当成真实构建证明；当前Windows仓颉未执行。

`cjpm run` 的失败状态另有八项真实程序回归：

```bash
python3 integration-tests/compatibility/run_exit_status.py --cjpm /path/to/enhanced/cjpm \
  --evidence-dir /path/to/new-run-status-evidence
```

已有SDK环境下，入口创建独立含空格应用目录、HOME和无依赖项目，先直接执行真实应用确认退出7，再检查普通/跳过构建运行、旧参数、分隔符优先级、带空格与help参数、产物缺失及编译失败不运行旧应用。修复契约是应用非零映射cjpm退出1，成功0，不是精确保留子进程退出码；应用失败时不得显示 `cjpm run finished`。成功只清理本次目录，失败保留现场，日志和摘要写入新证据目录；Windows仓颉尚未运行，当前实测范围见验证记录。

Windows 部署脚本的隔离回归见 [部署测试说明](deployment/README.md)。

两个已有Linux服务镜像间的停服快照、候选新卷及回退演练见[升级与回滚专项](recovery/README.md#stopped-volume-upgrade-and-rollback)。该入口只创建隔离卷，不接受业务卷名；不以健康检查替代真实包摘要和恢复边界检查。

离线服务端交付包另有接收端验证，不运行Windows仓颉程序：

接收工具合成回归现为12项，Linux完整执行；Windows无链接权限时3项跳过并明确记账。覆盖链接校验器/初始化器跨目录定位及制作端悬空输出路径拒绝，制作端拒绝测试不访问Docker。Windows宿主真实接收可在只有Python和已可发现的Docker Compose插件、无SDK的环境执行；仍是已有引擎上的目录隔离，不等同全新主机。

```cmd
python integration-tests\deployment\test_portable_bundle.py
python integration-tests\deployment\portable.py --bundle <未初始化交付目录> --package-dir <已有真实CJP及meta-data.json目录> --evidence-dir <新的证据目录>
```

第一项验证清单、损坏拒绝、凭据保护和初始化不覆盖；第二项需要Docker，复制交付目录到隔离接收副本，检查镜像导入、覆盖文件隔离、缺失令牌拒启、私有读写、真实CJP发布读取和容器重建持久化。结束仅清理匹配随机项目与发行标签的本次容器/卷，失败日志和本地接收副本保留；原交付目录不初始化，不写入凭据。此项不是消费端构建、全新主机或内网HTTPS验收。

含新运行态诊断器的服务端包可加 `--check-running`，在原12项上增加未启动拒绝、运行实例通过、停服拒绝及重建后通过，共16项。验收器有界等待Docker健康状态，不仅等待HTTP就绪；产品诊断仍严格检查healthy，不为测试放宽。`python integration-tests/deployment/test_portable_runtime.py`另验证元数据身份/权限拒绝及自有回环HTTP跳转和错误正文处理，不实际创建高权限或对外暴露容器。

更新后的完整包还可同时加 `--check-credential-drift`，共18项：仅在本次合成安装修改.env的读/发布令牌，确认未重建时诊断拒绝而旧令牌仍可用；测试重建后新令牌可用、旧令牌401，再恢复原合成配置。诊断本身只读解析Compose有效环境和比对运行值，不能把它的配置一致性结论当作真实鉴权。该选项依赖 `--check-running`，不操作任何现有业务配置；原16项入口保留。

[开发者与只读CI示例](../examples/team/README.md)另有准备器回归与可选真实Linux任务验证：

```cmd
python integration-tests\deployment\test_team_example.py
python integration-tests\deployment\test_team_delivery.py
python integration-tests\deployment\portable.py --bundle <未初始化交付目录> --package-dir <已有真实CJP目录> --team-sdk <已有LinuxSDK目录> --team-client <已有Linux增强版cjpm文件> --team-native <已有本机归档链接工具副本目录> --evidence-dir <新的证据目录>
```

`--team-sdk`与`--team-client`须同时指定；SDK需含cjlint。`--team-native`为可选只读工具挂载：`bin/`放ar和ld，`lib/`放它们所需库，`system/`按原绝对路径保存GCC和系统启动/链接输入。它只解决最小服务端运行镜像缺少构建工具的问题，不能把跨系统ABI不匹配的工具任意混用；正式自托管任务机应预先具备完整匹配工具链。本入口不安装或下载工具。

服务端出站跳转专项在已有Linux环境运行：`python3 integration-tests/compatibility/server_redirects.py --server <已有Linux服务端> --package-dir <已有真实默认组织CJP及meta-data.json目录> --evidence-dir <新证据目录>`。12项使用自有回环夹具，覆盖Proxy/Mirror/Sync三个正常直连以及九个源/目标索引302、制品307和发布307拒绝；核对指定路径到达、跳转目标零请求、完整发布帧和失败存储保持。Sync发布正向只验证协议帧，真实目的端存储由核心Sync组另行验证；不覆盖TLS/跨主机或Windows。

服务端TCP建连专项：`python3 integration-tests/compatibility/server_connect_timeout.py --server <已有Linux服务端> --package-dir <同上真实CJP目录> --evidence-dir <新证据目录>`。14项以自有IPv4回环监听队列饱和模拟建连停滞，不修改防火墙、不访问外部黑洞；设2秒，要求驱动4秒前返回失败且不写存储，包含Proxy同实例同包恢复、Mirror/Sync读取/目的仓预检和独立发布连接。发布夹具先停止接收并饱和、再返回404，必须确认源索引和制品均到达，避免只测到GET预检。另测六项非法配置无HTTP、三个正常直连（省略变量/1/300）；`--case blocked-sync-publish`可单测发布。运行前加载匹配SDK/stdx；拒绝Windows原生执行。默认30秒的停滞、DNS、TLS、慢读写及整体操作总时限均未验收，实际产物和各版本脚本结果见[验证记录](../docs/verification-report.md)。

TTL告警专项：`python3 integration-tests/compatibility/server_proxy_ttl.py --server <已有Linux服务端> --evidence-dir <新私有证据目录>`。五项覆盖默认、合法0、负数、非数字合成值及Int64溢出；核对启动行实际TTL、保留的默认兜底警告及原值不回显。使用本机随机端口、隔离HOME/存储和私有PTY避免stdout缓冲影响观察，仅停止本次Popen；断言使用原始内存输出，落盘前替换合成非法值。它只检查启动/告警，不验证TTL到期或上游取包，不使用真实凭据，不执行Windows仓颉。

服务端HTTPS专项：`python3 integration-tests/compatibility/server_tls_identity.py --server <Linux服务端> --package-dir <同上真实CJP目录> --evidence-dir <新证据目录>`。已有Linux OpenSSL生成合成CA/证书，0700临时目录退出清除；CA只给子进程，不改系统信任。当前24项保留原18项合法HTTPS、未知CA、错误DNS/IP/用途及后阶段连接身份检查，另加Mirror DNS/IP、Proxy IP、Sync源制品/目标索引/发布的六项过期叶证书拒绝。过期夹具先由OpenSSL确认error10，再要求目标实际握手收到certificate_expired告警；不能仅凭非零退出/502和零HTTP判通过。精确HTTP到达阶段、真实CJP/发布帧、认证及文件保持仍检查。需加载匹配SDK/stdx，不执行Windows仓颉；Sync夹具不提供真实持久化，真实目的仓由核心Sync组另验。镜像内复验另需既有Python/OpenSSL测试工具，不装入服务镜像；不将本机夹具称为成熟网关、跨主机或标准Compose CA验收，也未覆盖未来生效、过期根、吊销和改钟。

声明CA能力的完整服务端包可用 `python integration-tests/deployment/portable_ca.py --bundle <尚未初始化的新包> --package-dir <已有真实默认CJP目录> --native <已有Linux Python及lib工具目录> --openssl <已有Linux OpenSSL可执行文件> --evidence-dir <新证据目录>`。先按包说明加载固定镜像；脚本不拉取/构建镜像，不需SDK。10项在自建Compose项目验证CA导入、只读挂载与实际摘要、错误DNS证书/无令牌拒绝、同代理恢复后真实HTTPS取包、CA篡改诊断、上游离线缓存和重建保持；TLS夹具仅共享本次服务的网络命名空间，工具只读挂给夹具，不挂给服务。结束清理自建容器/卷和合成私钥，证据目录保留；不测试真实CA分发、原部署轮换、入站网关或跨主机。

接收工具的Python回归可用 `python -m unittest discover -s integration-tests/deployment -p "test_portable*.py"`，当前共65项：新旧包校验/初始化、运行诊断、CA，以及维护归档/配置/卷拒绝、辅助容器失败保留和日志解码。无需Docker或仓颉；健康诊断两项需要本机回环权限，不能把沙箱连接拒绝改成跳过或弱化断言。Windows链接权限不足时有4项跳过，Linux实际65项全过，具体记录见[验证报告](../docs/verification-report.md)。

新八文件维护包的完整恢复验收复用同一入口，在上述CA命令上增加 `--cold-restore --maintenance --hosted-package-dir <已有真实company::teamhello-1.0.0的CJP及meta-data.json目录> --client-bundle <完整当前Linux客户端目录> --client-sdk <已有LinuxSDK目录>`。默认CJP须为meshdep，标记默认期望 `high-1.0.0`，可用 `--expected-output` 明确覆盖。21项实际调用包内维护工具，覆盖真实内部包发布/只读发布401/重复409、原服务与其他运行写入者阻断、停服备份、损坏/已有配置/错误镜像拒绝、新卷恢复、独立两包基线空缓存构建与漂移拒绝、原件及重建保持。批准记录来自冻结的两个制品元数据，不使用本次消费输出自动批准；只读挂载到任务外部。此入口仍只操作其新建合成安装，真实部署使用[维护工具](../deployment/portable/README.md#接收端停服备份与独立恢复)。

maintenance验收失败时尝试停止本次写入实例、保留失败卷和证据，不删除业务或其他项目资源；成功只清理本次创建的资源。容器日志使用UTF-8及替换解码，收集日志失败也继续尝试安全停服。不要把这一个双包图推算成多图脚本、完整官方测试、生产切流、入站HTTPS或全新主机通过。

对带 `restorePreflight=offline-inputs-v1` 的新包，在上述维护命令中再加 `--restore-preflight`，由21项扩为23项。它先移除子进程PATH中的Docker搜索路径执行 `maintenance.py restore --check-only`，核对默认/显式端口的JSON结果及目标文件原字节；再验证非法端口、已有restore.json在预检和正式恢复前拒绝且不改配置/卷，随后继续原有实际恢复和受保护双包冷构建。该选项要求maintenance及新能力标记，在证据创建前拒绝不兼容参数/包。操作人员的独立预检命令及含义见[维护说明](../deployment/portable/README.md#接收端停服备份与独立恢复)，预检不证明Docker镜像已导入、资源可用或实际恢复已成功。

验证实际交付组合时，将 `--team-client <文件>` 换成 `--team-client-bundle <完整客户端交付目录>`，两者互斥且均须搭配SDK。新模式在创建证据目录/访问Docker前用源码仓库的可信校验器检查包，不执行待测包中的Python代码；任务只读挂载整个目录，通过包内run.sh执行。摘要记录实际二进制和清单SHA-256，结束再次检查包不变，共21项。启动器需容器内已有Python 3；可在任务专用的 `--team-native` 目录下提供已有 `bin/python3`、对应 `lib/python3.X` 标准库及匹配共享库，不向最小服务端镜像安装工具。应先在相同只读挂载条件下运行包的 `--help` 检查依赖。六项离线回归只验证预检和参数拒绝，不代替真实编译。

完整客户端模式还可加 `--team-protected`，在原21项上增加独立批准和SHA漂移拒绝，共23项；它要求 `--team-client-bundle`及SDK，不接受原始单文件客户端。参数不完整或包校验失败在创建证据/访问Docker前拒绝。批准仅根据本次受控发布任务的company::teamhello 1.0.0元数据及实际CJP字节建立，先核对包身份和SHA，不读取消费provenance；它是验收夹具，不是为真实远端解析结果自动批准的工具。

所有消费任务把批准从任务可写目录之外只读挂载到 `/approved/source.json`，再由现有脚本确认基线能力。两个正确冷任务核对完整provenance并真实运行检查应用没有示例读写令牌；另一独立空缓存任务使用SHA漂移批准，必须明确拒绝且没有应用/provenance。失败应用仍须返回7，错误读取及读取令牌发布仍须拒绝，最后核对批准原字节和完整客户端保持。若完整包没有基线能力，任务会失败，不会静默降级。

同时检查运行态和合成凭据生效时，完整组合为29项，可复用已安装的Linux工具：

```cmd
python integration-tests\deployment\portable.py --bundle <未初始化服务端交付目录> --package-dir <已有真实CJP目录> --team-sdk <已有LinuxSDK目录> --team-client-bundle <完整客户端交付目录> --team-native <已有Linux工具副本目录> --team-protected --check-running --check-credential-drift --evidence-dir <新的私有证据目录>
```

该命令只创建自己的合成实例与凭据，不接入现有业务部署；默认模式和完整客户端原21项入口保留。证据目录含合成凭据和内部材料，勿提交到公开仓库。此流程使用本机Docker内部HTTP，不是HTTPS/跨主机、共享缓存、容量、沙箱或完整来源基线矩阵验收。

可选模式在原12项上增加8项，共20项：无凭据准备目录、真实构建发布、只读CI编译运行、第二个独立冷任务、应用运行失败退出码、错误读取令牌、读取令牌越权发布拒绝，以及失败后制品和服务凭据保持。SDK/客户端只读挂载，任务通过本次内部Docker网络访问服务，主机仍仅本机监听。两次成功消费核对同一包的实际来源和SHA-256；失败应用仍可能有解析记录，但不得继续解释或返回成功。这不替代Windows仓颉、全新主机、内网HTTPS或完整官方验收。

在 Linux 上准备同一源码基线的官方原版 cjpm 后，可比较旧单仓配置的直接与传递依赖版本、冲突、锁文件转换、依赖树与缓存，并运行本地官方 HTTP 状态 LLT 夹具：

```bash
python3 integration-tests/compatibility/run.py \
  --official-cjpm /path/to/official/cjpm/dist/cjpm \
  --enhanced-cjpm /path/to/CjRepoMesh/cjpm/dist/cjpm \
  --official-fixture /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/repository/coverage/http_status_matrix
```

原版构建与测试范围、实际结果见 `docs/official-compatibility-report.md`。本入口不代替完整 Maple HLT/LLT。

HTTPS名称与IP SAN的Linux真实客户端回归另见[客户端HTTPS说明](../docs/https-client.md#可复验验证)。15项使用已有OpenSSL、SDK及真实组织CJP，在本机合成CA夹具中核对身份、401、实际下载构建，以及302索引和307发布/下载不自动跳转；不安装系统根证书、不运行Windows仓颉，也不等同于真实反向代理部署。

## 按批准集合制作依赖快照

接收者操作见[交付包快照说明](../deployment/portable/README.md#按批准集合制作依赖快照)。九文件包支持从停服备份按独立批准集合导出、离线校验和新卷导入；客户端/服务端二进制不变。单来源export保留快照v1；`approved-origins-v2` 新包还支持[按原URL分别封存的完整集合](../deployment/portable/README.md#多来源依赖快照集合)，不合并仓库存储或改写目标地址，不替代完整仓库备份。

相关纯Python回归另行运行：

```console
python -m unittest discover -s integration-tests/deployment -p test_dependency_snapshot.py -v
```

真实完整包验收在Windows宿主编排Linux容器，复用已加载镜像、已有Linux SDK和Python/native工具，不执行Windows仓颉。四个输入目录分别包含 `meta-data.json` 和真实CJP：meshdep 1.0.0/2.0.0、company::baselineparent 1.0.0（依赖meshdep）及无关company::teamhello 1.0.0。标记要求为 `baseline:high-1.0.0`。在新证据目录执行：

```console
python integration-tests/deployment/dependency_snapshot.py --bundle <未配置的完整新服务端包> --client-bundle <当前完整Linux客户端包> --client-sdk <已有LinuxSDK目录> --native <已有LinuxPython和链接工具目录> --package-dir <meshdep1目录> --package-dir <meshdep2目录> --package-dir <baselineparent目录> --package-dir <teamhello目录> --evidence-dir <新证据目录>
```

12项覆盖真实发布和停服备份、精确子集及单版本索引、缺失传递依赖、损坏/独立批准漂移拒绝、新配置/新卷seed和重复拒绝、原服务离线后的内部网络空缓存编译运行、匿名读取拒绝、无关包/版本不可读、另一个冷任务的来源漂移拒绝与重建保持。批准集合由冻结真实元数据独立构造，外部只读挂载，不从消费输出自动批准。目标仓及消费者仅接同一自建内部网络，以受控别名保持原URL；SDK/客户端/链接工具只读提供。该网络约束不是完整宿主气隙、任意迁移或所有外部构建输入的离线证明。

仅清理本次随机项目与带本次标签的容器/网络；失败时保留数据卷、配置和输出，成功保留归档及摘要证据。接收工具沿用维护窗口与失败辅助容器诊断规则，不接收业务卷名。已有CA/维护21项及官方/Windows仓颉矩阵不计为本入口重跑。

多来源验收复用同一入口，在上述命令增加 `--multi-origin --alternate-package-dir <另一份真实meshdep1目录> --legacy-bundle <真实旧approved-set-v1完整包>`。另一个meshdep1须与主输入同名同版本、实际CJP摘要不同；两个CJP均须匹配各自冻结的真实索引。旧包必须未配置且保持完整清单，脚本不会改写旧包。

该模式16项使用两个源仓的真实停服备份，parent来自internal、meshdep来自home，并让另一来源保存同名同版本的不同字节作为负对照。它校验集合完整性和来源分区、交换备份在输出前拒绝、重算清单的缺来源拒绝、真实旧v1工具校验新v1导出并拒绝v2分片；分别seed两个新卷，原源仓停止后，用完整独立批准图实际冷构建/运行跨仓应用，另做SHA漂移与同一服务URL别名漂移拒绝，最后核对双实例重建与原件保持。两个接收服务和消费任务只接同一自建内部网络；完整批准外部只读挂载。单来源默认12项与此16项属于不同模式，不把历史12项或旧包结果冒称新一轮重跑。

当前快照专项26项在Windows和Linux均通过；Linux使用已有镜像及只读Python/native工具、tmpfs和无外网容器，覆盖旧单来源、备份内部输出污染拒绝、多来源边界及创建成功后的日志故障。验收器在Docker网络/消费者创建返回0后先登记资源，再记录日志；记录失败仍核对proof标签并清理，故障数据卷保留，整体任务仍失败。真实网络/消费者两处日志故障注入及修复后正常多来源16项均已单独验证；创建结果未知、超时或进程被硬杀后的恢复不在该保证内。相关既有65项保留上一批独立记录，本轮未重跑；不执行Windows仓颉或安装工具。

## 可选仓库来源基线

使用已有Linux SDK/stdx、增强客户端和真实meshdep1.0.0包目录（包含meta-data.json与CJP），不运行Windows仓颉：

```bash
python3 integration-tests/compatibility/source_baseline.py \
  --cjpm /path/to/enhanced/cjpm \
  --package-dir /path/to/real-meshdep-package \
  --evidence-dir /path/to/new-baseline-evidence
```

入口要求新的证据目录，启动本机合成仓，真实构建parent→meshdep及消费应用；核对最终传递来源、匹配/顺序/替换、字段漂移、空图/热缓存、类型/大小/路径错误，以及拒绝时零制品请求、旧来源输出和批准文件保持。`--case <名称>` 可重复指定定向检查，始终保留未启用控制；目录内保存摘要及原始日志，按内部材料保管。此项不验证多图脚本接入、签名、已解包缓存真实性、Git/本地输入或脚本沙箱。用法和边界见[CI来源基线](../docs/repository-source-baseline.md)。

## 官方 Maple 框架选定用例对照

准备独立检出的官方 `cangjie_test_framework`、`cangjie_test`，以及同一源码基线的原版与增强版 Linux cjpm。加载 SDK 与 stdx 后运行：

```bash
python3 integration-tests/compatibility/maple_smoke.py \
  --framework /path/to/cangjie_test_framework \
  --fixture /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/repository/coverage/http_status_matrix \
  --config-suite /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/config/coverage \
  --install-coverage /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/install/coverage \
  --install-local-suite /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/install/local \
  --uninstall-suite /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/uninstall \
  --update-wrong-config /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/update/wrong_config \
  --update-coverage /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/update/coverage \
  --archive-fixture /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/install/coverage/repository_archive_matrix \
  --test-config /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/test.cfg \
  --official-cjpm /path/to/official/cjpm \
  --enhanced-cjpm /path/to/enhanced/cjpm \
  --results-dir /path/to/test-results
```

入口仅在临时副本中规范 HTTP 状态与本地索引刷新用例的 `.sh`、`.toml`、`.cj` 行尾；刷新脚本另以最多5秒的真实端口就绪等待替代固定sleep1，失败保留服务启动输出。原服务、cjpm命令与ASSERT不变，官方Git跟踪文件不变。Maple 对官方 HTTP 状态、三个配置、五个安装覆盖、十七个本地安装、四个卸载、两个更新错误配置和七个更新覆盖用例，共三十九个选定用例分别运行两版cjpm，其中38项原断言和1项就绪调整分别记账，要求各调用均PASS；实际当前候选及历史两版结果以验证记录为准。每次调用均隔离 `HOME`、`USERPROFILE`，并移除调用者的 `CJPM_CONFIG`；本地安装、卸载和新增更新用例还把其 `.cjpm/bin` 加入测试进程的 `PATH`，使安装命令可被后续断言找到。本地索引刷新只访问 `127.0.0.1:39138`，入口检查测试端口释放。另外运行 `repository_archive_matrix`：它原样试跑会因官方夹具动态 gzip 时间戳偶发哈希不一致，入口只在测试副本中固定 gzip mtime 为 0，再要求两版各 `1/1 PASS`。结果日志、刷新脚本就绪调整及原始/稳定化服务摘要保存在唯一的 `--results-dir/run-*` 中。就绪调整项和稳定化矩阵均不能表述为未经调整的官方用例通过；该入口也不代表完整 HLT/LLT。

另有 `integration-tests/compatibility/maple_local_bundle.py` 专门运行官方 `LLT/Tools/cjpm/CJNATIVE/repo/bundle` 下的 23 个本地打包用例。它先检查用例数量及命令未变，再逐例以隔离 `HOME` 对照原版和增强版，并将 46 份日志写到指定 `--results-dir`；不运行外部发布用例。参数为 `--framework`、`--bundle-suite`、`--test-config`、`--official-cjpm`、`--enhanced-cjpm`、`--results-dir`，路径含义与上述入口一致。

同一入口可加 `--level HLT`，将 `--bundle-suite` 指向官方 `HLT/Tools/cjpm/repo/bundle`，其余工具参数仍使用官方 Linux cjpm 测试配置。当前快照先核对该目录共 101 个用例，从中选择 95 个离线打包用例；排除含条件 `(not Windows)EXEC:` 而未纳入无条件EXEC选择的 `bundle_build_03/04/06`、单独生成二进制夹具的 `bundle_include_23/28`、含依赖查找的 `bundle_verify_03`。入口执行前检查所选命令和 TOML，拒绝远程地址、Git 仓库与依赖查找，不执行 HLT 的发布、下载或在线索引用例。每次运行保存 `selection.json`，包含级别、选择/排除清单、用例、配置及两版二进制摘要。95 个用例仅是 HLT bundle 离线子集，实际结果以日志为准，不等同于完整 HLT。

同样可用 `maple_local_tree.py --tree-suite <官方 CJNATIVE/tree 目录>` 和 `maple_local_organization.py --organization-suite <官方 CJNATIVE/organization 目录>` 运行 17 个本地依赖树及 12 个本地组织名用例；其余参数与打包入口相同。三个入口分别检查用例数和执行命令，组织名入口还拒绝非本地依赖。它们只验证 cjpm 本地行为；Hosted 组织仓发布、解析和私有读取另由 `hosted-server/org-package`、`org-app`、`org-private-app` 夹具验证，Proxy 组织仓拉包和离线缓存由 `proxy/org-app` 验证，Mirror/Sync 组织仓由 `sync/org-manifest.txt` 与 `sync/org-app` 验证，不等同于完整 Maple。

`maple_local_workspace.py --workspace-suite <官方 CJNATIVE/workspace 目录>` 对照运行 52 个本地 workspace 用例；其他参数与上述入口相同。入口先核对用例数量、执行命令与配置文件，拒绝外部 URL/发布操作；每例在隔离临时 `HOME` 下分别以原版和增强版运行。它只覆盖 workspace 子集，不代表完整官方 HLT/LLT。

```bash
python3 integration-tests/compatibility/maple_local_workspace.py \
  --framework /path/to/cangjie_test_framework \
  --workspace-suite /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/workspace \
  --test-config /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/test.cfg \
  --official-cjpm /path/to/official/cjpm \
  --enhanced-cjpm /path/to/enhanced/cjpm \
  --results-dir /path/to/test-runs/maple-workspace
```

脚本遇到子测试抛出的第一处失败即停止，全部通过后打印每组耗时汇总。部分安全测试会故意执行应当失败的客户端命令，因此统一入口以测试断言结果而不是最后一个原生命令的退出码判断整组状态。Proxy 性能测试不纳入功能回归，需独立运行：

```powershell
.\benchmark\proxy\run.ps1
```

## 基线能力查询与消费任务预检

```bash
python3 integration-tests/compatibility/baseline_capability.py \
  --cjpm /path/to/current/cjpm \
  --old-cjpm /path/to/existing/8da5/cjpm \
  --evidence-dir /path/to/new-capability-evidence
```

仅运行Linux客户端；入口为各例隔离HOME/目录，移除SDK环境及编译器PATH，并创建只记录请求的本机HTTP夹具。核对精确能力查询、损坏配置/脚本、未知/帮助标记、额外参数和原在线SDK边界；stdout与stderr分开判断，隐私检查覆盖两者。消费脚本的异常退出、空/错/额外stdout、显式空值及未配置/支持控制使用自有合成客户端，另有实际旧客户端拒绝；这些协议控制不冒充真实CJP构建。

真实完整新包的发布、消费、冷CI基线匹配/漂移及旧客户端构建前拒绝另在[验证记录](../docs/verification-report.md)记账。能力是兼容性自报，不认证二进制；所有日志和合成材料留在新的本地证据目录。

## 来源基线多图兼容性

使用与单图专项相同的固定Linux客户端、已有SDK/stdx和真实meshdep包目录：

```bash
python3 integration-tests/compatibility/source_baseline_graphs.py \
  --cjpm /path/to/enhanced/cjpm \
  --package-dir /path/to/real-meshdep-package \
  --evidence-dir /path/to/new-graph-evidence
```

入口使用新目录、每例独立HOME/缓存和本机HTTP合成仓，真实打包parent→meshdep，构建两个工作空间成员及带独立依赖的build.cj。核对整图/成员子集、同图/异图脚本、绝对/相对基线路径、pre/post执行标记、真实应用输出、制品请求及来源/批准文件。新增显式脚本批准覆盖分图成功、两图分别失配、脚本变量缺失/非法/为空/缺主批准、未选中批准与最终/临时输出冲突，以及主图不被脚本批准替代。`--case <名称>` 可重复指定定向用例；摘要标明实际执行数量，未知名称使运行失败。

不同图不能靠批准集合取并集通过；主图拒绝前，已批准脚本图可能已经执行、下载并写入来源输出。该测试验证每图边界，不提供整命令原子拒绝、脚本沙箱、嵌套Git/本地脚本或增量脚本缓存保证。完整使用边界见[CI来源基线](../docs/repository-source-baseline.md)，原始日志与合成材料留在本地证据目录。

## Docker 私有仓持久化专项

先通过 `deployment/docker/up.ps1` 构建当前服务端镜像，然后在 Windows 上运行：

```powershell
python integration-tests/docker_persistence.py
```

脚本使用随机命名的独立 Compose 项目、端口、发布/读取令牌和命名卷，不修改正在运行的主项目容器或其数据。它验证无令牌读取/发布均为 401、授权发布后索引和制品可读、强制重建容器后数据及 SHA-256 保留、重复发布仍为 409；结束时只清理该测试项目及其卷。制品是合成字节，仅用于验证服务端协议和持久化，不替代真实 cjpm 打包/安装端到端测试。

共享运行器不包含 Windows 部署或 Docker Compose：前者由 `integration-tests/deployment/run.ps1` 验证，Docker 健康/安全项由 `deployment/docker/doctor.ps1` 验证，持久化专项由上面的独立脚本验证。完整官方 Maple HLT/LLT 也不属于这些入口。
