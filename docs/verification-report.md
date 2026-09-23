# CjRepoMesh 全量验证报告

> 执行日期：2026-09-23
> 核心回归基线：`8e33119`；后续安全修复：`de2da77`
> 结论：历史 Windows 五组与 Linux 四组在 `8e33119` 上通过；本轮 `b10ced9` 的 Linux 四组与 Docker 诊断通过，Windows 构建被系统 Application Control 阻断

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
- Docker 在后续修复过程中再次 9/9 通过且启动输出不再回显 Token；`de2da77` 新增的 SecureString 与 `.env` ACL 逻辑已静态/权限测试，但因 Docker Desktop 随后停止，尚未再次执行容器启动；
- 未执行依赖额外官方测试资产的完整 Maple HLT/LLT；
- 未验证默认 organization 之外的服务端协议；
- 本报告不是长期稳定性、跨机网络或公网安全认证报告；
- 性能数据见独立的 `benchmark/results/proxy-benchmark.md`，不由本功能回归推导。

## 本轮最新提交复核

在 `b10ced9` 上运行 Windows `integration-tests/run-all.ps1 -SkipServerBuild`：第一组打包夹具时，系统 Application Control 拦截 `cjc -v`，统一入口停止，故本轮 Windows 结果记为 **环境阻断**，不能沿用上表的历史 5/5 作为当前提交结果。未调整 Windows 安全策略。

同一代码在 WSL 2 / Ubuntu 22.04.5 上执行 `./integration-tests/run-linux.sh`，服务端实际编译通过，四组为 **4/4 PASS**，总耗时 **510.22s**：Multi-repository 395.10s、Hosted 34.97s、Proxy 55.37s、Repository sync 24.71s。测试结束后没有留下固定测试端口和临时数据。本轮较历史 Linux 77.25s 明显变慢；两次结果均为实测值，不据此推导性能变化。

Docker Compose 在 `b10ced9` 上执行 `up.ps1 → doctor.ps1 → down.ps1`，9 项诊断全部 PASS。启动输出没有回显发布 Token，`.env` ACL 已关闭继承且仅当前 Windows 用户有允许规则。测试创建的 Compose 容器已停止并移除，命名数据卷保留；用户原先运行的独立 `cjrepomesh:local` 容器未被更改。

同轮完成官方原版与增强版的单仓差分 3/3，以及一个官方 LLT 夹具在两版上各 16/16 断言，结果见 `docs/official-compatibility-report.md`。完整 Maple HLT/LLT 仍未运行。

## 后续兼容性扩展

在未改动 cjpm 产品源码的前提下，单仓原版/增强版差分扩至 **7/7 PASS**：新增两版桥接包的传递约束下选择相容版本、共同选择最新版、不可解冲突拒绝，以及固定版本放宽后保留旧锁定版本、执行 `cjpm update` 再选择新版本。锁文件比较覆盖全部有效条目，但忽略 cjpm TOML 映射输出的不固定顺序；运行结果、依赖树和旧缓存布局也接受检查。详细条件与边界见 `docs/official-compatibility-report.md`。
