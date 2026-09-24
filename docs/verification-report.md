# CjRepoMesh 全量验证报告

> 最近执行日期：2026-09-24
> 历史基线：Windows 五组 `8e33119`；早期 Linux 四组与 Docker 复核 `e5be054`
> 结论：Hosted/Proxy/Mirror/Sync 命名组织仓、有界按包键锁分片及增量 Sync 预检查加入后，最新服务端通过 Linux 四组完整回归 4/4、1212.36 秒；本轮耗时包含偏慢的 WSL 夹具编译，不能据此推导服务性能。Docker 9/9 诊断和私有默认仓/组织仓隔离持久化专项通过。真实 cjpm 组织包发布、代理拉包、镜像同步、离线构建及私有 Hosted 拉包均有证据。官方 Maple 框架的三十九个选定 cjpm LLT 用例在原版与增强版上各 39/39 通过，另有本地打包、树与组织名选定批次通过。Windows 当前构建被系统 Application Control 阻断，完整 Maple HLT/LLT 尚未运行。

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
