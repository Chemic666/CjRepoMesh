# CjRepoMesh

> 面向仓颉与 cjpm 的原生多仓依赖和轻量企业私有仓基础设施

2026-10-21 客户端可靠性、离线交付及开发者/CI示例已同步至AtomGit和GitHub，两端内容一致、保留各自历史，见[交付记录](docs/delivery-record.md)。参赛者已授权后续阶段验收后自主双端推送；实际产物结果及Windows未测边界见[验证记录](docs/verification-report.md)。

2026-10-22 服务端补齐HTTPS上游与Sync目标：验证证书链及URL的DNS/IP身份后才发送HTTP，修复合法HTTPS未配置TLS的问题。最新6f5d服务端原生与465c镜像内专项各18/18，真实三组3/3、TCP14/14、跳转12/12及新离线包接收16/16。CA文件需单独配置，握手参数不是整体时限；入站网关、跨主机和新镜像冷恢复仍未验收，详情见[最新验证记录](docs/verification-report.md)。

当前固定客户端 `6a7b3acb…` 已完成[所列Linux候选范围的综合验收](docs/candidate-acceptance.md)：核心4/4、两组增量各7/7、旧单仓差分7/7、HTTPS15/15、网络14/14、脱敏10/10；Maple原断言38、就绪调整1、归档稳定化1、离线HLT95分别通过。无SDK来源查看13项、配置40项、运行8项及包接收为已核对的同一二进制有效证据，本轮未重复执行；完整Maple、Windows及跨主机验收仍未完成。

此客户端支持无SDK执行 `repo explain <包名> --recorded`，读取当前目录已有来源记录，保留配置、格式和安全地址拒绝；其他在线与构建命令仍需SDK。当前交付包不变，各历史候选结果分别保留。

前一c12运行状态修订使应用失败时 `cjpm run` 返回1，成功仍为0，不再错误报告完成；真实8项及多仓客户端组通过。该修复保留在新源码，最新实际回归见[验证记录](docs/verification-report.md)。

接收方已有离线包时，见[离线服务端交付](deployment/portable/README.md)：只用Python 3与Docker Compose即可导入、校验、配置和启动，服务端运行不依赖源码/仓颉SDK/开发机WSL。当前仅Linux amd64容器、本机监听与实例级读写令牌；不据此宣称内网HTTPS或完整企业生产验收已完成。

2026-10-22补齐服务端交付文件链接和悬空输出路径拒绝；Linux回归12/12，Windows Python9通过3跳过，并在隔离用户环境的Windows宿主实际接收12/12。新版服务端包更新接收工具，镜像和服务端未重建；仍使用既有Docker Desktop引擎，不冒充全新主机验收，见[验证记录](docs/verification-report.md)首节。

[开发者发布与只读CI示例](examples/team/README.md)提供独立任务目录：发布者构建上传私有包，消费任务仅用读取令牌编译运行，并记录实际来源与摘要。任务机需已有Linux仓颉工具链及增强版cjpm；服务端离线包不包含这些开发工具。

维护时参考[单实例升级与回滚](docs/upgrade-and-rollback.md)：停服快照恢复至新卷，并核对包内容、凭据和产物身份。两个固定Linux镜像已有隔离演练；从旧快照恢复会丢弃快照之后的发布，不承诺任意版本无损回退。

[容量样本](docs/capacity-report.md)提供固定资源下的并发、延迟、内存和数据完整性记录，帮助规划实际试用验证；当前是64包/256版本的本机合成热路径样本，不换算团队人数或生产容量上限。

HTTPS准备见[客户端身份与CA说明](docs/https-client.md)：本地修订核对DNS名称或IP SAN，并禁止自动跳转，已有真实CJP下载构建验证；成熟网关及跨主机HTTPS部署仍待验收。

