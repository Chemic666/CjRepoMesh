# CjRepoMesh 验证记录与范围

> 本批代码已于 2026-10-21 完成授权提交与双端推送，见[交付记录](delivery-record.md)。下文“尚未 Commit/Push”为各次验证时点的历史状态，不代表当前发布状态；后续纯文档更新不改变已验证产品与测试脚本。

> 最近执行日期：2026-10-21
> 包含多批产物；最新服务端见首节，各历史节的“当前”只指该节产物，不将旧结果视为新二进制的重新验收。
> 历史基线：Windows 五组 `8e33119`；早期 Linux 四组与 Docker 复核 `e5be054`
> 历史结论（2026-09-26）：在本地交付材料提交 `98e9f849` 上，从 Windows 工作区挂载路径真实重编译服务端并运行 Linux 四组，4/4 PASS、252.01 秒，随后 Docker Doctor 9/9。当时 Windows 原生构建被 Application Control 阻断；该限制不代表 2026-10-20 的实际环境。历史远端 HEAD、视频及 Maple 子集记录见各日期章节，不作为当前远端或最终产物的验收声明。

## 2026-10-21 最新 Linux 恢复与 Docker 产物对齐

在下节共享目录竞争修复后的同一 Linux Server（SHA-256 `1cea8eff24169a32695d2071518ac3184ad7f2c7e7fbbf3fa9186d27ec10b513`）上，文件存储冷备份恢复 **10/10 PASS，27 秒**。耗时由 Bash 整秒计时，不与前节精度为小数的记录混用。实际核对停服前后文件集合和摘要、损坏及缺失备份拒绝、不同目录恢复、默认/组织包全新缓存构建、重复版本拒绝、新版本发布及再次重启；原件和备份不变。没有运行 Windows 仓颉程序或更改其安全设置。

Docker Desktop 启动后，仅使用本地已有候选运行时镜像，将上述 Linux Server 放入独立 `cjrepomesh:delivery-20261021`，未覆盖默认镜像、正式配置或已有卷。新镜像 ID 为 `sha256:7d5a905a74d8286802ce7ad87d818f7421e238a2e2cc961a03cdc2dcf6119805`。构建前后均核对基础镜像 ID `sha256:fc24453eb2a0212439ec21099adf56656b38644f62e180b35e520bf137fe0fef`，运行中二进制摘要与 Linux Server 一致。

- 两种非法上游地址（内嵌凭据、单斜杠）在容器内退出 2，诊断不回显测试凭据；
- 项目现有部署脚本中的 Docker Doctor **9/9 PASS**；
- 独立 Compose 项目验证私有读取、组织隔离、授权发布、重建后索引/制品字节及摘要保留、重复发布 409，结束只回收本次自建项目和卷。

Docker 持久化检查沿用 `integration-tests/docker_persistence.py` 的合成字节探针，**不是实际 cjpm 构建**；本次真实包恢复与构建在上面的 Linux 文件目录演练完成。没有复跑此前 Docker 新卷冷备份 9/9，不把旧结果算到新镜像上。

首次镜像构建脚本将本地 image ID 写进 FROM，BuildKit 将其解释为仓库名，元数据查找被拒绝；未成功下载镜像层。纠正为先核对已有本地标签的 ID、使用该标签并在构建后再次核对；成功构建设置 `--pull=false --network=none`。失败日志保留，没有弱化产品断言或修改部署源码。

证据位于外层 `test-runs/delivery-20261021/`：`linux-backup.log`、`linux-inputs-sha256.txt`、`linux-backup-details/`、`docker-image.json`、`docker-build.log`、`docker-doctor.log`、`docker-run.log`、运行中二进制摘要及两份首次失败日志。产物、脚本和结果汇总另存 `verified-results.json`。本次只补充当前产物验收及文档，不新增备份系统，也没有 Commit/Push。

## 2026-10-21 连贯场景与共享父目录竞争修复

新增 `integration-tests/showcase/run.py`，把独占路由、认证阻断、Proxy 离线缓存、私有副本和离线来源解释串成同一条流程。五份真实包由已有增强版 cjpm 打包并核对归档摘要；每个消费者使用新目录、本地配置、独立缓存、无 lockfile 和无构建产物，HOME/USERPROFILE 也为测试专用。Python 的本机 HTTP 不读取宿主代理配置。

首次 Windows 演练在冷 Proxy 下载两个不同组织的包时失败；第二次保留的网关 502 响应明确包含递归建目录 `File exists`。原来不同包各持自己的包锁，但共享祖先目录的 `exists` / recursive mkdir 没有共同保护。修复将 `ensureParent` 移入 `storage.cj`，用一个短时进程内锁保护目录创建；审查又补齐 Hosted 首次发布的两处直接 mkdir。下载与文件写入仍不占目录锁，包锁与目录锁的获取顺序固定；不支持多个服务进程共用同一存储。

| 最终连贯演练 | 检查点 | 墙钟耗时 |
| --- | ---: | ---: |
| Windows | **7/7 PASS** | 26.27s |
| Linux | **7/7 PASS** | 42.66s |

共享目录辅助函数影响 Hosted、Proxy 与 Mirror/Sync，最终产物的相关三组回归另行执行：

| 回归 | Windows | Linux |
| --- | ---: | ---: |
| Hosted | PASS 20.55s | PASS 30.74s |
| Proxy（含不同包不等待慢上游） | PASS 21.84s | PASS 32.26s |
| Mirror / Sync（含组织与 watcher） | PASS 14.30s | PASS 15.55s |
| 三组总计 | **3/3，56.78s** | **3/3，78.57s** |

七项分别是无路由对照、独占保护、错误令牌、上游停服、同步副本、副本独立构建、所有仓停止后 recorded explain。对照使用**同一个增强客户端**，不是官方原版差分。保护阶段审计公共网关（包括 Proxy 缓存命中路径），断言没有内部命名空间请求；401 阶段公共入口请求数不变。Sync 的两个源包第一次为 SYNCED、重复为 SKIP，目标匿名读取 401、授权读取逐字节匹配。最后明确停止所有五个服务端口，核对 explain 的包名、版本、仓库、地址和摘要，并确认来源文件未改写。准备阶段并发发布两个组织的真实包，冷 Proxy 首次构建并行拉取两包。

| 本次产物 | SHA-256 |
| --- | --- |
| Windows cjpm（未改） | `20f3ce0c534c981a755388bc5b4b73e79e9e07a83d76336391130fb10570355d` |
| Windows Server（新建） | `533158e00bdd391b708564aa11927f6b08a8114f82431eab7542fa9c45b308fe` |
| Linux cjpm（未改） | `7e29eaa7e02885ba6d9ae998a6d2787170db5b17b28741bb61d613e02b330abf` |
| Linux Server（新建） | `1cea8eff24169a32695d2071518ac3184ad7f2c7e7fbbf3fa9186d27ec10b513` |
| 两平台相同演练脚本 | `96fb41e400a0716205fef32ad9df627674911e196d7cb85ac293c9e506e11b66` |

固定 140 份服务端/测试文件后，在全新 Linux 验证目录逐份核对摘要再构建；`source.tar` SHA-256 为 `265738cb4bb25356c69db04ab1fc3153879cfa1319219910222c74c2928eedcb`。说明文档随后补充，但运行器和产品源码保持该批固定内容；归档内说明文档的变化另存摘要。证据在外层 `test-runs/enterprise-showcase-20261021/`：两个早期 Windows 失败目录、`windows-final/` 与 `linux-final/` 的输入/归档摘要、逐阶段结果、原始命令及 HTTP 请求日志，另有两平台构建与相关回归输出。原始日志、失败 JSON 可能含本机路径，公开前需审阅。

Windows 运行结束后，参赛者报告安全中心反复询问是否允许 `std.testrunner.exe`。当前没有取得完整提示/路径，也未找到可匹配的 Defender/Code Integrity 事件，原因仍未核实；未将文件加入允许列表、未修改防护设置，停止继续 Windows 原生测试，后续验证使用现有 Linux 环境。已记录通过结果不等于已解决该环境提示。

这是本机合成场景，“离线”是指定源服务停止，并非操作系统断网。没有重跑完整 Windows 五组、完整 Maple 或新 Docker 镜像，不把上一服务端的冷备份/Docker记录视为本次重新验收。成果在本地，尚未 Commit/Push。

## 2026-10-20 原生服务端与 Mirror/Sync URL 安全边界

部署脚本的 URL 保护未覆盖直接执行服务端。旧产物会在启动日志输出带凭据的 `CJREPO_UPSTREAM`，Mirror/Sync 也未统一检查源/目标；非法目标仍可能先请求源，watcher 会持续重试，缓存 Mirror 可跳过地址检查并修改索引。新真实进程矩阵在旧 Windows Server 上为 **5/95**（仅五个合法地址对照通过）。

新增 `server/src/registry_url.cj`，复用客户端同等的小型词法安全边界：只允许 HTTP(S) 前缀、非空且无 userinfo/百分号的 authority，拒绝查询、片段、反斜线和 ASCII 控制/空白。启动、单项、清单和 watcher 均在后续操作前检查地址，Sync 先检查源与目标；错误只报告角色，不回显值。独立审查另发现规范化可能将原始 `/` 裁为空：新增回归后中间版本 **95/96**，改为先检查原值再处理尾斜杠，原始空值仍关闭 Proxy。复核无新增阻塞项。

最终固定 137 个服务端/测试文件，归档 SHA-256 为 `e192f8d90b733ed2e274d11dd6abd43ce339071ee72eaea8d070f11ff832318d`；Linux 在新的验证目录核对全部摘要后构建，客户端未修改。

| 验证 | Windows | Linux |
| --- | ---: | ---: |
| 原生 URL 矩阵 | **96/96 PASS** | **96/96 PASS** |
| Hosted 真实包集成 | PASS 16.69s | PASS 37.20s |
| Proxy 真实包集成 | PASS 23.88s | PASS 36.05s |
| Mirror / Sync 真实集成（含清单与 watcher） | PASS 15.50s | PASS 16.87s |
| 三组编排合计 | **3/3，56.22s** | **3/3，90.15s** |

矩阵的 91 项拒绝检查覆盖启动、源/目标、清单、watch、空命令地址、缓存 Mirror 以及单斜杠配置，断言及时非零退出、安全诊断、无测试凭据回显、夹具未收到 HTTP 请求和既有存储文件摘要不变。五项合法对照中，只有 HTTP 路径/令牌头实际访问上游；HTTPS、IPv6、大小写 scheme 和编码路径中的相应检查仅证明服务启动接受配置，不证明其 TLS/连接兼容性。该词法边界也不等于完整 URI 语法、所有 Unicode 空白或远端错误文本审计；不支持 authority 百分号形式的 IPv6 zone identifier。

