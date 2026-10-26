# CjRepoMesh 参赛演示 Runbook

## 2026-10-26：固定候选与最后复演

功能冻结在代码`93ee96f3`对应的客户端`5dd187b5…`、服务端`8b34570e…` / 镜像`722ffc3c…`，完整摘要以[候选清单](candidate-acceptance.md)首节为准。本次未重建产物，已有七阶段流程在隔离Linux目录实际通过 **7/7，41.41秒**；客户端21文件、服务端9文件及产品源码输入校验保持。运行环境使用已有SDK/stdx；没有执行Windows仓颉程序。

复演命令和五个回环端口说明见[运行入口](../integration-tests/showcase/README.md#运行)。Linux原生演练需要现有、摘要匹配的服务端ELF；服务端离线容器包的首次接收另按[操作说明](operations.md#固定双包的首次接入)执行，不能把ZIP或image.tar当作ELF传入。先查看本轮`summary.md`和`summary.json`，再按下表讲解；41.41秒是自动运行耗时，6～8分钟是讲解建议，不是性能承诺。

真人复演尚未确认：用自己的演示屏幕走一次“内部包保护 → 401阻断 → 停源构建 → 同步与独立副本 → 离线解释”，能说明失败是预期保护、缓存必须预热，以及依赖解析记录不等于完整构建凭证。现场只展示脱敏摘要，不直接公开原始日志、令牌或机器路径。

本轮不制作PPT或新视频。此前平台、正式视频、签字PDF及邮件成功状态沿用参赛者确认；本轮没有重新核验最新决赛通知、截止时间或平台外链。如组委会另有新增硬性要求，单独按实际通知核对，不从下方历史录制方案推定。

## 连贯场景与源码讲解（沿用2026-10-21流程）

当前优先展示一条有实际结果的完整流程，入口为 [`integration-tests/showcase/run.py`](../integration-tests/showcase/run.py)，环境、命令和输出见[演练说明](../integration-tests/showcase/README.md)。它自动启动自己的本机服务，生成真实仓颉包，在关键阶段更换全新应用缓存，并保存运行标记、来源、归档摘要与请求日志。

可按 6～8 分钟讲解，等待时间以现场实际为准，不把测试耗时当作产品性能指标：

| 建议时间 | 展示与讲解 |
| --- | --- |
| 约 1 分钟 | 企业内部包不能公开，同名公共高版本可能被选中，公共上游也可能停止服务；给出本地合成场景边界 |
| 约 2 分钟 | 对照公共 `auth 9.0.0` 与保护后的内部 `auth 1.0.0`；普通 `meshdep` 仍选择兼容的新版本 2.0.0，说明优先级不等于强制旧版本 |
| 约 1 分钟 | 错误令牌导致 401，构建必须失败；公共入口没有请求，证明没有为了“构建成功”绕开私有仓 |
| 约 1～2 分钟 | 上游停止后全新客户端仍能从已校验的 Proxy 缓存构建；同步到另一个私有仓，再关闭原仓，从新缓存仅用副本构建 |
| 约 1 分钟 | 关闭所有仓，展示 recorded explain 的版本、来源与摘要；说明限制与实际修复 |

### 从现象找到代码

1. **“这究竟解决什么问题？”** 给现有 cjpm 增加去哪些仓、允许怎样回退以及最终从哪取包的能力；再提供轻量私有仓、代理和复制。开发者继续用 cjpm 构建，包版本与依赖冲突仍由原求解过程处理。
2. **“为什么提高私有仓优先级还不够？”** 不同仓的兼容版本会进入候选集合；优先级只决定同一版本的来源。`company::*` 的 `exclusive` 路由从候选仓列表中排除公共仓，才保护内部命名空间。看 [`RepositoryRouter.getDepots`](../cjpm/src/implement/depot.cj) 与 [`dep_engine.cj`](../cjpm/src/implement/dep_engine.cj) 的版本来源聚合。
3. **“为什么 401 不继续尝试公共仓？”** 认证失败不能被其他来源掩盖。`RepositoryRouter.canContinueAfter` 明确只允许 404 和服务错误继续尝试；独占路由本身也不会提供公共候选。看 [`depot.cj`](../cjpm/src/implement/depot.cj) 和 [`central_repository.cj`](../cjpm/src/implement/central_repository.cj)。演练用新缓存并观察公共入口，避免把旧缓存成功当成回退安全。
4. **“离线构建有什么前提？”** Proxy 中必须已有可用索引和已校验制品；此次先预热，再停指定源服务，用新客户端缓存构建。Sync 将真实制品复制到另一仓并校验重复同步；它是可独立使用的副本，不是自动故障切换。看 [`proxy.cj`](../server/src/proxy.cj) 与 [`sync.cj`](../server/src/sync.cj)。
5. **“来源记录证明什么？”** 记录本次最终包、版本、仓库和 SHA-256，可在所有仓停止后读取；recorded explain 不会重新求解或联网确认远端现状。摘要证明字节与记录匹配，不能单独证明发布者可信；可信索引、访问控制和部署传输保护仍然必要。看 [`provenance.cj`](../cjpm/src/implement/provenance.cj) 与 [`doRepoExplainRecorded`](../cjpm/src/implement/repo.cj)。
6. **“本次发现了什么实际问题？”** 全新 Proxy 同时下载不同组织的包，包锁各自独立，却会同时创建共享祖先目录，Windows 实际返回 `File exists` 和 502。修复为 [`storage.cj`](../server/src/storage.cj) 的短时目录锁，Hosted/Proxy/Mirror/Sync 统一调用；网络和制品写入仍在锁外。演练以并发发布和冷 Proxy 构建覆盖该路径，另保留独立的不同包并行回归。

现场展示以实际产生的 `summary.md` 和对应原始日志为依据；401 是预期保护结果，整场成功也不表示所有错误或完整官方测试都已覆盖。最新产物与平台结果见[验证记录](verification-report.md)，不把自动运行报告当成真实屏幕录像。

讲解来源记录时应称为“依赖解析记录”。它在依赖解析与下载完成后、编译之前写入，不能单独充当整个构建成功的凭证。2026-10-21 保留应用产物的专项7/7通过，其中故意制造编译类型错误，实际确认构建失败时来源记录仍已更新为本次解析结果；该错误为受控测试夹具。

初赛正式视频约 5 分 39 秒，参赛者已确认可播放，提交邮件也已确认投递成功。这些是已完成的材料状态；本节没有生成新的决赛视频或 PPT。

## 以下为 2026-09-25～09-26 历史录制方案

以下“待录制”“Windows 被阻断”等描述只反映当时状态，不代表现在的材料或测试状态。

> 目标：6～8 分钟主视频，另留完整无剪切验证录像。
>
> 核心叙事：仓颉原生的多仓解析层与企业私有仓闭环，而不是“又一个制品仓”。
>
> 状态：这是待录制脚本，不表示视频已经完成。证据以录制时的提交号和当次结果为准。

### 已生成的辅助片段（不能替代原始录像）

2026-09-25 已用 `submission/render_doctor_clip.py` 对当次重新运行的 Docker Doctor
9/9 PASS 输出生成 44 秒、1280×720 的演示重放。素材留在外层
`test-runs/video/doctor-proof-2026-09-25.mp4`，未入 Git；画面明确标注“实测输出重放 / 非连续屏幕录像”。
它可以作为主视频中的说明性镜头，但不能充当无剪切验证视频，也不能证明片段外的功能。
脚本每次会重新执行 Doctor，任何一项不是 PASS 就不生成片段；编码器通过 `--ffmpeg` 指定，
输出通过 `--output` 指定。
同日还用完整 4/4 PASS 的带时间戳日志生成 64 秒安全边界重放，以及约 4 分 04 秒、
不剪速的完整终端输出回放。后者逐事件沿原始时间轴播放，不是 Windows/WSL 桌面的真实录屏；
可与外层 `test-runs/video/linux-core-current-2026-09-25/output.log` 和 `timing.log` 核对。
这两段仍只是辅助证据，不能勾销下文要求的主视频和实际屏幕无剪切录像。
目前已把片头、Doctor、安全边界、完整终端回放和片尾拼成外层
`test-runs/video/main-review-draft-2026-09-25.mp4`，时长 7:00.42、1280×720，
无旁白、无音轨。已抽帧和全片解码核验；它是审阅草稿，不是可直接宣称完成的参赛主视频。

2026-09-26 再次只读验收该文件：SHA-256 为
`255bd0633b20261461518337fb6ca924a76e0f85217b93456747bbca74d28c7a`；FFmpeg 7.1 识别为
H.264 High、1280×720、12 fps、7:00.42，仅有视频流，并完整解码 5046 帧，音频、字幕和其他流均为 0。
抽查片头、Doctor、安全边界、四组终端和片尾画面均可读，且回放性质有明确标注。画面内仍引用
2026-09-25 的历史证据提交，不能改名冒充当前提交的真实屏幕录像；正式视频仍需旁白或现场讲解，以及
按下文录制的当前提交真实操作画面。

## 证据边界与录制顺序

截至 2026-09-25，产品代码提交 `a1eb894` 的 Linux 四组核心回归曾 **4/4 PASS、1267.28 秒**；当天从当前源码重建服务端后 **4/4 PASS、255.51 秒**，又在 AtomGit 公开提交 `31567a61` 上重建并复核 **4/4 PASS、230.19 秒**，Docker 镜像内二进制与新构建产物 SHA-256 一致，Doctor **9/9 PASS**。隔离私有仓与组织仓持久化专项此前通过。官方 Maple 框架在原版与增强版分别跑通选定的 39 项，以及独立批次的本地打包 23、依赖树 17、组织名 12、workspace 52 项；各批分别通过，未统一运行，不能合称完整 HLT/LLT。另有制品异常矩阵仅在测试副本固定 gzip 时间戳后两版各 **1/1 PASS**。历史 Windows 五组曾 **5/5 PASS**，当前 Windows Code Integrity 拦截未签名 `cjc.exe`，不能宣称最新提交的 Windows 五组已通过。详见 [全量验证报告](verification-report.md)、[Docker 验证](docker-verification.md) 和 [官方兼容性报告](official-compatibility-report.md)。

先定稿并记录提交号，再录制完整无剪切验证过程，最后从同一次验证中剪出主视频片段。剪辑中的等待、跳转要明显标注；主视频中的 PASS、耗时与提交号必须能在无剪切录像或报告中找到对应证据。若最终提交后只改文档，也应明确验证所对应的代码提交，不把历史运行冒充最终提交复测。

录制前核对：

1. `git rev-parse --short HEAD` 与 `git status --short`；记录产品/测试代码提交，确认无凭据、缓存和构建产物入库。
2. 按 [Linux 验证](linux-verification.md) 的已有 SDK 环境运行 `./integration-tests/run-linux.sh`，保存四组完整输出。不要在 Windows 主机反复触发已知的 Code Integrity 拦截，也不要修改安全策略。
3. Docker Desktop、`CjRepoMesh` WSL 发行版、已编译 Linux 服务二进制和本地 `ubuntu:22.04` 镜像就绪后，仅操作本项目的 Compose 服务。`up.ps1` 在缺少基础镜像时可能拉取镜像；先检查并征得用户同意，不在录制时意外下载。保留用户已有的独立容器与数据卷。
4. 使用 `deployment/docker/up.ps1` 和 `doctor.ps1` 录制一键部署与 9 项诊断；`down.ps1` 仅关闭本项目 Compose 服务且默认保留数据卷。不要使用 `-PurgeData`。
5. 校对 [Proxy Benchmark 报告](../benchmark/results/proxy-benchmark.md) 与 [原始样本](../benchmark/results/proxy-benchmark.json)。旧数字只可标注其 2026-09-22 本机测试条件；若重新测量，先更新报告再引用。
6. 用 1080p 回看终端字体、架构图和字幕；清除桌面通知，检查画面中没有 `.env`、Docker 环境变量、任何认证 Token 或个人路径以外的隐私信息。完整验证录像和主视频目前均是待交付物。

## 主视频分镜（约 7 分钟）

| 时间 | 画面与要点 | 对应证据 |
| --- | --- | --- |
| 0:00–0:35 | 架构图；Router 聚合允许仓库的候选版本，原 cjpm 求解器选择版本；Hosted/Proxy/Mirror/Sync 构成私有仓闭环。 | [架构说明](architecture.md) |
| 0:35–1:20 | Docker Compose 一条命令启动、`/health`、Doctor 9 项。启动等待可剪辑，明确标注剪辑；不展示 Token。 | [Docker 验证](docker-verification.md) |
| 1:20–2:25 | 高优先级仓只有 1.0.0、低优先级仓有 2.0.0，最终选择 2.0.0；同版本再按仓优先级选源；跨仓传递约束与 SHA-256 来源核对。 | [Linux 四组回归](verification-report.md)、[跨仓测试](../integration-tests/lib/suites.py) |
| 2:25–3:20 | `company::*` 独占路由；公共仓故意放 9.0.0，最终只用私有 1.0.0；私有仓遇到 404/401/403/500 时，公共仓请求数仍为 0。 | [路由配置](../integration-tests/multirepo/app-namespace/cangjie-repo.toml)、[安全断言](../integration-tests/lib/suites.py) |
| 3:20–4:05 | Explain/Doctor/Recorded：选择原因、连接/认证诊断、离线来源及 SHA-256；区分独立审计文件与官方 lockfile。 | [验证报告](verification-report.md) |
| 4:05–5:05 | Proxy 并发首次填充、TTL、离线命中和损坏拒绝；展示本机冷/热基准并读出适用边界。 | [Proxy 测试](../integration-tests/lib/suites.py)、[基准报告](../benchmark/results/proxy-benchmark.md) |
| 5:05–6:05 | 清单批量 Mirror/Sync、逐项 SHA-256、幂等 SKIP、部分失败汇总与源仓离线后目标仓构建。 | [清单](../integration-tests/sync/mirror-manifest.txt)、[验证报告](verification-report.md) |
| 6:05–7:00 | 四项课题要求的对应关系、当前验证边界和下一步。显示真实提交号与报告，不把历史 Windows 5/5 说成当前结果。 | [提交检查表](submission-checklist.md) |

### 必说的三句话

> Priority 只在确定最终版本后决定同版本的来源，不覆盖原 cjpm 的版本求解。

> 独占命名空间缺包必须失败；仓库认证失败也不能回退。可用性机制不能越过安全边界。

> 当前 Linux 四组和 Docker 9 项诊断已通过，私有仓持久化也有实测。Maple 的 39 项选定用例及另批本地打包、依赖树、组织名、workspace 子集分别通过，但完整套件未运行。Windows 最新复测受本机代码完整性策略阻断，我们不会把这些缺口包装成通过。

## 演示画面与命令

从项目根目录，在前置条件满足、8080 端口可用且不会覆盖现有 Compose 服务时录制 Docker 部署：

```powershell
.\deployment\docker\up.ps1
.\deployment\docker\doctor.ps1
```

`up.ps1` 自动生成或复用保存在被 Git 忽略的 `deployment/docker/.env` 中的发布 Token，终端不回显其值；不要在命令行传明文 Token，也不要展示 `.env` 或 `docker inspect` 的环境变量。Doctor 应显示 9 项和 Overall 均为 PASS。若已有用户容器占用 8080，不停止它；选择空闲端口并按脚本 `-Port` 参数部署，或采用已录制的对应证据。

Linux 核心回归从已配置的 WSL Bash 中执行，环境准备见 [Linux 验证](linux-verification.md)：

```bash
./integration-tests/run-linux.sh
```

四组耗时受本机环境影响很大，最近一次完整重编译回归为 1267.28 秒；录制时要标明当次真实耗时及是否重编译服务端。主视频只截取相关断言与汇总，完整输出留在无剪切录像中。可展示 `highest compatible version across repositories`、`cross-repository diamond converges on one audited meshdep source`、`exclusive namespace dependency-confusion protection` 等 PASS 行；不要把报告中的旧行当作当次运行画面。Explain/Doctor/Recorded 的语义由测试夹具和报告支撑；录屏应展示实际输出，不只展示命令文字。

Proxy 基准报告中的 Cold Median **62.76 ms**（10 轮）、Warm Median **33.102 ms**（50 轮）、Median **1.9x** 均来自 2026-09-22 本机 HTTP 微基准，不代表公网官方仓或跨机延迟。Mirror 是显式清单镜像，不宣称完整复制官方中心仓；Mirror/Sync 仅有单进程周期轮询，不宣称持久化游标、字节级断点续传或多实例协调。

只关闭本次确实启动的 Compose 服务：

```powershell
.\deployment\docker\down.ps1
```

这会保留命名数据卷；不要对用户原有独立容器执行停止或删除。

## 失败切换

| 现场问题 | 立即动作 | 可用证据与不能说的话 |
| --- | --- | --- |
| Windows SDK/Code Integrity 阻断 | 保持安全策略原状，切到 Linux 或既有录像 | 展示当前 Linux 4/4、历史 Windows 5/5 并标明提交；不能说最新 Windows 已通过 |
| Docker 不可用、镜像缺失或 8080 被占 | 不触碰用户已有容器；换空闲端口或切录像 | 已提交 Docker 9/9 与持久化记录；不能把旧记录说成现场成功 |
| 某一组测试超时或失败 | 保留失败输出，标明本次失败；切换到历史报告 | 不能剪去失败段后宣称本次 PASS |
| 公网不可用 | 演示本地夹具与 Proxy 离线缓存 | 不能宣称公网官方仓实测 |
| Benchmark 波动 | 展示带日期的旧原始样本 | 不能现场编造新加速数字 |

任何失败都不得通过关闭安全功能、泄露凭据、删除校验或修改测试断言来“修复”。