前一综合验收产物 `af3516e8…` 修复保留target换仓仍运行旧程序的问题，覆盖源码路径身份、静态库内容指纹及传递静态链接；四组受控时间戳/三包回归和旧热缓存升级各7/7。同一产物另通过核心4/4、配置40/40、旧单仓差分7/7、HTTPS15/15、网络14/14、脱敏10/10；Maple原断言38项通过，刷新项就绪调整1项及归档稳定化1项分列。[Linux客户端离线包](deployment/client/README.md)已完成隔离接收验证，接收者无需编译cjpm，大多数命令仍需匹配SDK。摘要见[验证记录](docs/verification-report.md)。旧06ae的HLT95/95不移算给新产物；完整HLT/LLT及当前Windows原生验收仍未完成。

CjRepoMesh 对应仓颉生态创新开发挑战赛推荐技术课题 **#6 仓颉中心仓多仓配置与私有化体系建设**。项目在不重写 cjpm 版本求解器的前提下，增加公共仓、私有仓、代理仓和镜像仓之间的路由、优先级、安全回退、来源审计与同步能力，并提供仓颉原生的私有中心仓服务端。

## 为什么需要它

单一公共中心仓无法完整覆盖企业工程：内部包不能公开上传、内网需要缓存或镜像、公共仓故障不能阻塞所有构建，同名公共包还可能对私有命名空间形成 Dependency Confusion 风险。

CjRepoMesh 把两个问题明确分层：

```text
Repository Resolution                Dependency Resolution
去哪些仓、访问顺序、来源与回退   →   版本范围、冲突、传递依赖与最终依赖图
          CjRepoMesh                           原 cjpm
```

仓库优先级只决定同一最终版本从哪里下载，不会用高优先级仓的旧版本覆盖原求解器本应选择的新版本。

## 先看一次完整场景

[连贯演练入口](integration-tests/showcase/README.md)可以在已有 SDK 和构建产物上运行七个检查点：先看到公共同名高版本被选择，再启用内部命名空间保护；错误令牌必须阻断构建；关闭上游后从已校验的 Proxy 缓存构建；同步到私有副本，关闭源仓后用全新客户端缓存构建；最后所有仓停止，仍能解释已记录来源。

这是本地合成场景，使用真实 `cjpm bundle` 归档、编译与运行；无路由对照使用同一个增强客户端，不冒充官方原版比较。按[演示与代码讲解](docs/demo-runbook.md)可把每个结果对应到真实实现；实际平台结果和产物边界见[验证记录](docs/verification-report.md)。

## 官方要求完成情况

| 官方主要交付 | 当前实现 | 自动证据 |
| --- | --- | --- |
| 多仓配置及优先级查找 | 命名仓库、`priority`、`enabled`、`token-env`、确定性排序 | 多仓与旧配置兼容测试 |
| 多仓解析、冲突和强制替换 | 跨仓候选聚合、同版本选源、原生 `[replace]` | 版本/来源冲突及替换矩阵 |
| 私有中心仓一键部署 | Windows 构建、后台启动、健康诊断、安全停止、持久化重启 | Deployment 端到端测试 |
| 镜像、代理及仓间同步 | Proxy、批量 Mirror、批量 CjRepo-to-CjRepo Sync | 离线、损坏、并发、幂等和部分失败测试 |

赛事要求之外的冲奖增强包括：

- `exclusive` 私有命名空间隔离；
- 401/403 安全阻断，禁止认证失败后回退公共仓；
- `cjpm repo explain` 解释版本、来源、替换与路由；
- `cjpm repo doctor` 诊断连接、认证、元数据 API 和回退判定；
- `cjpm-provenance.json` 保存最终来源和 SHA-256，支持离线审计；
- 并发原子发布、Proxy 首次填充合并与索引 TTL；
- 保留原始样本的可重复 Proxy Benchmark。

## 架构