| 产物 | SHA-256 |
| --- | --- |
| 新 Windows Server | `6c475c54f04b8252f92c1039629953acf91f51fa6a1ee0fdec7b260bd7f8c55b` |
| 新 Linux Server | `09d03bf5b9bf5dab9ff0631e02fd05c61b3ccdd5a9883a7b85e5951f6a84dc2c` |

基于已有本地候选运行时镜像，只替换上述 Linux Server，禁用拉取和构建网络，创建独立 `cjrepomesh:native-urls-20261020`，ID 为 `sha256:6c8b677e1d4c41ba0dda376719efcf48a240c725fb8d75bdbfcc5bd3c9659861`。容器内带凭据/单斜杠两个配置均安全退出 2；Doctor **9/9 PASS**，私有读取、组织隔离、重建持久化及重复 409 通过，运行中二进制摘要与新 Linux Server 相同。没有覆盖默认镜像、正式 `.env` 或业务卷。

原始证据在外层 `test-runs/server-urls-20261020/`：基线与单斜杠失败日志、两平台 `*-final-urls.log` / `*-final-details/results.json`、`*-core.log`、新旧二进制摘要、`final-source.tar` / `final-source-sha256.json` 及 Docker 构建/Doctor/持久化输出。收口核对生产/测试脚本未再变化；归档内后补的一份使用说明另存 `documentation-overlay-sha256.json`，结果核对汇总为 `verified-results.json`。本轮未重跑客户端 Multi-repository、完整 Windows 五组、冷备份与其他恢复专项或完整 Maple；此前这些结果保留其原产物边界。变更仍在本地，尚未 Commit/Push。

## 2026-10-20 Maple 调用者目录隔离与离线 HLT 子集

测试入口原先只对部分用例设置临时 HOME。新增回归使用一个真实 Python 子进程，将合成的“调用者目录”作为 HOME/USERPROFILE，检测子进程是否写入该目录；旧入口 **FAIL**，证实了配置和写入隔离缺口。这里使用的是测试自建目录，没有操作真实个人文件。

`maple_smoke.run_case` 现在每例均使用独立 HOME/USERPROFILE，并移除调用者 `CJPM_CONFIG`；需要运行本地安装命令的用例继续将相应 `.cjpm/bin` 加入 PATH。修复后 Windows 与 Linux 隔离/端口单元均 **3/3 PASS**。该单元中的探针不是官方 Maple 用例；随后实际调用官方框架，原版和增强版各完成配置 **3/3**、HTTP 状态 **1/1 PASS**。未因此重复整套 39 项或产品核心集成。

证据为外层 `test-runs/maple-isolation-baseline-20261020.log`、`maple-isolation-fixed-20261020.log`，以及 `test-runs/maple-offline-hlt-20261020/` 的 `linux-unit.log`、`config-http-summary.log`、`config-http/` 与 `inputs-sha256.txt`。客户端二进制沿用下文当前候选与官方基线，未修改生产源码。

继续扩展现有 `maple_local_bundle.py --level HLT`：对官方 `HLT/Tools/cjpm/repo/bundle` 的 101 个 `.info` 先做本地操作检查，选择其中 95 个。排除 `bundle_build_03/04/06`（没有 Linux EXEC）、`bundle_include_23/28`（另有 Python 生成夹具步骤）与 `bundle_verify_03`（含依赖查找），没有运行发布、下载或在线索引用例。使用既有 Maple 框架及官方 LLT cjpm Linux 工具配置执行这些 HLT 来源用例，不改其内容和断言，不宣称完整 HLT 环境验收。

| 二进制 | 所选 HLT 打包用例 | 逐例耗时之和 |
| --- | ---: | ---: |
| 官方原版 `2f624cbe…` | **95/95 PASS** | 274.08s |
| 当前增强版 `7e29eaa7…` | **95/95 PASS** | 281.95s |

结果位于 `test-runs/maple-offline-hlt-20261020/hlt/bundle-1792504961-9939b607/`，含 `selection.json` 与 190 份逐例 `runner.log`。收口时核对每份真实 Maple 日志的 `Total: 1, PASS: 1, FAIL: 0`、对应二进制摘要和原始用例摘要，另保存 `results-summary.json` 与各日志 SHA-256。耗时为日志记录的逐例合计，未当作整批墙钟时长；这 95 个用例不与历史 LLT 子集相加冒充全量。完整 HLT/LLT 仍未执行。

## 2026-10-20 Docker 卷冷备份与异常证据保留

新增 `integration-tests/recovery/docker_backup.py`，使用本地已有候选镜像（固定 ID，不拉取），由当前 Windows cjpm 打包真实默认/命名组织包。最终演练 **9/9 PASS，25.16s**：停源容器后只读挂载其唯一测试卷，导出完整 tar；校验路径/类型及文件摘要后恢复到另一个新卷，启动前再次对比文件集合和 SHA-256。恢复容器通过私有读取、两个全新缓存消费者构建、重复版本 409、新版本发布及重启读取；源卷与备份归档保持不变。仅回收本次自建容器与带匹配标记的卷，没有操作正式 Compose 项目。

独立审查指出失败时清理容器会丢失异常日志。修复为删除前保存完整 inspect 及含 stderr 的日志，捕获失败时尝试停止并保留容器。另在真实测试容器已启动后，注入健康检查失败：演练按预期返回 1，校验器确认诊断文件已经保存、容器已移除而两个测试卷保留，随后按本次唯一标记显式回收这两个测试卷；该故障注入检查 **PASS**，不把故意的 `0/9` 当作产品功能失败或成功验收。

- 镜像 ID：`sha256:fc24453eb2a0212439ec21099adf56656b38644f62e180b35e520bf137fe0fef`；容器内 Server SHA-256：`d0d7fd99f568a7006903b8d43f4fa31dc7c60e39d014ddad831bdec4c76862e2`，与上一批 Linux 候选一致。
- Windows cjpm 沿用下表产物；最终演练脚本 SHA-256：`ca8e1aaef9d81b53a337ebff28221ee602a0bc1c5c0c15b2984219faa796a0e5`。
- 原始证据：外层 `test-runs/docker-cold-backup-20261020/` 的 `final.log`、`final-result.json`、`final-source-sha256.json`、`final-details/`（含合成包备份、清单、运行时身份及消费者日志），以及 `failure-injection.log`、`failure-details/`。

这里只验证隔离卷的停服备份恢复，不宣称在线快照、自动调度、业务切换或断电持久性；没有修改生产源码或重建候选二进制。

## 2026-10-20 文件存储冷备份恢复演练

在已交付的 AtomGit `d99d51ee` / GitHub `7aee7732` 等内容源码基础上，新增 `integration-tests/recovery/backup.py`；没有修改生产源码或重建二进制。两端提交历史不同、文件树相同，GitHub 后续交付继续使用 noreply 分支。本批测试与文档尚未 Commit/Push。

| 平台 | 检查点 | 耗时 | 产物 |
| --- | ---: | ---: | --- |
| Windows | **10/10 PASS** | 16.33s | 下文当前候选表的 Windows cjpm / Server |
| Linux | **10/10 PASS** | 29.05s | 下文当前候选表的 Linux cjpm / Server |

演练实际打包三个初始制品（默认组织两个版本、命名组织一个版本），授权发布并校验读取权限。停止源实例后，对完整存储复制和逐文件 SHA-256 校验；故意损坏制品或移除索引的两个副本均被测试清单比较发现。将原存储改为离线路径，从备份复制到新目录启动，分别用全新缓存的两个消费者下载、构建和运行。恢复实例拒绝重复版本，接受第四个真实制品，重启后仍能读取全部版本；备份与离线原件保持不变。成功后只清理测试自有进程与临时存储。

最终证据保存在外层 `test-runs/cold-backup-20261020-isolated/`：`windows.log`、`windows-result.json`、`linux.log`、两平台 `*-details/` 的打包/服务/消费者日志及 `backup-manifest.json`。脚本两平台摘要相同，为 `a28ffa6db14fa56a9332f8425ea1661d331abfdc0aea8cda133b237e804f844e`；Windows 输入摘要另存 `windows-input-sha256.json`，Linux 输入摘要在 `linux.log`。

初版两平台演练虽通过，独立审查发现打包夹具可能读取用户级 cjpm 配置。修正为隔离 HOME/USERPROFILE，并给每个夹具写本地仓库/缓存配置后，两平台重新执行并得到上表结果；复核未发现新的必须修复问题。初版证据保留在 `test-runs/cold-backup-20261020/`，不作为最终脚本验收；其中首次 WSL 启动因外层参数转义失败，尚未进入测试，原输出保留为 `linux-launch-preflight.log`。

本批仅补齐停服文件存储备份恢复的验证，不等于自动备份产品、Docker 卷恢复、在线快照、业务切换或断电持久性验收。完整 HLT/LLT 仍未执行；没有重复运行未受影响的核心套件。

## 2026-10-20 当前候选的固定源码验收

本轮从 Windows 源码工作区固定了 245 个客户端、服务端与测试源文件，逐文件计算 SHA-256 并归档为 `source.tar`。在新的 Linux 验证目录解包，先核对全部摘要，再用已有 SDK/stdx 与本地静态库构建；未安装或下载依赖。证据目录为外层 `test-runs/candidate-20261020-hardening-420fee1a/`，源码清单为 `source-sha256.json`，归档 SHA-256 为 `6e8ebf6e13ad65a460f96cf17fac1a6a986b03a32b82081dd707179126335583`。

| 产物 | SHA-256 |
| --- | --- |
| Windows cjpm | `20f3ce0c534c981a755388bc5b4b73e79e9e07a83d76336391130fb10570355d` |
| Windows Server | `df0ebfe6d5e7c935d15d01e1ee0167dbaf81978d29603f698da2f70443c3a05f` |
| Linux cjpm | `7e29eaa7e02885ba6d9ae998a6d2787170db5b17b28741bb61d613e02b330abf` |
| Linux Server | `d0d7fd99f568a7006903b8d43f4fa31dc7c60e39d014ddad831bdec4c76862e2` |

### 当前产物核心集成

| 测试组 | Windows | Linux |
| --- | ---: | ---: |
| Multi-repository cjpm | PASS 63.62s | PASS 127.93s |
| Hosted repository | PASS 11.77s | PASS 35.68s |
| Proxy repository | PASS 19.45s | PASS 40.72s |
| Repository sync | PASS 14.34s | PASS 20.74s |
| 四组编排合计 | **4/4，109.36s** | **4/4，225.24s** |

Windows 同次综合入口在进入第五组时暴露测试脚本缺陷：相对 `-Cjpm` 路径在切换到隔离夹具目录后失效。将路径在切换前解析为绝对路径后，仅单独复验部署组并通过实际构建包、启动、Doctor、发布、停止/重启和下载校验；没有重复四组，也不宣称原来那次五组入口全通过。输出分别为 `windows-core.log` 和 `windows-deployment-relative-path.log`。

