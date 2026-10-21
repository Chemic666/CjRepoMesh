# CjRepoMesh 端到端验证

四组核心测试由同一个 Python 标准库运行器编排，Windows 与 Linux 共用夹具、断言、安全边界和清理逻辑；PowerShell 与 Bash 仅负责加载平台环境。Windows 一键部署是平台专属的第五组。

如果希望先理解完整使用场景，见[连贯企业依赖演练](showcase/README.md)。一个入口串起同名公共高版本对照、私有命名空间保护、错误令牌阻断、上游停服、私有副本与离线来源解释，使用真实包和全新客户端缓存。它不替代四组回归或官方测试。

固定客户端、服务端、交付包及同一产物的新执行/引用证据集中在[固定候选验收清单](../docs/candidate-acceptance.md)，其中仍未验收项单独列出。

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

[开发者与只读CI示例](../examples/team/README.md)另有准备器回归与可选真实Linux任务验证：

```cmd
python integration-tests\deployment\test_team_example.py
python integration-tests\deployment\portable.py --bundle <未初始化交付目录> --package-dir <已有真实CJP目录> --team-sdk <已有LinuxSDK目录> --team-client <已有Linux增强版cjpm文件> --team-native <已有本机归档链接工具副本目录> --evidence-dir <新的证据目录>
```

`--team-sdk`与`--team-client`须同时指定；SDK需含cjlint。`--team-native`为可选只读工具挂载：`bin/`放ar和ld，`lib/`放它们所需库，`system/`按原绝对路径保存GCC和系统启动/链接输入。它只解决最小服务端运行镜像缺少构建工具的问题，不能把跨系统ABI不匹配的工具任意混用；正式自托管任务机应预先具备完整匹配工具链。本入口不安装或下载工具。

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

## Docker 私有仓持久化专项

先通过 `deployment/docker/up.ps1` 构建当前服务端镜像，然后在 Windows 上运行：

```powershell
python integration-tests/docker_persistence.py
```

脚本使用随机命名的独立 Compose 项目、端口、发布/读取令牌和命名卷，不修改正在运行的主项目容器或其数据。它验证无令牌读取/发布均为 401、授权发布后索引和制品可读、强制重建容器后数据及 SHA-256 保留、重复发布仍为 409；结束时只清理该测试项目及其卷。制品是合成字节，仅用于验证服务端协议和持久化，不替代真实 cjpm 打包/安装端到端测试。

共享运行器不包含 Windows 部署或 Docker Compose：前者由 `integration-tests/deployment/run.ps1` 验证，Docker 健康/安全项由 `deployment/docker/doctor.ps1` 验证，持久化专项由上面的独立脚本验证。完整官方 Maple HLT/LLT 也不属于这些入口。
