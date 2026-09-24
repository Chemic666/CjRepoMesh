# CjRepoMesh

> 面向仓颉与 cjpm 的原生多仓依赖和轻量企业私有仓基础设施

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

完整组件关系、决策流程和代码地图见 [架构说明](docs/architecture.md)。

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

### 批量仓间 Sync

```powershell
$env:CJREPO_SYNC_DESTINATION_TOKEN = "destination-publish-token"
.\server\target\release\bin\main.exe sync-manifest `
  http://source:8080 `
  http://destination:8080 `
  mirror.txt
```

Sync 从 Source 取得索引和制品、验证 SHA-256，再通过目标仓发布协议写入；目标版本已经存在时按幂等 `SKIP` 处理。

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

最近新增可选的私有读取令牌，并防止“读私有、写匿名”的错误配置。2026-09-24 在新编译服务端上完成 Linux 四组共享核心回归 **4/4 PASS，189.09 秒**；当前二进制 Docker 镜像的安全诊断 **9/9 PASS**，私有读取容器专项验证无令牌 401、正确令牌可继续查询，之后恢复原配置。Windows 入口仍被系统 Application Control 拦截，历史 5/5 不能当作当前结果。官方原版与增强版的单仓差分 7/7 通过；官方仓库 HTTP 状态夹具在两版上各 16/16 断言通过。官方 Maple 框架对三十九个选定 LLT 用例在两版上各判定为 39/39 PASS；另有一个制品异常矩阵在只对测试副本固定 gzip 时间戳后两版各 1/1 PASS。完整 HLT/LLT 尚未运行。环境、耗时和边界见 [全量验证报告](docs/verification-report.md)、[官方兼容性记录](docs/official-compatibility-report.md) 与 [Docker 验证记录](docs/docker-verification.md)。

本次完整回归覆盖跨仓传递依赖的相容版本选源、不可解冲突、来源 SHA-256 实值核对、独占命名空间故障矩阵，以及篡改制品拒绝与同缓存恢复。另备有 [8 页可编辑技术答辩稿（重设计版）](submission/CjRepoMesh-technical-defense-redesign-2026-09-23.pptx)，视频路线仍待录制。

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
| 跨仓同名同版本污染 | 缓存键和来源记录包含仓库身份 |
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

以下能力尚未完成，不应在参赛材料中描述成已有功能：

- Hosted 服务端支持默认仓与命名 organization 的发布和读取，索引/制品按组织隔离；Proxy、Mirror、Sync 暂只支持默认 organization；读取鉴权需显式配置，默认仍公开读取；
- 当前使用进程级存储锁，尚未细化为按包锁；
- Mirror/Sync 尚无调度和断点续传；
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