冻结之后只补 Windows 测试入口路径、Maple 夹具端口释放等待、相应单元回归及测试说明；提交前另清理一处 PowerShell 测试文件末尾空行，生产源码和上述二进制未变化。四个已存在测试/说明文件及一个新增单元测试以 `test-overlay/`、`test-overlays-sha256.json` 单独保留，不覆盖原归档；Windows 部署脚本另有 `windows-deployment-source-sha256.json`。

### 恢复、配置与容器

- Linux 当前产物另完成 Hosted 恢复 **23/23**、Sync 恢复 **12/12**、配置/诊断 **36/36**、网络边界默认集合 **14/14**，输出为 `linux-*-recovery.log`、`linux-config.log`、`linux-network.log`。
- Windows 当前客户端配置/诊断 **36/36**，输出为 `windows-config.log`。真实读取超时的独立测试及对应候选边界见下一节。
- Docker 基于新 Linux Server 和现有运行时创建独立本地候选镜像，使用已缓存 Ubuntu 22.04，禁用拉取和构建网络。没有覆盖默认 `cjrepomesh:local` 镜像，也没有操作正式部署 `.env` 或卷。
- 原 Docker Doctor **9/9 PASS**；独立随机 Compose 项目完成私有读取、匿名发布拒绝、默认/命名组织发布下载、容器重建持久化与重复 409，之后仅回收本测试容器和卷。
- 容器内 `/usr/local/bin/cjrepo` 摘要与上述新 Linux Server 一致，候选镜像 ID 为 `sha256:fc24453eb2a0212439ec21099adf56656b38644f62e180b35e520bf137fe0fef`；运行摘要及输出见 `docker-running-binary-sha256.txt`、`docker-doctor.log`、`docker-persistence.log`。

### 官方原版对照与选定 Maple

同一 Linux 候选与原版 cjpm（SHA-256 `2f624cbe5493fcc686611e22eef7eb30e317c1ec589c18980dd88892875d9646`）的单仓差分 **7/7 PASS**，覆盖固定/范围/混合依赖、传递约束与最新版、不可解冲突、锁文件更新转换及旧缓存布局。

Maple 选定用例两版各 **39/39 PASS**；另外的稳定化 `repository_archive_matrix` 两版各 **1/1 PASS**。稳定化仅在测试副本固定 gzip mtime，保留原始/调整脚本摘要，不表述为未经调整的官方矩阵通过。

首次 Maple 在原版 34 项已经通过后，因前一夹具端口瞬时存活而被入口拦截，报错时第二次探测已为空。入口改为最多约 5 秒等待端口释放，不结束未知进程；持续占用仍拒绝。两个单元回归在旧入口均失败，修复后 Windows/Linux 均 **2/2 PASS**。为避免重复测试，续跑按同一原版二进制摘要及每组实际 Maple 日志核对、复用上述 34 项，只新增执行原版剩余 5 项与稳定化矩阵，以及增强版全部 39 项与稳定化矩阵；不声称两版在一次全新调用中各重跑全部。

原始输出为 `official-differential.log`、首次 `maple-summary.log` 与 `maple/`；续跑记录为 `maple-resumed-summary.log`、`maple-resumed/run-1792499862-c6981720/` 和 `maple-reused-results.json`。官方夹具源未修改，测试使用隔离 HOME 和临时副本。独立收口源码审查未发现需要处理的真实问题，未代替上述实测。

本地官方 cjpm 测试目录另有 LLT 1202 个、HLT 157 个 `.info` 文件（文件清点，不等于本轮运行数）。完整 HLT/LLT 未执行，不能把选定集合当作全量。断电持久性、跨进程共享存储及独立备份灾难恢复演练也不在上述通过结论内。

验收结束、推送前，AtomGit 与 GitHub 的 `refs/heads/main` 在关闭凭据辅助器及额外认证头后均可匿名读取，提交同为 `73efda2602088928fb7dcc8b823adaae7b192731`。这些验证在该 HEAD 的未提交工作区完成，未读写私有签字与个人材料。参赛者随后授权本批 Commit 并推送到两个参赛仓库；最终提交以远端 Git 记录为准，不向 `origin` 推送，不创建 Release。

## 2026-10-20 客户端地址安全与网络失败分类

新增 URL 回归在此前客户端上为 **25/32**：内嵌凭据、查询参数和片段会实际触网，其余非法地址也缺少统一且不回显值的诊断。`Depot.loadConfiguration` 现在在请求、在线 explain 和来源写入前拒绝不安全地址，认证使用 `token-env`。只允许 HTTP(S) 基地址，拒绝 userinfo、查询参数、片段、反斜线及 ASCII 控制/空白；authority 中的 `%` 也拒绝，所以不支持带 zone identifier 的 IPv6 地址。

独立审查确认新请求路径未提前输出不安全地址，同时指出历史来源仍会被离线 explain 原样显示。新增三项合成历史记录后为 **33/36**，修复后最终 Windows 配置与诊断专项 **36/36 PASS**：`--recorded` 在显示前使用相同约束，拒绝不安全记录但不自动改写原文件。普通历史记录、旧单仓缺省值及合法独占路由控制均通过。

- 最终 Windows 客户端 SHA-256：`20f3ce0c534c981a755388bc5b4b73e79e9e07a83d76336391130fb10570355d`。
- 初次 URL 修复候选的真实多仓单组 **PASS 63.30s**；之后仅补历史记录显示检查，最终候选的综合验收另见本文首节。
- 网络边界专项 Windows **15/15 PASS**，包括实际客户端读取超时、连接拒绝/重置、截断响应、损坏索引、HTTP 状态与独占路由。超时测试当时使用地址检查补充前的客户端，未把该结果冒充后续所有客户端的重新执行。
- 404 与 5xx 可回退；400/401/403/429、传输失败、读取超时和损坏索引停止；独占路由始终不跨出目标仓。
- 原始证据：外层 `test-runs/registry-url-baseline-20261020-*/`、`test-runs/registry-url-fixed-20261020-201643/`、`test-runs/recorded-url-baseline-20261020-*/`、`test-runs/url-final-multirepo-20261020-201642/` 和 `test-runs/network-timeout-20261020-*/`；最终配置输出见候选证据目录 `windows-config.log`。

缓存继续以仓库配置名隔离；更改同名仓地址指向无关服务不会自动清空旧缓存，操作约束见多仓说明。上述检查不等于对全部远端错误文本的全面脱敏审计。

## 2026-10-20 Sync 目标完整性与中断重跑

此前 Sync 只根据目标索引的版本与 SHA-256 判断是否跳过，导致索引存在而制品缺失、损坏或读取被拒绝时仍报告成功。新增 `integration-tests/recovery/sync.py`，旧服务端 **8/12**：默认/命名组织的缺失制品、损坏制品和制品 403 四项错误通过。

修复只位于 `destinationHasVersion`：索引匹配后读取并验证目标制品；404 进入 Hosted 缺失制品补齐，其余非 200 与摘要不符明确失败。相同检查也用于并发发布 409 后确认；不会覆盖已存冲突内容。代价是已存在版本需额外读取一次目标制品，但仍不下载源制品。

- 最终服务端 SHA-256：`df0ebfe6d5e7c935d15d01e1ee0167dbaf81978d29603f698da2f70443c3a05f`。
- 恢复专项 **12/12 PASS**，含索引/制品单边残留、提交失败回滚重试、冲突拒绝、读取权限及三种真实进程终止。
- 原真实包 Sync 单组 **PASS 21.88s**，编排合计 21.97s，覆盖清单、私有源/目标、watcher、组织隔离和离线构建。
- 原始输出与哈希：外层 `test-runs/sync-recovery-baseline-20261020-195142/`、`test-runs/sync-recovery-fixed-20261020-195226/`、`test-runs/sync-core-fixed-20261020-195227/`。
- 独立源码审查未发现本轮生产逻辑缺陷；审查没有重新运行测试，实测结果来自上述执行记录。

三种真实终止分别发生于：源响应尚未完整发送、目标提交后代理暂扣响应、代理向目标 socket 发送部分请求后。最后一种只证明发送调用完成，未观测目标 handler 已消费多少字节，不宣称终止发生在磁盘写入或两次 rename 之间。目标残留用确定性磁盘注入；专项使用合成协议负载，真实包由 Sync 单组验证。未宣称断电恢复、字节级续传、跨进程共享存储互斥或所有时序穷举。该候选产物未重新执行完整 Windows 五组、Linux/Docker 或完整 Maple。

## 2026-10-20 Hosted 发布中断恢复与临时文件隔离

继续在 HEAD `73efda26` 的本地未提交工作区实施，仅修改服务端发布与原子写入逻辑；增强版 cjpm 未再变化。

### 已修复的实际故障

1. 制品已落盘但索引未提交时，重发被误判为完整重复；现在只在磁盘制品校验和与上传匹配时补索引，不重写已有制品。
2. 索引存在但制品缺失时，重发会追加重复版本，甚至为不同校验和版本写入制品；现在匹配原索引时只补制品、保留索引字节，冲突仍为 409。
3. 已存索引的重复记录、错误身份、非法版本或 SHA-256 格式会在任何写入前阻断；完整版本仍保持不可变。
4. 原子写入的 `<包名>.tmp` 会与合法的同名包索引冲突：先发布 `recoverneighbor.tmp`，再发布 `recoverneighbor` 可使前者索引丢失。现在使用点号开头的内部临时名，API 不接受该路径，正式存储布局不变，也不擅自清理有歧义的旧 `.tmp` 文件。

所有恢复仍在原有鉴权、上传 SHA 校验及包锁内执行，200 响应格式保持兼容。恢复成功增加不含令牌的 `result=RECOVERED` 日志。

### 最终产物与实测结果

- 服务端 SHA-256：`57c86835be35e4492a8e0683db7e6fd7e42879b736a6ea25a77ef4586c7b43a6`。
- 客户端沿用前一配置修复产物：`6361b12850144f0f21b70fc28bdf26cdfbc9b666710e01d1ce636813aae230d4`。
- `integration-tests/recovery/run.py` **23/23 PASS**，包括两类并发恢复、索引提交失败时的不同回滚行为、旧记录格式损坏、组织隔离、临时文件名碰撞及半上传时强制终止自有进程后的重启。
- 该最终服务端执行真实集成：Hosted **PASS 16.41s**、Proxy **PASS 21.70s**、Sync **PASS 14.08s**，合计 **52.30s**。复用已构建产物，未重复无关客户端多仓套件或整套 Windows 验收。
- 原始输出与源码/产物哈希位于外层 `test-runs/hosted-recovery-storage-20261020-171721/`、`test-runs/storage-recovery-integration-20261020-171804/`。

独立审查指出的损坏 SHA 检查遗漏已通过“截断/非 hex 校验和 × 新发布/孤立制品/缺失制品”六种故障复现后修复，并完成复核。最初未修复版本的恢复矩阵为 3/10，后续格式遗漏为 14/21，临时文件碰撞为 21/22；这些失败仓库的 21、44、42 个文件分别完整移至外层 `test-runs/hosted-recovery-{baseline,index-validation,temp-collision}-failure-20261020/`，未丢弃失败证据。

