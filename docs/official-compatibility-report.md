# 官方 cjpm 兼容性差分记录

> 执行日期：2026-09-23
> 项目测试入口：`a49b5e1`；本轮并发下载失败修复：`efb7e24`
> 结论：修复后的 cjpm 与官方原版单仓差分 7/7 通过；官方 HTTP 状态 LLT 的 16 条断言在两版上分别通过，且官方 Maple 框架对 HTTP 状态、三个配置及缺少中心仓用例在两版上各 5/5 通过。完整 Maple HLT/LLT 尚未运行。

## 对照基线与环境

| 项目 | 取值 |
| --- | --- |
| 官方 cjpm 源码 | `Cangjie/cangjie_tools` 提交 `2978007`，即项目修改前的基线 |
| 官方测试源码 | `Cangjie/cangjie_test` 提交 `1dfa37619f920884e119d7f51266869c8f0fd81e` |
| 官方 Maple 框架 | `Cangjie/cangjie_test_framework` 提交 `e92721e2000c00c19701d4df2ac9e42e7921fe5c` |
| 增强版 cjpm 源码 | 本仓库 `efb7e24` 后续版本；本轮另修复仅含旧 `repository.home`/`repository.cache` 时的失败提示兼容性 |
| 运行系统 | WSL 2 / Ubuntu 22.04.5 x86_64 |
| 编译器 / stdx | Cangjie 1.1.3 cjnative / stdx 1.1.3.1 |
| Python | 3.10.12 |
| 官方 cjpm 二进制 SHA-256 | `2f624cbe5493fcc686611e22eef7eb30e317c1ec589c18980dd88892875d9646` |
| 增强版 cjpm 二进制 SHA-256 | `6336f0bd1c973c4128717d7684ab13cdc3dce0840b9b8793aa5e599a00dca62a` |

原版以本地 Git 提交单独检出，并在 WSL 使用已有 SDK、stdx 和 libuv 执行官方 `cjpm/build/build.py build -t release --target native`，输出 `Successfully build libfswatcher!` 与 `Successfully build cjpm!`。未下载、安装或解压依赖。两版 `cjpm -v` 均为 `1.3.0-alpha.05`。

## 单仓行为差分

入口为 `integration-tests/compatibility/run.py`，使用 `integration-tests/multirepo/app-legacy` 和本地测试仓。每个版本的应用在独立临时目录中运行；应用配置均使用旧 `[repository.home]`，不会启用多仓配置。脚本执行原版和增强版的 `cjpm run`、`cjpm tree --no-tests`，锁文件转换场景还执行 `cjpm update`。比较锁文件全部有效条目、依赖树与旧索引缓存路径。cjpm 的 TOML 映射输出顺序不固定，因此锁文件比较忽略条目顺序，不声称逐字节一致。

| 场景 | 原版与增强版共同结果 | 差分 |
| --- | --- | --- |
| 固定版本 `meshdep = "2.0.0"` | 运行输出包含 `low-2.0.0`；锁文件记录 2.0.0 | 锁文件有效条目、依赖树、旧缓存布局一致 |
| 范围 `[1.0.0, 3.0.0)` | 从 1.0.0/2.0.0 中选择 2.0.0 | 同上 |
| 混合双依赖 | 同一旧仓解析 `meshdep` 和 `company::auth 1.0.0` | 同上 |
| 传递约束收敛 | 根项目固定 `meshdep 1.0.0`，要求 `meshbridge [1.0.0, 3.0.0)`；桥接包 2.0.0 要求 `meshdep 2.0.0`，1.0.0 要求 `meshdep 1.0.0` | 两版均选 `meshbridge 1.0.0` 与 `meshdep 1.0.0`；运行、锁文件、依赖树一致。不单凭结果断言求解器内部回溯路径 |
| 传递依赖最新版 | 根项目对两个包均给出 `[1.0.0, 3.0.0)` | 两版均选桥接包与底层包 2.0.0；运行、锁文件、依赖树一致 |
| 不可解传递冲突 | 根项目固定 `meshdep 2.0.0` 与 `meshbridge 1.0.0`，后者要求 `meshdep 1.0.0` | 两版均以非零退出码拒绝，诊断包含冲突包和两个版本 |
| 锁文件转换 | 先固定 `meshdep 1.0.0`，放宽依赖范围后运行，再执行 `cjpm update` | 两版均先保持 1.0.0，更新后选择 2.0.0；各阶段锁文件与最终依赖树一致 |

旧诊断兼容修复后的增强版 cjpm 在 2026-09-23 重新执行，结果：**7/7 PASS**。每个应用的 `meshdep` 索引均保存在旧路径 `cache/repository/index/default/me/sh/meshdep`，没有创建 `cache/repository/registries`。这支持“旧 `repository.home` 下，已覆盖的直接依赖、传递依赖冲突与锁文件行为保持一致”；仍不证明所有传递依赖组合都一致。

