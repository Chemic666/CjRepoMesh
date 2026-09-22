# CjRepoMesh 全量验证报告

> 执行日期：2026-09-22  
> 被测代码基线：`b0ce10a`
> 结论：Windows 五组端到端测试通过；Linux 原生关键链路另行通过

## 环境

| 项目 | 值 |
| --- | --- |
| 操作系统 | Windows（x86_64） |
| 仓颉编译器 | Cangjie Compiler 1.1.3（cjnative） |
| 编译目标 | `x86_64-w64-mingw32` |
| PowerShell | 7.6.5 |
| 增强版 cjpm | `cjpm/target/release/bin/cjpm.exe` |
| CjRepo Server | `server/target/release/bin/main.exe` |

本次验证未下载、安装或解压任何依赖，使用用户已经放置在 `D:\Apps\Cangjie` 的工具链。

## 执行命令

```powershell
.\integration-tests\run-all.ps1
```

## 结果

| 测试组 | 结果 | 耗时 |
| --- | --- | ---: |
| Multi-repository cjpm | PASS | 102.14s |
| Hosted repository | PASS | 34.60s |
| Proxy repository | PASS | 34.29s |
| Repository sync | PASS | 32.00s |
| Windows deployment | PASS | 7.99s |
| **合计** | **5/5 PASS** | **211.07s** |

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

## 未覆盖范围

- Linux 原生 cjpm/Server 构建、服务启动、双仓版本选择和离线来源解释已通过，详见 `docs/linux-verification.md`；
- 未执行 Linux 全量统一入口和 Docker Compose 部署验证；
- 未执行依赖额外官方测试资产的完整 Maple HLT/LLT；
- 未验证默认 organization 之外的服务端协议；
- 本报告不是长期稳定性、跨机网络或公网安全认证报告；
- 性能数据见独立的 `benchmark/results/proxy-benchmark.md`，不由本功能回归推导。