### 验证边界

两个文件提交之间的磁盘状态通过确定性注入验证，不宣称把真实 kill 精确落在两次 rename 之间；真实进程终止用例覆盖未完成 HTTP 上传及之后的重启。专项使用小型合成协议制品，真实 cjpm 包与构建由上述三组集成另行验证。本轮没有验证断电持久性、fsync、跨进程共享存储互斥、完整仓间 Sync 进程中断矩阵，或新的 Linux/Docker/完整 Maple 结果。

## 2026-10-20 Windows 部署与配置安全补强

本轮在 `cjrepomesh-multirepo` 分支、HEAD `73efda26` 上的未提交工作区实施；未 Commit、Push 或发布。使用已安装的 Windows SDK（Cangjie Compiler 1.1.3）、stdx 1.1.3.1 和已有 C++ 静态库，实际重建服务端及增强版 cjpm，未下载依赖或改变系统安全策略。

### 部署脚本与真实运行

- Windows PowerShell / Pester 3.4 隔离回归 **22/22 PASS**：外部监听地址覆盖、环境恢复、端口占用与归属、PID 复用、旧状态、停止超时、时间戳精度及不安全上游 URL。
- PowerShell 7 和 Windows PowerShell 5.1 分别完成真实隔离部署：启动、Doctor、发布真实制品、停止/重启、下载与 SHA-256 核对均通过。
- 部署集成测试改为复制脚本、服务端与测试包到唯一测试目录，不操作正式部署实例。成功路径只清理自己的目录；停止失败时保留状态和日志。
- 原始输出位于外层 `test-runs/windows-deployment-hardening-20261020-161648/` 和 `test-runs/windows-powershell51-deployment-20261020-161819/`。

### 日期类型检查补充前的候选产物五组验收

使用客户端 SHA-256 `83ecd2e862ca9e644b352e27f2dbb976275ec50768383f5afc21eb759553c4ff`，服务端 SHA-256 `5919de1a3f5a3e912b928ad2f09e30a93a50436c77ad2579cb33a44d69f98b67`。这时已包含字段类型检查，尚未加入之后发现的原始 TOML 日期/时间检查。

| 测试组 | 结果 | 耗时 |
| --- | --- | ---: |
| Multi-repository cjpm | PASS | 122.55s |
| Hosted repository | PASS | 866.39s |
| Proxy repository | PASS | 19.92s |
| Repository sync | PASS | 13.99s |
| Windows deployment | PASS | 8.31s |
| **五组合计（含编排开销）** | **5/5 PASS** | **1032.22s** |

入口为 `integration-tests/run-all.ps1 -SkipServerBuild`，服务端复用本轮刚构建的上述产物。原始输出及二进制哈希保存在外层 `test-runs/windows-core-hardening-20261020-162533/`。

### 最终配置修复产物的针对性复验

独立审查发现公共 `DataModel.fromToml` 会将 TOML 日期/时间转换为字符串。本轮仅在 `readConfigToml` 内、共享转换之前检查仓库与路由的原始字符串类型，未改变其他配置文件的转换规则。

- 该阶段最终客户端 SHA-256：`6361b12850144f0f21b70fc28bdf26cdfbc9b666710e01d1ce636813aae230d4`；当时服务端仍为上节五组验收所用产物。后续服务端恢复补强的独立结果见本文首节。
- 配置回归 **25/25 PASS**：22 项非法配置均非零退出、给出字段类型错误且 HTTP 请求数为 0；3 项合法控制保留独占路由、旧单仓默认值和带引号的日期字符串行为。补充前同一扩展矩阵为 16/25，四种时间类型的路由值可导致错误触网。
- 最终客户端重新执行受影响的多仓单组 **PASS，60.75s**，覆盖传递依赖、菱形冲突、替换、来源记录、完整性拒绝、401/403、独占路由与旧单仓兼容。
- 原始证据分别位于外层 `test-runs/config-temporal-hardening-20261020-164723/` 与 `test-runs/windows-final-multirepo-20261020-164743/`。

后续补充仅收紧错误 TOML 类型的处理；未重复其余昂贵测试。因此不能表述为“最终客户端又完成一次五组全量”。本轮也未重跑 Linux 四组、Docker 验收或完整 Maple HLT/LLT，历史证据与本轮结果继续分开记录。

### 保留的失败记录与限制

测试包隔离最初漏复制 README，导致 bundle 正确拒绝；随后补齐。PowerShell 7 自动将状态时间戳转换为 DateTime，最初的字符串比较丢失精度；改为 UTC ticks 比较后，在真实实例上完成身份确认与安全停止，并补回归。该失败实例的 24 个文件已移至外层 `test-runs/windows-deployment-identity-failure-20261020/`，失败日志和编译诊断未删除。

旧状态不含精确启动时间时，新脚本拒绝自动停止仍存活的 PID；人工核对迁移方式见 `deployment/windows/README.md`。完整官方兼容性、进程中断恢复专项、最终跨平台验收和公开发布仍是后续工作。

## 2026-09-26 本地交付材料提交回归

在本地提交 `98e9f8499d7f97afece81f13601bb9f0deb5a5de` 上，从 Windows 工作区的 WSL 2 `CjRepoMesh` 发行版运行 `integration-tests/run-linux.sh`。使用增强版 cjpm SHA-256 `6336f0bd1c973c4128717d7684ab13cdc3dce0840b9b8793aa5e599a00dca62a`，入口真实重编译当前工作区服务端，产物 SHA-256 为 `9347140e8436183114c01e79c97a795508b695dd84fe455d2b6d05a47d65d87b`。

| 测试组 | 结果 | 耗时 |
| --- | --- | ---: |
| Multi-repository cjpm | PASS | 151.66s |
| Hosted repository | PASS | 32.08s |
| Proxy repository | PASS | 38.92s |
| Repository sync | PASS | 24.03s |
| **合计** | **4/4 PASS** | **252.01s** |

原始输出保存在外层 `test-runs/final-core-98e9f849-2026-09-26/output.log`，SHA-256 为 `fbe402e7082aa24e480bdaefdc51eebe0ff709598239aeb71571273b6b9db9b6`。首次预检因 Windows 工作树未包含默认 Linux cjpm 路径而在测试组开始前退出；失败输出保存在同目录 `preflight-missing-cjpm.log`，随后显式指定上述已核对 SHA-256 的增强版 cjpm 重试，没有掩盖失败过程。

回归结束后 Git 工作区干净，`integration-tests/.tmp` 不存在，`CORE_PORTS` 定义的 39141–39147、39200–39202、39300–39307、39401 和 39501–39504 均无监听。随后既有 Docker 主容器再次通过 Doctor 9/9。本轮未运行 Windows 原生五组、Docker 隔离持久化专项或完整 Maple HLT/LLT；后续验证记录提交仅修改文档与表格材料，不把它表述为重新执行产品测试。

## 2026-09-26 Docker 运行状态复核

Docker Desktop 从停止状态启动后，现有 `cjrepomesh-cjrepo-1` 使用原镜像、配置和命名卷自动恢复，状态为 `healthy`，仍只绑定 `127.0.0.1:8080`。`deployment/docker/doctor.ps1` 的容器运行、Docker 健康、非 root、只读根文件系统、丢弃 capabilities、禁止新增权限、本机绑定、持久化卷和 Registry API 九项及 Overall 全部 PASS。

本轮没有重建镜像、重新核对容器内二进制 SHA-256、运行隔离持久化专项或重跑 Linux 四组；它只证明当天既有部署的恢复状态和 Doctor 诊断，不替代 2026-09-25 的完整回归记录。

## 2026-09-26 双公开仓库匿名复核

只读 `git ls-remote` 确认 AtomGit `Chemic666/CjRepoMesh` 与 GitHub `zhan-cm/CjRepoMesh` 的 `refs/heads/main` 均指向 `8cd4a82130e23e3ec0701c7e3791d1d953280cac`。分别禁用凭据助手并使用部分克隆建立新的匿名检出，结果均为干净的 `main...origin/main`，HEAD 与远端一致。

两个检出均可读取根目录 `README.md`、`README.OpenSource`、`LICENSE`、`CHANGELOG.md`、`.gitattributes` 和 `integration-tests/README.md`。在本机全局 `core.autocrlf=true` 条件下，`git ls-files --eol` 显示 `integration-tests/run-linux.sh` 及受管 Python 入口均为 `i/lf w/lf attr/text eol=lf`。证据目录分别为外层 `test-runs/atomgit-anonymous-lf-8cd4a821-2026-09-26/` 与 `test-runs/github-anonymous-8cd4a821-2026-09-26/`。

`8cd4a821` 相对已完成 Linux 4/4 的 `6c4dbc8a` 只修改 `CHANGELOG.md`、`docs/submission-checklist.md` 和 `docs/verification-report.md`，未改产品源码、部署脚本或测试入口。因此本节证明最终公开提交与检出可用性，不把它表述为在 `8cd4a821` 上重新执行了 Linux、Docker 或 Windows 回归。

## 2026-09-25 Windows 干净检出换行修复

在 Windows 全局 `core.autocrlf=true` 的条件下，匿名克隆 AtomGit 提交 `71e5cc80` 后，检出的 `integration-tests/run-linux.sh` 为 CRLF，WSL 直接执行报 `/usr/bin/env: ‘bash\r’: No such file or directory`。这是仓库缺少 Unix 脚本换行约束导致的实际可移植性故障；失败日志保存在外层 `test-runs/anonymous-final-core-71e5cc8-2026-09-25/output.log`，SHA-256 为 `522c643721fbbdfdae12839349b4bb7d4192aac23dfc9bcdb03574792afa1cf8`。

提交 `6c4dbc8a` 增加 `.gitattributes`，对 `*.sh` 和 `*.py` 明确 `eol=lf`。在同一 Windows Git 设置下创建的独立工作树显示 `integration-tests/run-linux.sh` 为 `i/lf w/lf attr/text eol=lf`；从该干净检出实际重建服务端并运行四组，结果为：

| 测试组 | 结果 | 耗时 |
| --- | --- | ---: |
| Multi-repository cjpm | PASS | 140.69s |
| Hosted repository | PASS | 31.49s |
| Proxy repository | PASS | 33.56s |
| Repository sync | PASS | 20.46s |
| **合计** | **4/4 PASS** | **230.47s** |

该检出的服务端产物 SHA-256 为 `bb3afe5d728328574f8775d537e43312b9216efbea267bdb253eae287d12055b`；原始输出保存在外层 `test-runs/lf-core-6c4dbc8-2026-09-25/output.log`，SHA-256 为 `25891c7048c972320e603ac82427194da49deba911f13da473ae0e5cb46310d7`。测试临时目录与固定端口无残留，项目 Docker Doctor 9/9。此轮使用干净的本地 Git 工作树；修复推到 AtomGit 后仍需用新的匿名克隆核对公开检出换行。