```text
Cangjie Project
      │  cangjie-repo.toml / cjpm.toml
      ▼
Repository Router
      │  namespace → allowed registries → priority → safe fallback
      ▼
Original cjpm Dependency Resolver
      │
      ├── download + SHA-256 ── repository-aware cache
      └── final source ───────── cjpm-provenance.json

      ┌─────────────── CjRepo Server ───────────────┐
      │ Hosted │ Proxy Cache │ Mirror │ Sync │ SHA-256 │
      └──────────────── Atomic Filesystem ───────────┘
```

完整组件关系、决策流程和代码地图见 [架构说明](docs/architecture.md)。首次使用、升级前保留项、故障恢复与卸载保留数据见 [操作说明](docs/operations.md)，当前产物的实测范围见 [验证报告](docs/verification-report.md)。

## 多仓配置示例

`cangjie-repo.toml`：

```toml
[repository.cache]
path = "./cache"

[repository.private]
registry = "https://repo.company.example"
priority = 100
token-env = "CJPM_PRIVATE_TOKEN"

[repository.mirror]
registry = "https://mirror.company.example"
priority = 80

[repository.official]
registry = "https://pkg.cangjie-lang.cn/registry"
priority = 10

[[route]]
namespace = "company::*"
registry = "private"
exclusive = true

[global]
strict-tls = true
```

`exclusive = true` 表示匹配包只能访问指定仓库。私有仓返回 404、401 或 5xx 时都不会越过边界访问公共仓。

强制版本继续使用 cjpm 已有配置，而不是引入第二套 Override 语义：

```toml
[dependencies]
meshdep = "[1.0.0, 3.0.0)"

[replace]
meshdep = "1.0.0"
```

## Windows 快速开始

前置条件：本机已经准备仓颉 SDK、stdx 和 Windows 构建工具。本项目的部署与验证脚本不会自动下载或安装依赖。

```powershell
# 一条命令构建、启动并完成健康检查
.\deployment\windows\start.ps1 -PublishToken "change-this-token"

# 检查进程、存储和 HTTP 健康状态
.\deployment\windows\doctor.ps1

# 停止服务；持久化数据不会被删除
.\deployment\windows\stop.ps1
```

默认地址为 `http://127.0.0.1:8080`，数据保存在 `deployment/windows/data`。端口、存储、Proxy 上游和索引 TTL 均可通过参数配置，详见 [Windows 部署说明](deployment/windows/README.md)。

## Docker Compose 快速开始

在 WSL 中完成 Linux 构建且 Docker Desktop 已启动后：

```powershell
.\deployment\docker\up.ps1
.\deployment\docker\doctor.ps1
```

脚本只打包 Linux 服务二进制和两项必要运行库，容器以非 root、只读根文件系统、无 capabilities 方式运行。真实发布、容器销毁重建和持久化下载已经通过，见 [Docker 验证记录](docs/docker-verification.md) 与 [部署说明](deployment/docker/README.md)。

### 解析解释与诊断

```powershell
cjpm repo explain meshdep
cjpm repo doctor meshdep
cjpm repo explain meshdep --recorded
```

### 批量 Mirror

清单为简单的 `package version` 格式：

```text
# mirror.txt
meshdep 1.0.0
meshdep 2.0.0
```

```powershell
$env:CJREPO_STORAGE = "D:\CjRepoData"
.\server\target\release\bin\main.exe mirror-manifest https://upstream.example.com mirror.txt
```

每项都验证 SHA-256。重复执行有效缓存时逐项返回 `SKIP`；坏条目不会阻止后续条目，但命令最终返回失败并输出 `total / succeeded / failed`。
镜像索引仅公开本地已有且校验通过的版本；老版本缓存中多余的上游索引条目会在重访有效缓存时离线清理。

### 批量仓间 Sync

```powershell
$env:CJREPO_SYNC_DESTINATION_TOKEN = "destination-publish-token"
.\server\target\release\bin\main.exe sync-manifest `
  http://source:8080 `
  http://destination:8080 `
  mirror.txt
