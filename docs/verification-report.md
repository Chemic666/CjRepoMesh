# CjRepoMesh 全量验证报告

> 执行日期：2026-09-23
> 历史基线：Windows 五组 `8e33119`；最近 Linux 四组与 Docker 复核 `e5be054`
> 结论：旧诊断兼容修复后的增强版 cjpm 通过 Linux 四组完整回归 4/4；此前 Docker 诊断 9/9，包含菱形依赖图。官方 Maple 框架的五个选定 cjpm LLT 用例在原版与增强版上各 1/1 + 3/3 + 1/1 通过。Windows 当前构建被系统 Application Control 阻断。各次提交号与耗时见文末，不把历史 Windows 通过当作当前结果。

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
- 未验证默认 organization 之外的服务端协议；
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