## 2026-09-25 AtomGit 公开提交复核

从可匿名克隆的 AtomGit `main` 核对提交 `31567a61782c73b45026dd666044cccdb5ac6986`，在相同 Windows 工作区的 WSL 2 / Ubuntu 22.04.5 中运行 `integration-tests/run-linux.sh`，没有使用 `--skip-server-build`。增强版 Linux cjpm SHA-256 为 `6336f0bd1c973c4128717d7684ab13cdc3dce0840b9b8793aa5e599a00dca62a`，当次重建服务端 SHA-256 为 `9347140e8436183114c01e79c97a795508b695dd84fe455d2b6d05a47d65d87b`；后者与前一轮及 Docker 镜像内二进制一致。四组结果：

| 测试组 | 结果 | 耗时 |
| --- | --- | ---: |
| Multi-repository cjpm | PASS | 141.76s |
| Hosted repository | PASS | 29.48s |
| Proxy repository | PASS | 33.49s |
| Repository sync | PASS | 21.12s |
| **合计** | **4/4 PASS** | **230.19s** |

原始输出保存在工作区外层 `test-runs/final-core-31567a61-2026-09-25/output.log`，SHA-256 为 `e162f9c0312009999d922ca07f00478ab2d4c38fa315de2b2f89a1a8bd82386f`。运行器返回 0；测试临时目录不存在，检查的固定测试端口未监听，未发现测试进程残留。随后项目 Docker Doctor 9 项及 Overall 均 PASS。此轮没有运行完整 Maple HLT/LLT 或 Windows 原生五组，不能据此宣称二者通过。

## 2026-09-25 当前源码复核

在 WSL 2 / Ubuntu 22.04.5、Cangjie 1.1.3、stdx 1.1.3.1 上，增强版 cjpm 使用 SHA-256
`6336f0bd1c973c4128717d7684ab13cdc3dce0840b9b8793aa5e599a00dca62a`。
从本工作区源码重新 `cjpm build` 的服务端 SHA-256 为
`9347140e8436183114c01e79c97a795508b695dd84fe455d2b6d05a47d65d87b`，
与运行中的 Docker 镜像内 `/usr/local/bin/cjrepo` 一致。统一入口未跳过服务端构建，结果为：

| 测试组 | 结果 | 耗时 |
| --- | --- | ---: |
| Multi-repository cjpm | PASS | 157.92s |
| Hosted repository | PASS | 33.13s |
| Proxy repository | PASS | 36.87s |
| Repository sync | PASS | 22.98s |
| **合计** | **4/4 PASS** | **255.51s** |

原始 `script` 终端输出、经典时间记录和 `.cast` 回放文件保存在外层
`test-runs/video/linux-core-current-2026-09-25/`。`output.log` SHA-256 为
`4fde30eab17a3f8d85538cfbb2dff1dbf9016451ea0b2edfdf09e78b63d09c8f`。
重放是终端记录，不是屏幕无剪切录像。Docker Doctor 当天重跑 9 项与 Overall 均 PASS。

同日首次复跑误指定了 9 月 23 日的旧服务端二进制；多仓组 PASS 后，Hosted 的不安全配置拒绝用例因旧二进制持续运行而超时，整轮记为 FAIL。该失败日志保留在
`test-runs/video/linux-core-full-2026-09-25/`，没有与上述成功轮次合并或删除。

## 环境

| 项目 | 值 |
| --- | --- |
| 操作系统 | Windows（x86_64） |
| 仓颉编译器 | Cangjie Compiler 1.1.3（cjnative） |
| 编译目标 | `x86_64-w64-mingw32` |
| PowerShell | 7.6.5 |
| Python | 3.12 |
| 增强版 cjpm | `cjpm/target/release/bin/cjpm.exe` |
| CjRepo Server | `server/target/release/bin/main.exe` |

本次验证未下载、安装或解压任何依赖，使用用户已经放置在 `D:\Apps\Cangjie` 的工具链。

## 执行命令

```powershell
.\integration-tests\run-all.ps1 -SkipServerBuild
```

## 结果

| 测试组 | 结果 | 耗时 |
| --- | --- | ---: |
| Multi-repository cjpm | PASS | 45.03s |
| Hosted repository | PASS | 3.06s |
| Proxy repository | PASS | 7.24s |
| Repository sync | PASS | 4.97s |
| Windows deployment | PASS | 4.89s |
| **合计** | **5/5 PASS** | **65.47s** |

Windows Smart App Control / Code Integrity 已知会阻止未签名的仓颉 LLVM 组件，因此本次遵循安全边界复用现有 `main.exe`，没有尝试关闭安全功能或重复触发 Windows 编译。相同提交内容随后在 Linux 统一入口中真实执行 `cjpm build`，服务端编译成功。`-SkipServerBuild` 只跳过服务端重编译，不跳过五组运行、故障或安全断言。

## 已验证证据

- 跨仓候选聚合后仍由原 cjpm 规则选择最高兼容版本；
- 同版本跨仓冲突按优先级确定来源，来源与 SHA-256 被持久化；
- `[replace]` 强制版本、缺失错误和允许范围内的仓库回退；
- `repo explain` 在线解释与离线 Provenance 审计；
- `repo doctor` 正常探测及 `401` 认证屏障判定；
- `404/5xx` 回退，`401` 禁止回退，`token-env` 认证；
- 独占命名空间阻止公共同名高版本包参与解析；
- 旧 `repository.home` 单仓配置兼容；
- Hosted 发布鉴权、SHA-256、重复版本、下载和并发原子写；
- Proxy 并发首次填充合并、MISS/HIT、TTL、离线命中和损坏拒绝；
- 批量 Mirror 清单逐项校验、幂等、部分失败汇总，带令牌 Sync，以及源仓离线后的目标仓构建；
- Windows 一条命令部署、健康检查、发布、持久化重启与安全停止。

## 结果解释

安全测试会故意执行应当失败的命令，例如错误令牌、缺失替换版本或损坏制品。测试脚本只有在这些命令按预期失败且安全断言成立时才记为 PASS；统一入口以断言异常为失败边界，不把预期失败命令遗留的进程码误判为整组失败。

## Linux 共享核心回归

2026-09-23 在 WSL 2 / Ubuntu 22.04.5、Cangjie 1.1.3、stdx 1.1.3.1 和 Python 3.10.12 环境中，对提交 `8e33119` 执行：

```bash
./integration-tests/run-linux.sh
```

结果为 4/4 PASS，总耗时 77.25s：Multi-repository 59.23s、Hosted 6.56s、Proxy 7.50s、Repository sync 3.94s。该入口与 Windows 共用 Python 夹具、断言和安全清理逻辑，并实际调用一次服务端构建。端口、进程与临时数据残留复核通过。详细证据见 `docs/linux-verification.md`。

## 未覆盖范围

- Linux 原生 cjpm/Server 构建、四组共享核心回归和离线来源解释已通过，详见 `docs/linux-verification.md`；
- Docker Compose 一键启动、真实发布、容器重建持久化和最小权限诊断已通过，详见 `docs/docker-verification.md`；
- Docker 在后续修复过程中再次 9/9 通过且启动输出不再回显 Token；`de2da77` 的 SecureString/ACL 路径在当时尚未完成容器启动复测，后续 `c602c12` 的默认 Token/ACL 完整链路已复测，见文末与 `docs/docker-verification.md`；
- 未执行依赖额外官方测试资产的完整 Maple HLT/LLT；
- Hosted/Proxy/Mirror/Sync 命名 organization 已分别通过专项验证；
- 本报告不是长期稳定性、跨机网络或公网安全认证报告；
- 性能数据见独立的 `benchmark/results/proxy-benchmark.md`，不由本功能回归推导。

## 早期提交复核（历史记录）

在 `b10ced9` 上运行 Windows `integration-tests/run-all.ps1 -SkipServerBuild`：第一组打包夹具时，系统 Application Control 拦截 `cjc -v`，统一入口停止，故本轮 Windows 结果记为 **环境阻断**，不能沿用上表的历史 5/5 作为当前提交结果。未调整 Windows 安全策略。

同一代码在 WSL 2 / Ubuntu 22.04.5 上执行 `./integration-tests/run-linux.sh`，服务端实际编译通过，四组为 **4/4 PASS**，总耗时 **510.22s**：Multi-repository 395.10s、Hosted 34.97s、Proxy 55.37s、Repository sync 24.71s。测试结束后没有留下固定测试端口和临时数据。本轮较历史 Linux 77.25s 明显变慢；两次结果均为实测值，不据此推导性能变化。

Docker Compose 在 `b10ced9` 上执行 `up.ps1 → doctor.ps1 → down.ps1`，9 项诊断全部 PASS。启动输出没有回显发布 Token，`.env` ACL 已关闭继承且仅当前 Windows 用户有允许规则。测试创建的 Compose 容器已停止并移除，命名数据卷保留；用户原先运行的独立 `cjrepomesh:local` 容器未被更改。

同轮完成官方原版与增强版的单仓差分 3/3，以及一个官方 LLT 夹具在两版上各 16/16 断言，结果见 `docs/official-compatibility-report.md`。完整 Maple HLT/LLT 仍未运行。

## 后续兼容性扩展

在未改动 cjpm 产品源码的前提下，单仓原版/增强版差分扩至 **7/7 PASS**：新增两版桥接包的传递约束下选择相容版本、共同选择最新版、不可解冲突拒绝，以及固定版本放宽后保留旧锁定版本、执行 `cjpm update` 再选择新版本。锁文件比较覆盖全部有效条目，但忽略 cjpm TOML 映射输出的不固定顺序；运行结果、依赖树和旧缓存布局也接受检查。详细条件与边界见 `docs/official-compatibility-report.md`。

## 跨仓传递依赖专项复核

在测试提交 `a663cbf` 上，WSL 2 / Ubuntu 22.04.5 运行 `./integration-tests/run-linux.sh --suite multirepo --skip-server-build`，单组 **PASS，78.69s**。新增的两个桥接包分布于优先级不同的仓库：根项目约束为 1.0.0 时，桥接包选自低优先级仓、底层包选自高优先级仓；根项目允许 2.0.0 时，桥接包选自高优先级仓、底层包选自低优先级仓。两种成功路径均检查运行输出、最终版本、来源仓，并将审计文件里的 SHA-256 与实际制品逐一比对；固定互不相容的两个版本则明确失败。整组既有多仓场景也继续通过。测试后无固定端口或临时数据残留。

本次是 cjpm 多仓**单组专项复核**，并显式复用已有服务端二进制；不记为最新提交上的 Linux 四组全量回归，也不改变上述 Windows 环境阻断结论。