## 官方 LLT 仓库状态夹具

运行官方 `testsuites/LLT/Tools/cjpm/CJNATIVE/repository/coverage/http_status_matrix` 的 `run_matrix.sh`。脚本自身用 `|| true` 容纳预期失败，因此本项目的运行器额外读取官方 `.info`，逐条检查实际输出中的 16 条 `ASSERT: scan` 文字，而非仅看脚本退出码。

| 被测程序 | 索引错误 4 条 | 下载错误 5 条 | 发布错误与中断 7 条 | 总计 |
| --- | ---: | ---: | ---: | ---: |
| 官方原版 cjpm | PASS | PASS | PASS | 16/16 PASS |
| CjRepoMesh 增强版 cjpm | PASS | PASS | PASS | 16/16 PASS |

官方测试仓在 Windows 上检出为 CRLF。运行器仅在临时副本中把 `.sh`、`.toml`、`.cj` 转成 LF，使官方脚本的行尾 `sed` 匹配生效；未修改官方测试仓。临时服务进程、39137/39142 端口和测试数据已清理。

2026-09-23 使用本地已有官方夹具，对修复后的增强版二进制（SHA-256 `d2858f2f749b6f1e27b82afe9f01cce9ae95f76c466bd68423843fd2f5a57aa5`）与上述官方原版再次逐条核对，结果仍分别为 **16/16 PASS**。这是一个官方 LLT 夹具，不代表完整 Maple HLT/LLT。

旧诊断兼容修复后，使用新编译二进制 SHA-256 `6336f0bd1c973c4128717d7684ab13cdc3dce0840b9b8793aa5e599a00dca62a` 再跑同一入口，原版与增强版仍各 **16/16 PASS**。

## 官方 Maple 框架复核

2026-09-23 将官方框架独立检出到工作区，在 WSL 2 / Ubuntu 22.04.5 中使用 `integration-tests/compatibility/maple_smoke.py` 运行 `http_status_matrix.info`、三个配置用例和 `central_repository_missing.info`。入口只对 HTTP 状态测试临时副本的 `.sh`、`.toml`、`.cj` 规范 LF 行尾，官方 Git 跟踪文件未修改；原版与本轮新编译增强版 cjpm 的二进制 SHA-256 分别为 `2f624cbe5493fcc686611e22eef7eb30e317c1ec589c18980dd88892875d9646` 和 `6336f0bd1c973c4128717d7684ab13cdc3dce0840b9b8793aa5e599a00dca62a`。

首次扩展 `central_repository_missing.info` 时，原版 **PASS**，增强版 **FAIL**：二者都正确拒绝缺少中心仓的安装，但增强版改写了旧错误提示，未匹配官方断言。修复仅在配置只含默认 `home`/`cache`、`home` 启用且 registry 为空、未配置路由时恢复原版提示；其余无可用仓配置仍显示新诊断。重新编译后，官方 Maple 判定原版 HTTP 状态 **1/1 PASS（46.33s）**、配置 **3/3 PASS（4.11s）**、缺仓 **1/1 PASS（1.39s）**；增强版 HTTP 状态 **1/1 PASS（45.86s）**、配置 **3/3 PASS（4.03s）**、缺仓 **1/1 PASS（1.25s）**。两版各五个选定用例全部通过，运行日志保存在工作区外层 `test-runs/maple-smoke/run-1790168948-56463991/`。这里的 HTTP 1/1 表示一个官方 `.info` 用例，不是 16 个独立 Maple 用例；框架仓虽已就绪，WSL Python 环境仍没有 `pexpect` 和 `fasteners`，尚未启动整套测试。

## 复现命令

在加载仓颉 SDK `envsetup.sh` 并设置 `CANGJIE_STDX_PATH` 后，从项目根目录运行：

```bash
python3 integration-tests/compatibility/run.py \
  --official-cjpm /path/to/official/cjpm/dist/cjpm \
  --enhanced-cjpm /path/to/CjRepoMesh/cjpm/dist/cjpm \
  --official-fixture /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/repository/coverage/http_status_matrix
```

脚本不会构建或下载两版 cjpm；运行前需自行准备同一官方源码基线的二进制。可用 `--only-official-fixture` 单独复验官方 LLT 状态夹具。

## 尚未覆盖

- 官方 Maple 框架已跑通上述五个选定的 cjpm LLT 用例；`pexpect`、`fasteners` 尚未安装，也没有运行完整官方 HLT/LLT。本报告不把子集通过外推为整套通过。
- 单仓差分已覆盖两个桥接包版本造成的传递约束收敛与不可解冲突，以及旧锁文件的保留和更新；更大规模的传递依赖图、跨仓冲突、其他官方夹具仍待扩展。
- Windows 本轮 `cjpm bundle` 在执行 `cjc -v` 时被 Application Control 阻止，故最新 Windows 五组结果为环境阻断；没有关闭或绕过该策略。