```

Sync 先比较 Source 和 Destination 索引的指定版本与 SHA-256：相同则直接 `SKIP`、不下载制品；缺失才下载、校验并发布；同版本校验和不同则报冲突，不覆盖目标。私有目标仓的读取和发布可分别使用 `CJREPO_SYNC_DESTINATION_READ_TOKEN`、`CJREPO_SYNC_DESTINATION_TOKEN`。清单中断后可重跑并跳过已完整同步项，但尚无持久化进度游标。

需要持续运行时，`mirror-watch <upstream> <清单> <间隔秒>` 和 `sync-watch <source> <destination> <清单> <间隔秒>` 每隔 1–86400 秒重新读取清单。新增版本会被处理，失败项下一轮重试，已有相同校验和的 Sync 版本不会再次下载。进程开机启动与异常重启需由外部管理器负责；不提供字节级断点续传或多实例协调。

## 验证

Windows 一条命令顺序执行四组共享核心测试与一组平台部署测试：

```powershell
.\integration-tests\run-all.ps1
```

Linux / WSL 使用相同的核心夹具和断言：

```bash
source /path/to/cangjie/envsetup.sh
export CANGJIE_STDX_PATH=/path/to/stdx/linux_x86_64_cjnative/static/stdx
./integration-tests/run-linux.sh
```

| 测试组 | 主要覆盖 |
| --- | --- |
| Multi-repository cjpm | 版本与来源冲突、Replace、Explain、Doctor、Provenance、回退、认证、Namespace 和旧配置 |
| Hosted repository | 发布、索引、下载、鉴权、SHA-256、重复版本与并发原子写 |
| Proxy repository | 并发填充、MISS/HIT、TTL、离线构建和损坏拒绝 |
| Repository sync | 批量 Mirror/Sync、部分失败、鉴权、幂等和源仓离线构建 |
| Windows deployment | 一键启动、诊断、发布、持久化重启和安全停止 |

2026-10-20 最新服务端补齐原生启动及 Mirror/Sync 的 URL 前置校验，拒绝地址内凭据且诊断不回显值：Windows / Linux 矩阵各 **96/96 PASS**，受影响的 Hosted、Proxy、Mirror/Sync 三组分别 **3/3 PASS、56.22 秒 / 90.15 秒**。新独立 Docker 镜像 Doctor **9/9 PASS**，容器内 URL 拒绝、私有读取、组织仓和重建持久化通过；客户端没有改动。

此前固定候选完成 Windows 四组核心 **4/4 PASS、109.36 秒**与 Linux 四组 **4/4 PASS、225.24 秒**；Windows 部署入口的相对路径问题修复后另行复验通过，不表述为同次五组全通过。文件存储冷备份恢复在 Windows / Linux 各 **10/10**，Docker 停服导出、新卷恢复及真实包构建 **9/9**，本次 URL 修复未重复这些专项。这些演练不保证在线备份、业务切换或断电持久性。

当前固定客户端6a7与官方原版单仓差分 **7/7 PASS**；增强版Maple **原断言38项、就绪调整1项、归档稳定化1项、HLT离线95/101** 分别通过，共113份真实调用日志。原刷新失败保留，不称39项未经调整通过；本轮Maple只执行增强版，完整HLT/LLT仍未完成。身份和本轮新执行/引用的区别见[固定候选验收清单](docs/candidate-acceptance.md)，详情见[验证记录](docs/verification-report.md)、[官方兼容性记录](docs/official-compatibility-report.md)与[Docker历史记录](docs/docker-verification.md)。

历史2026-10-20批次使用隔离HOME/USERPROFILE执行同一离线打包选择：当时增强版 `7e29eaa7…` 与官方原版各 **95/95 PASS**，190份日志仍保留；10月21日06ae另做增强版95项复验。两批仍为各自历史产物记录，不移算为本轮6a7执行，也不代表完整HLT/LLT。

上述核心回归覆盖跨仓传递依赖的相容版本选源、不可解冲突、来源 SHA-256 实值核对、独占命名空间故障矩阵，以及篡改制品拒绝与同缓存恢复。正式视频和签字 PDF 等材料已由参赛者完成提交，状态见 [提交检查表](docs/submission-checklist.md)；另保留 [早期可编辑技术答辩参考稿](submission/CjRepoMesh-technical-defense-redesign-2026-09-23.pptx)。

性能测试单独运行，避免把性能波动混入功能回归：

```powershell
.\benchmark\proxy\run.ps1
```

当前本机本地 HTTP 微基准：Cold Median `62.76 ms`，Warm Median `33.102 ms`，Median speedup `1.9x`。这不是公网官方中心仓延迟，原始样本与限制见 [Proxy Benchmark](benchmark/results/proxy-benchmark.md)。

## 安全语义

| 风险 | 控制 |
| --- | --- |
| Dependency Confusion | 独占命名空间使公共仓请求数为 0 |
| 认证失败后错误回退 | 401/403 立即失败 |
| 私有仓未授权读取 | 可选读取令牌保护 Hosted/Proxy 索引与制品，在访问缓存或上游前返回 401 |
| 制品篡改 | cjpm、Proxy、Mirror、Sync 全链路 SHA-256 |
| 跨仓同名同版本污染 | 命名/多仓缓存包含配置名与原始URL摘要；旧单仓home保留兼容布局，改地址须换缓存根 |
| 静默强制替换 | 显式 `[replace]`，Explain 显示决策 |
| 来源不可追溯 | 原子写入独立 Provenance 文件 |
| Token 泄漏 | 从环境变量读取，不写入部署状态 |

## 项目结构

```text
cjpm/                 官方 cjpm 上的多仓增强
server/               仓颉原生 CjRepo Server
deployment/windows/   一键部署、诊断和停止
integration-tests/    跨平台四组核心验证与 Windows 部署验证
benchmark/            可重复 Proxy 基准与原始样本
docs/                 架构、验收、报告、演示和提交材料
```

## 当前边界

当前支持范围与限制如下：

- Hosted 与 Proxy 服务端支持默认仓与命名 organization 的读取，Hosted 可发布；Mirror、Sync 接受 `组织名::包名` 的单项命令和清单，索引/制品按组织隔离；读取鉴权需显式配置，默认仍公开读取；
- 当前使用按仓库、组织和包名定位的固定锁分片；同包串行，不同包通常并行，但哈希碰撞时仍会串行；
- 命名/多仓客户端缓存按配置名和原始URL摘要分区；升级后旧名称缓存不自动迁移，首次需联网预热。仅单个 `home` 保留旧布局，其URL变化仍须使用新的缓存根目录；
- Mirror/Sync 有单进程周期轮询，但尚无持久化游标、字节级断点续传或多实例协调；
- Linux 原生构建与四组共享核心回归已验证；Windows 一键部署和 Docker Compose 分别保留平台专属验证入口；
- 尚未运行依赖额外官方测试资产的完整 Maple HLT/LLT；
- `cjpm-provenance.json` 是独立审计文件，不是官方 lockfile 新格式。

完整进度与诚实边界见 [参赛与获奖就绪度](docs/award-readiness.md) 和 [官方验收矩阵](docs/competition-requirements-matrix.md)。

## 参赛材料

- [演示 Runbook](docs/demo-runbook.md)：6～8 分钟演示顺序、话术和失败切换；
- [提交检查表](docs/submission-checklist.md)：官方闭环、仓库卫生、证据、安全表述与平台提交；
- [技术可行性审查](docs/technical-feasibility-review.md)：官方 cjpm 调用链与修改边界；
- [多仓实现状态](docs/multirepo-implementation.md)：配置、语义和测试矩阵。
- [官方兼容性差分](docs/official-compatibility-report.md)：同源码基线的原版/增强版差分与已运行的官方 LLT 夹具。