随后同一测试提交 `a663cbf` 在 WSL 2 / Ubuntu 22.04.5 执行 `./integration-tests/run-linux.sh`，真实编译服务端，**Linux 四组 4/4 PASS，总耗时 96.13s**：Multi-repository 78.50s、Hosted 6.48s、Proxy 7.43s、Repository sync 3.69s。全量测试结束后，固定测试端口、服务进程和 `integration-tests/.tmp` 均无残留。产品 cjpm 源码未变；与先前 510.22s 的运行条件和系统负载不一定相同，不能据此推断性能提升。

## 未闭合验证环境的处置

本机 `Microsoft-Windows-CodeIntegrity/Operational` 于 2026-09-23 09:00:25 记录事件 3077：`cjpm.exe` 调用 `D:\Apps\Cangjie\bin\cjc.exe` 时被代码完整性策略拦截；`Get-AuthenticodeSignature` 对该 `cjc.exe` 返回 `NotSigned`。这定位了 Windows 当前阻断点，不是项目断言失败。当前不修改或绕过系统安全策略；Windows 原生五组需在经授权、工具链可运行的独立环境复测。

官方测试框架方面，此处记录的是当时环境。后续已取得 `cangjie_test_framework` 并运行一个 cjpm LLT 用例；`pexpect` 和 `fasteners` 仍未安装。先运行更多 cjpm 相关 HLT/LLT，再评估整套 HLT/LLT；运行范围必须分别报告，不把子集通过表述成整套通过。

## 401/403 安全回退补充复核

测试实现提交 `5f33e24` 为多仓模拟仓新增 HTTP 403 故障注入，并把已有 401 测试扩展为两种状态分别验证：依赖解析必须失败、错误中保留对应状态码、低优先级仓的请求日志必须为空；`repo doctor` 必须显示 `Fallback BLOCKED` 与 `Overall: FAIL`。Doctor 会独立探测允许的各仓以给出诊断，因此“低优先级仓零请求”只用于约束依赖解析，不错误套用到 Doctor。

2026-09-23 将同样的可执行测试逻辑同步到 WSL 2 / Ubuntu 22.04.5 测试副本，在已有 Cangjie 1.1.3/stdx 1.1.3.1 环境中运行多仓单组，**PASS，81.87s**。之后执行 `./integration-tests/run-linux.sh`，实际重新编译服务端，四组 **4/4 PASS，总耗时 98.52s**：Multi-repository 80.72s、Hosted 6.57s、Proxy 7.53s、Repository sync 3.68s。提交相较执行时的测试逻辑仅增加一行解释性注释。测试后 `integration-tests/.tmp` 已清理，固定测试端口未见监听。

本轮未重跑 Windows 原生五组、Docker Compose 或完整 Maple HLT/LLT；其状态仍按上述各节记录。

## 制品拒绝与并发下载失败修复

提交 `efb7e24` 新增“索引正常、制品返回 401/403”的故障注入：增强版 cjpm 必须保留已选来源、拒绝构建，不能从低优先级仓偷偷取同版本制品，也不能写出成功的 `cjpm-provenance.json`。另以两个跨仓传递包、`cjpm build -j 1` 和双 403 制品拒绝测试并发清理。修复前该命令超过测试的 30 秒上限；定位为下载任务失败时提前返回而未释放并发许可。首次加入 `finally` 后不再超时，但结果汇总的短路求值没有等待全部已启动任务。最终修复同时保证许可始终释放，并逐个等待所有下载任务。

2026-09-23 在现有 WSL 2 / Ubuntu 22.04.5、Cangjie 1.1.3、stdx 1.1.3.1 环境中重新编译 cjpm，得到二进制 SHA-256 `d2858f2f749b6f1e27b82afe9f01cce9ae95f76c466bd68423843fd2f5a57aa5`。修复后多仓单组 **PASS，83.28s**；`./integration-tests/run-linux.sh` 实际重新编译服务端，四组 **4/4 PASS，总耗时 101.47s**：Multi-repository 83.44s、Hosted 6.51s、Proxy 7.65s、Repository sync 3.85s。单并发双拒绝测试确认两个仓均收到制品请求、命令及时失败且未写成功来源记录。完整回归及随后的单仓差分结束后，测试临时目录和固定端口未见残留。

修复后增强版与已有官方原版 cjpm 的旧 `repository.home` 行为差分再次 **7/7 PASS**。随后用本地已有官方 `http_status_matrix` LLT 夹具分别对原版、修复后的增强版逐条核对，均为 **16/16 PASS**。Windows 原生五组、Docker Compose 和完整 Maple HLT/LLT 未重跑，不把历史结果计为本次通过。

## 独占命名空间故障矩阵

提交 `2bb1884` 把 `company::*` 独占路由的缺包测试扩为 HTTP **404、401、403、500** 四种故障。每次测试都清空应用缓存和公共仓请求日志，私有仓返回对应状态时要求构建失败、错误保留状态码，且放有 `company::auth 9.0.0` 的公共仓请求数仍为 **0**。这直接覆盖了认证失败、权限拒绝和服务故障不会越过独占路由；普通非独占仓的 404/5xx 回退仍由既有测试验证。

2026-09-23 在 WSL 2 / Ubuntu 22.04.5、上述修复后的 cjpm 二进制上，多仓单组 **PASS，85.83s**；随后执行包含服务端真实编译的 Linux 四组完整回归，**4/4 PASS，总耗时 103.30s**：Multi-repository 85.12s、Hosted 6.69s、Proxy 7.75s、Repository sync 3.73s。本次只扩展测试逻辑，未修改 cjpm 产品源码；Windows 原生五组、Docker Compose 与完整 Maple 套件仍未重跑。

## 篡改制品与缓存恢复

提交 `662935d` 扩展多仓夹具：高优先级仓的索引保持合法、只篡改同版本制品的下载字节；低优先级仓仍提供可用制品。断言要求增强版 cjpm 因 SHA-256 不一致拒绝构建，低优先级仓没有收到制品下载请求，也没有写出成功来源记录。随后不清空应用缓存，恢复高优先级仓的正常制品，要求构建成功，来源仍为高优先级仓，审计 SHA-256 与实际制品一致。这验证失败下载没有污染成功缓存或偷换制品来源。

2026-09-23 在已有 WSL 测试副本和修复后的 cjpm 二进制上运行 `./integration-tests/run-linux.sh --suite multirepo --skip-server-build`，新增断言及整组 **PASS，600.00s**；统一入口总耗时 600.10s。该轮编译相关步骤明显慢于此前约 85s 的多仓单组，期间进程持续推进且内存、磁盘空间充足；两次运行条件和系统负载未严格控制，不据此归因于代码性能变化。测试后 `integration-tests/.tmp` 已清理，固定测试端口未见监听。本轮是多仓单组复测，未重跑 Linux 四组完整回归或其他平台。

## Docker 凭据权限复核

提交 `c602c12` 修复 Docker `up.ps1` 在已有受保护 `.env` 上重复授权时要求 `SeSecurityPrivilege` 的问题，同时把凭据写入移到 ACL 收紧之后。空白新文件与重复授权均经无凭据临时文件测试；实际 Compose 使用已有 `.env` 完成 `up.ps1 → doctor.ps1 → down.ps1` 两轮，Doctor 每轮 **9/9 PASS**。`.env` ACL 读回为关闭继承、仅当前用户一条 FullControl 允许规则；启动输出不含 Token。Compose 容器已移除，命名数据卷保留，原有独立容器仍健康。未下载或安装依赖；显式 SecureString Token 参数分支未单独端到端复测。

## 最近基线完整复核

2026-09-23 在提交 `0f0e076` 上，将 Windows 源码同步到已有 WSL 测试副本后执行 `./integration-tests/run-linux.sh`，统一入口实际重新编译服务端。四组 **4/4 PASS，总耗时 710.19s**：Multi-repository 596.43s、Hosted 46.42s、Proxy 45.70s、Repository sync 21.56s。多仓组含先前新增的篡改制品拒绝、同缓存恢复、单并发双拒绝、独占命名空间 404/401/403/500 矩阵等断言，因此这轮不再仅依赖 `662935d` 的专项单组结果。测试后固定端口无监听，`integration-tests/.tmp` 不存在。耗时与先前 103.30s 的环境条件不同，不据此推断产品性能退化。

同一提交随后使用本地已有 `ubuntu:22.04` 基础镜像和 WSL 编译产物执行 `deployment/docker/up.ps1 → doctor.ps1 → down.ps1`，**9/9 PASS**。启动输出未回显 Token；本轮 Compose 容器和网络已移除，命名卷保留；用户独立容器 `magical_bartik` 仍健康。此复核没有重跑真实发布及持久化重建场景，那些证据仍以 `docs/docker-verification.md` 的历史完整流程为准。Windows 当前原生构建与完整 Maple HLT/LLT 仍未通过本轮验证。

## 菱形依赖图专项复核

提交 `add0849` 新增第三个跨仓夹具 `meshleaf`。根应用同时依赖 `meshbridge` 与 `meshleaf`，两条分支汇聚到同一个 `meshdep`。相容场景中，`meshbridge 1.0.0` 来自低优先级仓，`meshleaf 1.0.0` 和 `meshdep 1.0.0` 来自高优先级仓；测试核对三个运行标记，以及三条来源记录的版本、仓库地址和实际制品 SHA-256。冲突场景让 `meshbridge 2.0.0` 要求 `meshdep 2.0.0`，而 `meshleaf 1.0.0` 要求 `meshdep 1.0.0`，解析必须明确失败。

2026-09-23 在 WSL 2 / Ubuntu 22.04.5 中，直接对 Windows 工作区执行 `python3 integration-tests/run.py --suite multirepo --cjpm <现有增强版 Linux 二进制> --server <现有服务端 Linux 二进制> --skip-server-build`。新增成功和冲突场景、其余既有多仓断言均 **PASS，多仓组 147.98s，入口总耗时 151.42s**。本轮复用已编译二进制，没有重编译 cjpm 或服务端；固定测试端口与 `integration-tests/.tmp` 结束后均无残留。它属于最新测试内容的多仓单组专项，不替代 `0f0e076` 的 Linux 四组、Docker 9/9，也不解决 Windows 或完整 Maple HLT/LLT 缺口。

## 最新测试内容的完整回归

2026-09-23 在提交 `e5be054` 上，直接从 Windows 工作区的 WSL 挂载路径执行 `integration-tests/run-linux.sh`。入口使用已有增强版 Linux cjpm，**实际重新编译当前工作区的 CjRepo Server**，随后四组 **4/4 PASS，总耗时 184.08s**：Multi-repository 151.12s、Hosted 12.87s、Proxy 10.72s、Repository sync 5.97s。多仓组包含新增的菱形相容选源、三包来源和 SHA-256 核对、菱形冲突拒绝；其他既有故障与安全断言也通过。运行后固定测试端口和 `integration-tests/.tmp` 无残留。本轮未重编译 cjpm；从 `0f0e076` 至 `e5be054`，`cjpm/`、`server/` 与 `deployment/` 的产品源码无差异。

