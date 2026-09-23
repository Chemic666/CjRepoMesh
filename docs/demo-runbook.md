# CjRepoMesh 参赛演示 Runbook

> 目标：6～8 分钟主视频，另留完整无剪切验证录像。
>
> 核心叙事：仓颉原生的多仓解析层与企业私有仓闭环，而不是“又一个制品仓”。
>
> 状态：这是待录制脚本，不表示视频已经完成。证据以录制时的提交号和当次结果为准。

## 证据边界与录制顺序

截至 2026-09-23，提交 `e5be054` 上 Linux 四组核心回归 **4/4 PASS，184.08 秒**，包含菱形依赖图与篡改制品场景；标准 Docker Compose 诊断 **9/9 PASS**。之后修复旧诊断并新编译增强版 cjpm，Linux 四组再获 **4/4 PASS，161.42 秒**（复用服务端构建）。三十九个选定官方 cjpm LLT 用例经 Maple 框架在原版与增强版上各 **39/39 PASS**；另有制品异常矩阵在测试副本固定 gzip 时间戳后两版各 **1/1 PASS**，完整 HLT/LLT 尚未运行。历史 Windows 五组曾 **5/5 PASS**，当前 Windows Code Integrity 拦截未签名 `cjc.exe`，不能宣称最新提交的 Windows 五组已通过。详见 [全量验证报告](verification-report.md)、[Docker 验证](docker-verification.md) 和 [官方兼容性报告](official-compatibility-report.md)。

先定稿并记录提交号，再录制完整无剪切验证过程，最后从同一次验证中剪出主视频片段。剪辑中的等待、跳转要明显标注；主视频中的 PASS、耗时与提交号必须能在无剪切录像或报告中找到对应证据。若最终提交后只改文档，也应明确验证所对应的代码提交，不把历史运行冒充最终提交复测。

录制前核对：

1. `git rev-parse --short HEAD` 与 `git status --short`；记录产品/测试代码提交，确认无凭据、缓存和构建产物入库。
2. 按 [Linux 验证](linux-verification.md) 的已有 SDK 环境运行 `./integration-tests/run-linux.sh`，保存四组完整输出。不要在 Windows 主机反复触发已知的 Code Integrity 拦截，也不要修改安全策略。
3. Docker Desktop、`CjRepoMesh` WSL 发行版、已编译 Linux 服务二进制和本地 `ubuntu:22.04` 镜像就绪后，仅操作本项目的 Compose 服务。`up.ps1` 在缺少基础镜像时可能拉取镜像；先检查并征得用户同意，不在录制时意外下载。保留用户已有的独立容器与数据卷。
4. 使用 `deployment/docker/up.ps1` 和 `doctor.ps1` 录制一键部署与 9 项诊断；`down.ps1` 仅关闭本项目 Compose 服务且默认保留数据卷。不要使用 `-PurgeData`。
5. 校对 [Proxy Benchmark 报告](../benchmark/results/proxy-benchmark.md) 与 [原始样本](../benchmark/results/proxy-benchmark.json)。旧数字只可标注其 2026-09-22 本机测试条件；若重新测量，先更新报告再引用。
6. 用 1080p 回看终端字体、架构图和字幕；清除桌面通知，检查画面中没有 `.env`、Docker 环境变量、Bearer Token 或个人路径以外的隐私信息。完整验证录像和主视频目前均是待交付物。

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

> Linux 四组和 Docker 部署已有实测通过；Maple 跑通三十九个选定官方 LLT 用例，另有一个仅在稳定化测试副本上通过。Windows 最新复测受本机代码完整性策略阻断，完整 Maple 套件未运行，我们不会把这些缺口包装成通过。

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

四组耗时受本机环境影响很大，最近一次为 161.42 秒（复用服务端构建）；录制时要标明当次真实耗时及是否重编译服务端。主视频只截取相关断言与汇总，完整输出留在无剪切录像中。可展示 `highest compatible version across repositories`、`cross-repository diamond converges on one audited meshdep source`、`exclusive namespace dependency-confusion protection` 等 PASS 行；不要把报告中的旧行当作当次运行画面。Explain/Doctor/Recorded 的语义由测试夹具和报告支撑；录屏应展示实际输出，不只展示命令文字。

Proxy 基准报告中的 Cold Median **62.76 ms**（10 轮）、Warm Median **33.102 ms**（50 轮）、Median **1.9x** 均来自 2026-09-22 本机 HTTP 微基准，不代表公网官方仓或跨机延迟。Mirror 是显式清单镜像，不宣称完整复制官方中心仓；Sync 不宣称调度或断点续传。

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
