# CjRepoMesh 参赛演示 Runbook

> 目标时长：6～8 分钟
>
> 核心叙事：不是“又一个制品仓”，而是仓颉原生的 Repository Resolution 层与企业私有仓闭环
>
> 原则：现场只演示已经自动验证的能力，网络、工具链或录屏异常时立即切换到保底证据

## 1. 演示前一天

1. 在最终参赛提交上运行一次 `integration-tests/run-all.ps1`，把提交号、环境和结果更新到 `docs/verification-report.md`；
2. 单独运行 `benchmark/proxy/run.ps1`，确认报告中的数字来自最终提交；
3. 确认 `git status --short` 为空，不携带 Token、测试缓存、日志或构建产物；
4. 录制一份完整无剪切备份视频，再录制最终讲解版；
5. 保存架构图、全量验证报告和 Benchmark 报告的本地副本，避免现场网络依赖；
6. 关闭会弹通知的软件，确认端口 `39141～39600` 与演示端口未被占用；
7. 不在演示当天升级 SDK、操作系统、依赖或安全策略。

## 2. 开场：问题与边界（40 秒）

展示 `docs/architecture.md` 的总体架构图，只讲三个结论：

1. 企业项目需要同时消费公共包和私有包；
2. CjRepoMesh 的 Router 只决定“去哪个仓”，原 cjpm 继续决定“选哪个版本”；
3. 项目同时交付 cjpm 多仓能力和仓颉原生 Hosted/Proxy/Mirror/Sync 私有仓。

建议话术：

> CjRepoMesh 没有重写 cjpm 的依赖求解器。我们在中心仓访问之前加入 Repository Router，聚合允许仓库的候选版本，再把版本选择交还原求解器；这样获得企业多仓能力，同时守住官方要求的兼容性边界。

## 3. Scene 1：一键部署私有仓（50 秒）

```powershell
.\deployment\windows\start.ps1 -Port 8080 -PublishToken "demo-publish-token"
.\deployment\windows\doctor.ps1
```

必须让评委看到：

- 单条命令完成构建、后台启动和健康检查；
- Doctor 同时显示 PROCESS、STORAGE、HEALTH 为 PASS；
- 数据目录、PID 和地址明确可见；
- Token 不写入状态文件或日志。

讲解重点：这是官方“一键部署”要求的直接证据，不需要数据库、Redis 或 Kubernetes。

## 4. Scene 2：多仓不改变原版本规则（80 秒）

先展示 `integration-tests/multirepo/app/cangjie-repo.toml`：高优先级仓只有 `1.0.0`，低优先级仓还提供 `2.0.0`。

```powershell
.\integration-tests\multirepo\run.ps1
```

在输出中指出：

- `highest compatible version across repositories` 为 PASS；
- 最终选择 `2.0.0`，说明仓库优先级没有错误覆盖原版本求解；
- 同一版本存在于两个仓时，才由仓库优先级确定来源；
- `[replace]`、404/5xx 回退和 401 阻断均有自动断言。

建议话术：

> Priority 决定同一最终版本从哪里下载，不决定版本范围最终选哪个版本。这个分层是我们避免破坏 cjpm 原语义的关键。

## 5. Scene 3：Dependency Confusion 防护（60 秒）

展示 `integration-tests/multirepo/app-namespace/cangjie-repo.toml`：

```toml
[[route]]
namespace = "company::*"
registry = "private"
exclusive = true
```

说明测试中的公共仓故意放置更高版本 `company::auth 9.0.0`，私有仓只有 `1.0.0`。结果必须指出：

- 构建仍选择私有 `1.0.0`；
- 公共仓请求数为 0；
- 私有仓返回 404 时也不越过独占边界；
- 私有仓 401 时立即失败，不能偷偷回退公共仓。

建议话术：

> Fallback 不是越多越好。企业命名空间一旦认证失败或不存在，就必须失败；否则可用性机制会变成供应链漏洞。

## 6. Scene 4：Explain、Doctor 与离线审计（60 秒）

从多仓测试输出中展示：

```text
cjpm repo explain <package>
cjpm repo doctor <package>
cjpm repo explain <package> --recorded
```

讲解它们分别回答：

- Explain：为何选这个版本、这个仓库，是否发生替换或路由；
- Doctor：仓库是否可达、Token 是否正确、当前错误是否允许回退；
- Recorded：仓库已经离线时，上一次构建的来源与 SHA-256 是否仍可审计。

不要把 `cjpm-provenance.json` 描述成官方 lockfile；它是 CjRepoMesh 独立的来源审计文件。

## 7. Scene 5：Proxy 离线与真实性能（70 秒）

```powershell
.\integration-tests\proxy\run.ps1
```

必须指出：

- 并发首次请求只产生一次经过校验的上游填充；
- MISS 下载索引和制品并校验 SHA-256；
- 索引 TTL 到期只刷新元数据，不重复下载不可变制品；
- 上游关闭后缓存仍能完成构建；
- 损坏制品被拒绝且不进入缓存。

随后展示 `benchmark/results/proxy-benchmark.md`：本机实测 Cold Median `62.76 ms`、Warm Median `33.102 ms`、Median `1.9x`。必须同时说明这是本地 HTTP 微基准，不代表公网官方仓延迟。

## 8. Scene 6：批量 Mirror 与跨仓 Sync（60 秒）

展示 `integration-tests/sync/mirror-manifest.txt`：

```text
meshdep 1.0.0
meshdep 2.0.0
```

```powershell
.\integration-tests\sync\run.ps1
```

指出：

- Mirror/Sync 都能按清单批量处理；
- 每个制品都经过 SHA-256 校验；
- 重复执行逐项返回 SKIP；
- 一个坏条目不会阻止后续条目，但最终返回失败并汇总数量；
- Source 关闭后，Destination 仍能独立供 cjpm 构建。

## 9. 收尾（30 秒）

```powershell
.\deployment\windows\stop.ps1
```

展示 `docs/verification-report.md`：最终提交应为五组全部 PASS。然后只说真实边界：

- Windows、Linux 原生关键链路和 Docker Compose 路径均已验证；
- Linux 全量统一回归仍需在最终提交上执行；
- 默认 organization、无读鉴权；
- 尚无调度和断点续传。

建议收尾：

> 我们优先完成了官方四项要求的可运行闭环，并把企业最容易出问题的来源可解释性、认证回退和 Dependency Confusion 做成了确定性机制。CjRepoMesh 现在不是架构图，而是可以部署、可以故障注入、可以复验的仓颉基础设施。

## 10. 失败切换方案

| 现场问题 | 立即动作 | 保底证据 |
| --- | --- | --- |
| SDK 或安全策略阻止编译 | 不修改安全策略，不重复尝试 | 最终提交的验证报告、无剪切备份视频、已生成二进制演示 |
| 端口占用 | 使用部署脚本的 `-Port` 参数切换 | `doctor.ps1` 输出 |
| 公网不可用 | 不访问公网，全部演示使用本地夹具 | Proxy 离线构建测试 |
| 某场景超时 | 终止该场景，直接展示对应自动测试报告 | `verification-report.md` |
| Benchmark 波动 | 不现场宣称新数字 | 已提交原始样本和可重复脚本 |

任何现场失败都不得通过关闭安全功能、删除校验或修改测试断言来“修复”。