随后运行标准 `deployment/docker/up.ps1 → doctor.ps1 → down.ps1`，**9/9 PASS**。打包脚本使用已有 WSL 服务端产物 SHA-256 `5cedbde24bf02f71d0a68da50808af9b639d6b04da4d10af9034a88c53ac44de`，不是上述刚在 Windows 挂载路径重编译的产物；这两个产物的摘要不同，不能宣称字节相同。标准启动流程未回显 Token，Compose 容器与网络已移除，命名数据卷保留，原独立容器 `magical_bartik` 仍为 healthy。本轮 Docker 只复核一键启动和 9 项诊断，未重跑历史真实发布及持久化重建场景。Windows 原生五组与完整 Maple HLT/LLT 仍未解决。

## 官方 Maple 选定用例复核

2026-09-23 取得官方 `cangjie_test_framework` 提交 `e92721e2000c00c19701d4df2ac9e42e7921fe5c`，通过 `integration-tests/compatibility/maple_smoke.py` 对官方 `http_status_matrix.info` 和三个配置用例在原版与增强版 cjpm 上分别运行，首次均 **1/1 + 3/3 PASS**。测试只在 HTTP 用例的临时副本中规范 Windows 检出的 CRLF；官方 Git 跟踪文件不变。

再扩展官方 `central_repository_missing.info` 后，发现增强版改变了旧缺仓提示，虽然同样拒绝安装，仍使官方断言失败。`cjpm/src/implement/depot.cj` 已针对纯旧 `home`/`cache` 空 registry 配置恢复旧提示（对应代码提交 `0aae9ea`）。重新编译的增强版二进制 SHA-256 为 `6336f0bd1c973c4128717d7684ab13cdc3dce0840b9b8793aa5e599a00dca62a`，原版 SHA-256 为 `2f624cbe5493fcc686611e22eef7eb30e317c1ec589c18980dd88892875d9646`。新一轮 Maple 判定原版 HTTP **1/1 PASS（46.33s）**、配置 **3/3 PASS（4.11s）**、缺仓 **1/1 PASS（1.39s）**；增强版 HTTP **1/1 PASS（45.86s）**、配置 **3/3 PASS（4.03s）**、缺仓 **1/1 PASS（1.25s）**。原始日志在外层 `test-runs/maple-smoke/run-1790168948-56463991/`。HTTP 的 1/1 是单个 `.info` 用例，不能与夹具内部 16 条断言相加为 17 个官方用例；完整 HLT/LLT 仍未运行。WSL Python 环境仍缺 `pexpect` 和 `fasteners`。

同一新编译 cjpm 又从 Windows 工作区的 WSL 挂载路径运行 Linux 共享核心入口，复用已有服务端二进制，四组 **4/4 PASS，总耗时 161.42s**：Multi-repository 136.29s、Hosted 5.82s、Proxy 10.66s、Repository sync 5.43s。官方原版单仓差分 **7/7 PASS**，HTTP 状态夹具逐条断言两版各 **16/16 PASS**。本轮没有重跑 Docker、Windows 原生五组或完整 Maple HLT/LLT；Docker 9/9 仍引用前述 `e5be054` 验证。

## Maple 七用例扩展与不稳定夹具排查

2026-09-23 增加官方缓存安装及 Git 无效配置用例后，`integration-tests/compatibility/maple_smoke.py` 在原版与增强版 cjpm 上各 **7/7 PASS**：HTTP 状态 1/1、配置 3/3、缺仓 1/1、缓存安装 1/1、Git 无效配置 1/1。两版二进制 SHA-256 未变；逐例日志在外层 `test-runs/maple-smoke/run-1790170871-2e498703/`。测试只覆盖选定 LLT，不代表完整 HLT/LLT。

单独探索的官方制品异常矩阵首次为原版 PASS、增强版 FAIL，增强版未改夹具复跑 PASS。失败点是 `wrongpkg` 的哈希校验；官方夹具每次请求动态创建 gzip 压缩包，本地验证其跨秒产生不同时间戳字节及 SHA-256，因此不能把原始夹具的单次通过记作稳定通过，也不据此修改或放松产品哈希检查。之后仅在临时测试副本固定 gzip mtime 为 0，Maple 对同一制品矩阵判定原版 **1/1 PASS（10.64s）**、增强版 **1/1 PASS（9.57s）**，日志在外层 `test-runs/maple-smoke/run-1790171311-a4644d17/`，并附有原始和稳定化脚本的 SHA-256。这个 **1/1 不计入七个未改测试逻辑的选定用例**，不宣称原始夹具稳定通过。未重跑 Linux 四组或 Docker，因为本轮只修改测试入口与说明，未修改产品代码。

随后新增官方 Git 分支/标签/提交安装、workspace 安装与两个更新错误配置用例。统一入口在原版与增强版上各 **11/11 PASS**（HTTP 1、配置 3、安装 5、更新 2）；仅稳定化测试副本的制品矩阵另各 **1/1 PASS**。本轮逐例日志与夹具调整摘要在外层 `test-runs/maple-smoke/run-1790171957-a31a42db/`。两版二进制摘要未变；这轮没有改产品源码，也没有重跑 Linux 四组、Docker 或 Windows。

随后把官方 `install/local` 的十七个 `.info` 全数纳入入口。首次探索把 `HOME` 指向隔离目录却未把其 `.cjpm/bin` 加入 `PATH`，导致原版 **15/17**：两个安装后的命令调用报 `command not found`；补齐隔离路径后，原版和增强版探索分别 **17/17 PASS**。最终统一入口每版使用独立临时 `HOME`，测试期间将相应 `.cjpm/bin` 放入 `PATH`，避免写入用户日常仓颉安装目录。统一回归原版与增强版各 **28/28 PASS**（HTTP 1、配置 3、安装覆盖 5、本地安装 17、更新 2），稳定化制品矩阵另各 **1/1 PASS**。逐例日志与夹具调整摘要在外层 `test-runs/maple-smoke/run-1790174668-ce1149a9/`。两版二进制摘要未变，未改产品源码；Linux 四组、Docker、Windows 原生五组及完整 Maple HLT/LLT 未因这次入口扩展而重跑。

再次纳入官方 `uninstall` 四个用例：隔离 `HOME` 的探索运行两版各 **4/4 PASS**；统一回归原版与增强版各 **32/32 PASS**（HTTP 1、配置 3、安装覆盖 5、本地安装 17、卸载 4、更新 2），稳定化制品矩阵另各 **1/1 PASS**。日志在外层 `test-runs/maple-smoke/run-1790175442-0c33ee03/`，两版二进制摘要未变。官方 `install/git` 两例被官方 `testlist` 显式排除，探索入口只提示不在清单，未强行计入通过数。本轮仍未修改产品源码或复测 Linux 四组、Docker、Windows 原生五组及完整 Maple HLT/LLT。

本轮扩展官方 `update/coverage` 七个用例，其中 `local_index_refresh` 使用仅监听 `127.0.0.1:39138` 的测试服务，入口仅在临时副本规范该夹具 Windows 检出文件的 CRLF。两版统一运行各 **39/39 PASS**（前述 32 项加更新 7 项），稳定化制品矩阵另各 **1/1 PASS**。逐例日志与夹具调整摘要在外层 `test-runs/maple-smoke/run-1790176547-80305f39/`。两版二进制摘要未变，产品源码及官方测试仓跟踪文件未改；Linux 四组、Docker、Windows 原生五组和完整 Maple HLT/LLT 本轮未复测。

本地官方测试快照仍有大量未覆盖用例：CJNATIVE cjpm LLT 773 个 `.info`、HLT cjpm 157 个 `.info`，上述通过数只是子集。部分 HLT 发布用例会携带测试凭据向外部中心仓执行 `cjpm publish`，本轮未运行，也未在报告中披露凭据。完整 HLT 需要先明确可用的隔离测试仓和写入授权。

## 可选私有读取鉴权

2026-09-23 为 CjRepo Server 增加 `CJREPO_READ_TOKEN`：显式设置时保护 Hosted/Proxy 的索引和制品请求，未设置时保持原有公开读取，`/health` 不受影响。服务端在触碰本地缓存或发起上游请求前先校验原始 `Authorization` 值，故无令牌/错误令牌均返回 401，不能用 Proxy 触发未授权上游流量。客户端继续使用已实现的 `token-env`；仓间 Sync 从私有源仓读取时使用 `CJREPO_UPSTREAM_TOKEN`，目标发布仍使用独立令牌。

用增强版 cjpm SHA-256 `6336f0bd1c973c4128717d7684ab13cdc3dce0840b9b8793aa5e599a00dca62a` 在 Windows 挂载工作区的 WSL 2 / Ubuntu 22.04.5 中真实编译新服务端，Linux 服务端二进制 SHA-256 `f08a1e560e1d17ea98d89f00937bf6ab9f96e93b4551d131481ffcb2144053d6`。Hosted 专项 **1/1 PASS（28.01s）**，验证公开读取兼容、私有索引与制品拒绝无效令牌、有效令牌下 cjpm 编译运行。随后复用该新服务端执行 Linux 四组：**4/4 PASS，总计 176.45s**，多仓 145.20s、Hosted 10.94s、Proxy 11.00s、Sync 5.77s。再扩展 Proxy 未授权 MISS 不触发上游、授权离线 HIT，以及私有源仓 Sync 拒绝缺令牌后，Proxy/Sync 专项 **2/2 PASS，总计 31.59s**（23.58s、6.00s）。PowerShell 启动脚本语法与 Compose 配置静态检查通过；本轮 Docker 引擎未运行，未执行实际镜像构建/容器诊断。Windows 原生最新五组仍受 Application Control 阻断，完整官方 Maple HLT/LLT 未重跑。

2026-09-24 开机后重启项目 WSL 与 Docker Desktop，修正“只配置读取令牌、却允许匿名发布”的风险：此配置现在于服务启动前返回错误；制品缓存存在性判定移到读取鉴权之后。新服务端在 WSL 真实重编译后 SHA-256 为 `afb896fd886525dc91ff01b9eadb3731e632e7defcbfbe8b74db5d488902d61f`，四组核心回归 **4/4 PASS，总计 189.09s**：多仓 147.03s、Hosted 20.91s、Proxy 11.50s、Sync 6.17s。测试包含拒绝不安全配置、私有 Hosted 下载、Proxy 未授权 MISS 不访问上游、授权离线 HIT，以及私有源仓 Sync。新增 Docker 打包参数显式指定此二进制，打包文件 SHA 与源文件一致；Docker 当前镜像诊断 **9/9 PASS**。临时启用随机读取令牌后，容器中索引和制品请求无令牌均返回 401，正确令牌下缺失资源均返回正常 404；随后通过正式 `up.ps1 -ReadToken` 与 `up.ps1 -DisableReadToken` 验证鉴权生效及公开读取恢复，最终诊断 **9/9 PASS**。Compose 服务和命名卷保留运行，独立容器未启动或修改。Windows 原生五组与完整官方 Maple HLT/LLT 本轮未复测。

同日新增并运行隔离 Docker 持久化专项 `integration-tests/docker_persistence.py`：独立临时 Compose 项目中，未经授权的读取与发布返回 401；授权发布后索引及合成制品可读；强制重建容器后两者仍在且制品 SHA-256 一致，重复发布返回 409。**专项 PASS**，其容器和卷已清理；原项目容器再次诊断 **9/9 PASS**。合成制品专项不代替真实 cjpm 发布/安装或最终提交上的全量回归。

继续处理官方测试覆盖缺口：筛出 `repo/bundle` 23 个本地 LLT（不运行外部发布），用官方原版与增强版分别逐例执行，**两版各 23/23 PASS**；46 份日志在外层 `test-runs/maple-bundle/bundle-1790223696-c5626f35/`。这是先前 39 项之外的独立选定批次，不等于完整 Maple。Windows 侧已确认本机 `D:\Apps\Cangjie\bin\cjc.exe` 仍为 `NotSigned`，先前 Code Integrity 3077 事件明确阻断它；仓库代码或测试脚本无法给该工具链签名。当前继续以 Linux 原生回归作产品验证，不关闭系统安全策略，也不把 Linux 结果冒充 Windows 原生五组。

同日再运行官方本地 `tree` **17 项**、`organization` **12 项**，原版和增强版每批均全通过；34 份依赖树日志和 24 份组织名日志分别保存在外层 `test-runs/maple-tree/tree-1790224129-a37bb849/`、`test-runs/maple-organization/organization-1790224256-52fb157b/`。隔离临时目录已清理。组织名批次只覆盖本地路径依赖，不外推为服务端组织仓支持。

组织名边界审查发现服务端原本仅按 URL path 分发，`?organization=demo` 被忽略，会把请求导向默认仓已有索引/制品。修复后默认仓的索引、制品和发布端点拒绝任何查询参数（400）；私有读取先验令牌，无令牌仍为 401。Hosted 测试覆盖明文、空值、编码组织名及其他查询参数，Proxy 测试确认拒绝后不访问上游。服务端真实重编译，SHA-256 `bd424b79d39ebd47d550a8130fa7d06a444babe62e2fe3496751796ed3c353af`；Linux 四组 **4/4 PASS、176.32s**（多仓 142.77s、Hosted 13.69s、Proxy 10.81s、Sync 5.51s）。当前二进制已打入 Docker 镜像，主项目容器诊断 **9/9 PASS**；在保留数据卷的容器上，同一默认仓包无查询请求为 200、带组织查询为 400。独立 Docker 私有仓持久化专项含组织查询断言再次 PASS。此修复是“未支持组织仓时拒绝错误路由”，并非实现组织仓。

随后在 Hosted 模式实现命名 organization：仅接受合法 `?organization=<组织名>`，核对发布元数据和索引组织身份，并按组织分目录存储；默认仓继续使用无查询请求。Proxy 仍拒绝组织查询。使用真实增强版 cjpm 完成组织包 `bundle → publish → run`，并从启用读取鉴权的组织仓通过 `token-env` 拉包运行。Linux 四组回归 **4/4 PASS、184.28s**（多仓 140.19s、Hosted 24.43s、Proxy 10.65s、Sync 5.52s），随后仅追加私有组织仓客户端夹具，Hosted 专项 **PASS、43.10s**。服务端二进制 SHA-256 `9c9aac3ed913cbcb4fdb0a0728fb64dc652aed77af7beabb82a52a3036c97c50`；当前 Docker 镜像诊断 **9/9 PASS**，隔离容器内默认仓与同名同版本组织仓均能发布、隔离读取、容器重建后保留并分别拒绝重复发布（409）。

随后 Proxy 也实现命名组织仓：代理把规范化组织参数传给上游，索引与制品按组织分区缓存，上游索引组织身份不匹配时返回 502 且不落盘，制品须匹配同组织缓存索引的 SHA-256。真实增强版 cjpm 经 Proxy 拉取 Hosted 组织包并运行；停止 Hosted 上游后清理客户端缓存，再次经 Proxy 缓存构建运行。Linux 四组 **4/4 PASS、219.88s**（多仓 155.23s、Hosted 29.20s、Proxy 25.73s、Sync 5.90s）；加入错组织上游索引拒绝断言后，Proxy 专项 **PASS、37.54s**。服务端二进制 SHA-256 `5fbb27e6effe719234eee31a58c4a1876ad9d16c97b2d157d223e2b5444500f5`，当前 Docker 镜像诊断 **9/9 PASS**，隔离私有仓/组织仓持久化专项 **PASS**。Mirror/Sync 仍只覆盖默认仓。

最终补齐 Mirror/Sync 命名组织仓：单项命令和原有两列清单均接受 `组织名::包名`，索引/制品按组织分区，源索引组织身份和制品 SHA-256 仍严格校验。组织包的镜像与同步均验证幂等跳过，停止源仓后目标仓能由真实增强版 cjpm 编译运行组织应用。Linux 四组 **4/4 PASS、236.04s**（多仓 154.62s、Hosted 32.01s、Proxy 27.71s、Sync 17.42s）。Docker 构建上下文中服务端 SHA-256 `09f956b0399c3b00ae71f122ece3d1c87a95d90c2ffd464fa78aa3dd8dafe4d4`；主容器沿用原 `.env` 与数据卷更新，诊断 **9/9 PASS**，新版镜像隔离私有默认仓/组织仓持久化专项 **PASS**。尚未覆盖当前版本 Windows 原生运行、按包细粒度锁、自动调度和断点续传。

其后将 Hosted 发布和 Proxy 缓存填充的进程级全局锁改为固定 256 个锁分片，按存储目录、组织和包名计算分片。同包并发发布仍为一成功一冲突，八个同包 Proxy 首次请求仍只触发一次上游填充；新增慢上游夹具证明第二个不同包在慢包结束前已访问上游。分片数量有界，不随公开请求中的包名数增长；哈希碰撞的不同包仍可能串行，因此不称“每包独占锁”。Proxy 专项 **PASS、315.19s**；最终 Linux 四组 **4/4 PASS、1686.09s**（多仓 1064.53s、Hosted 220.79s、Proxy 242.95s、Sync 119.47s）。本轮 WSL 构建/夹具明显变慢，测试仍完整运行，不将总耗时与前轮作为性能对比。最终服务端二进制 SHA-256 `191f4e2a982a277424c6d279b2d6b2633a477e40168c6bdeea51dcb952e202a8` 已进入 Docker 镜像；`doctor.ps1` **9/9 PASS**，独立私有仓/组织仓持久化专项 **PASS**。当前版本仍缺 Windows 原生验证、自动调度和断点续传。

电脑重启后核对 Docker Desktop 已运行，`cjrepomesh-cjrepo-1` 自动恢复且 `doctor.ps1` **9/9 PASS**；仓颉 WSL 发行版从停止状态启动，`cjc`、stdx、增强版 cjpm 和 Python 均可用，未启动无关容器。继续完成 Sync 真正的增量预检查：同步前比较 Source 与 Destination 索引，同版本同 SHA-256 跳过源制品下载，同版本不同 SHA-256 在下载前报冲突；并发发布返回 409 时重新核对目标校验和。私有目标仓读取和发布令牌分离。更新后的 Sync 专项 **PASS、174.09s**，覆盖禁止制品读取的源仓仍可跳过、校验和冲突无制品请求、私有目标仓缺读取令牌 401、读写令牌齐全后发布与幂等重跑，以及组织仓和源仓离线构建。随后最新代码的 Linux 四组完整回归 **4/4 PASS、1212.36s**（多仓 772.85s、Hosted 155.69s、Proxy 164.47s、Sync 90.94s）；总耗时包含本机 WSL 夹具编译，不能据此推断服务性能。服务端二进制 SHA-256 `2ee15bd2c684e4956fe962973a5339b3a694e6986d0fc08d6696846145c658b8` 已打包部署，容器内指纹一致；Docker 诊断 **9/9 PASS**，新版镜像隔离私有默认仓/组织仓持久化专项 **PASS**。

随后增加 `mirror-watch` 与 `sync-watch`：输入清单及 1–86400 秒轮询间隔，每轮重新读取清单，新增版本按现有校验逻辑处理，失败轮次下轮重试。Sync 专项用后台进程验证运行中修改清单后，默认仓两个版本依次镜像并同步；无效间隔拒绝，进程被停止后测试端口关闭。专项 **PASS、176.66s**；最终重新编译并执行 Linux 四组 **4/4 PASS、1248.48s**（多仓 784.32s、Hosted 166.54s、Proxy 173.61s、Sync 94.40s）。当前二进制 SHA-256 `aa44264497d01fe1ff3d9cf78b1dcb06bc5aeaed192db29571707ea10d71f8a3` 已进入 Docker 镜像且与容器内一致，主容器保留原 `.env` 与数据卷更新；诊断 **9/9 PASS**，隔离私有默认仓/组织仓持久化专项 **PASS**。此功能是单进程周期轮询，不包含持久化游标、字节级断点续传、多实例协调或 watcher 的开机托管；当前版本 Windows 原生验证仍受本机工具链签名问题阻断。

随后发现 Mirror 单项镜像原会把上游完整索引直接写到本地，但只下载指定版本，造成未镜像版本被错误公开。修复为只合并本地已有且 SHA-256 正确的条目，先原子写入制品、再原子更新索引；对旧版缓存，重访一个有效版本时可在上游关闭的状态下清理未落盘条目。Sync 专项新增稀疏镜像和旧缓存离线修复断言，**PASS、205.69s**。最终 Linux 四组重新编译回归 **4/4 PASS、1267.28s**（多仓 771.16s、Hosted 161.87s、Proxy 192.60s、Sync 114.32s）。服务端 SHA-256 `9347140e8436183114c01e79c97a795508b695dd84fe455d2b6d05a47d65d87b` 已部署进原项目容器，容器内指纹一致；Docker 诊断 **9/9 PASS**，隔离私有默认仓/组织仓持久化专项 **PASS**。镜像写入仍无跨进程分布式锁；多实例同时更新同包不在此次保证范围。

2026-09-25 开机后，Docker Desktop 已运行，原项目容器沿用镜像、`.env` 和命名数据卷恢复，`doctor.ps1` **9/9 PASS**；`CjRepoMesh` WSL 发行版启动，SDK、stdx、增强版 cjpm、服务端产物和 Python 可用。随后官方 Maple 本地 `workspace` 52 个 LLT 用例，原版与增强版分别 **52/52 PASS**；逐例日志共 104 份位于外层 `test-runs/maple-workspace/workspace-1790309933-28de5678/`。入口预检无外部发布/URL 操作，测试在隔离 `HOME` 运行，官方测试仓和产品源码未改。此批与先前选定批次分别运行，不合称完整 HLT/LLT；当前环境仍缺 `pexpect`、`fasteners`，Windows 最新原生五组仍受未签名工具链阻断。
