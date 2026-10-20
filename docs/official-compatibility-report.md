# 官方 cjpm 兼容性差分记录

> 最近执行：2026-10-20；本轮固定候选结果见首节，后续章节保留历史证据。
> 项目测试入口：`a49b5e1`；并发下载失败修复：`efb7e24`；本轮旧诊断兼容修复：`0aae9ea`
> 结论：修复后的 cjpm 与官方原版单仓差分 7/7 通过；官方 HTTP 状态 LLT 的 16 条断言在两版上分别通过。Maple 框架先前对 39 个选定 cjpm LLT 用例在两版上各 39/39 通过，随后独立运行的本地打包 23 项、依赖树 17 项、组织名 12 项也分别在两版全通过；另一个制品异常矩阵仅在稳定化测试副本上两版各 1/1 通过。完整 Maple HLT/LLT 尚未运行。

## 2026-10-20 当前候选对照

从 Windows 当前源码固定快照，在全新的 Linux 验证目录重建增强版 cjpm，SHA-256 为 `7e29eaa7e02885ba6d9ae998a6d2787170db5b17b28741bb61d613e02b330abf`；原版仍为下表官方基线，二进制摘要本轮已重新核对。

- 单仓直接/传递依赖、冲突、锁文件和缓存布局差分 **7/7 PASS**。
- Maple 选定集合两版各 **39/39 PASS**；稳定化归档异常矩阵另各 **1/1 PASS**，不等于原样夹具或完整 HLT/LLT。
- 首次在原版 34 项通过后遇到夹具释放端口竞态。修复入口的有限等待后，按原版未变化哈希与实际日志复用 34 项，只补剩余 5 项与稳定化矩阵；增强版 39 项及稳定化矩阵全部本轮执行。未修改官方测试源。
- 证据在外层 `test-runs/candidate-20261020-hardening-420fee1a/`，详细摘要、复用清单和执行边界见 [验证报告](verification-report.md)。

完整 HLT/LLT 仍未完成，历史其他子集不与本轮相加冒充完整覆盖。

## 历史对照基线与环境

| 项目 | 取值 |
| --- | --- |
| 官方 cjpm 源码 | `Cangjie/cangjie_tools` 提交 `2978007`，即项目修改前的基线 |
| 官方测试源码 | `Cangjie/cangjie_test` 提交 `1dfa37619f920884e119d7f51266869c8f0fd81e` |
| 官方 Maple 框架 | `Cangjie/cangjie_test_framework` 提交 `e92721e2000c00c19701d4df2ac9e42e7921fe5c` |
| 增强版 cjpm 源码 | 本仓库 `0aae9ea`；在 `efb7e24` 后另修复仅含旧 `repository.home`/`repository.cache` 时的失败提示兼容性 |
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

## 七用例扩展与制品矩阵波动

又增加 `repository_cached.info` 和 `git_install_invalid_config.info`，完整入口在原版与增强版上分别 **7/7 PASS**：HTTP 状态 1/1、配置 3/3、缺仓 1/1、缓存安装 1/1、Git 无效配置 1/1。两版二进制摘要与上表一致；逐例日志在外层 `test-runs/maple-smoke/run-1790170871-2e498703/`。测试仅用临时副本规范 HTTP 夹具行尾，官方测试仓 Git 跟踪文件未变。

另探索官方 `repository_archive_matrix.info`：原版首次通过，增强版首次在 `wrongpkg` 处被 SHA-256 校验拒绝，第二次原样复跑通过。该官方夹具的 `server.py` 在索引与制品请求中分别调用 `tarfile.open(..., mode="w:gz")` 动态生成同名压缩包；本地直接跨秒调用 `make_archive("wrongpkg")` 得到不同 gzip 时间戳字节和 SHA-256。因此首次失败不能直接归因为增强版回归，也不能把一次重跑通过称为稳定通过。

随后只在烟测入口的临时测试副本中，将该服务脚本的 gzip mtime 固定为 0；不改归档内容、索引断言或 cjpm 的哈希校验。Maple 复核原版 **1/1 PASS（10.64s）**、增强版 **1/1 PASS（9.57s）**，与前述七个用例共同运行的日志在 `test-runs/maple-smoke/run-1790171311-a4644d17/`；其中 `archive-fixture-adjustment.txt` 记录原始和调整后服务脚本的 SHA-256。这个结果只证明稳定化夹具下的兼容性，不把它算入七个未改测试逻辑的用例，也不宣称原始夹具稳定通过。

再扩展官方 `git_install_options.info`、`git_install_workspace.info` 与 `update/wrong_config` 两个用例后，统一入口在同一原版与增强版二进制上各 **11/11 PASS**（HTTP 1、配置 3、安装 5、更新错误配置 2）；稳定化制品异常矩阵另各 **1/1 PASS**。本轮逐例日志及夹具调整摘要在 `test-runs/maple-smoke/run-1790171957-a31a42db/`。新增 Git 用例覆盖分支、标签、提交与 workspace 安装；更新用例覆盖空路径和不存在路径的明确拒绝。项目产品源码与两版二进制摘要未变。这个十一个用例仍只是选定 LLT 子集。

再加入官方 `install/local` 下全部十七个 `.info`，覆盖本地安装、指定 root/name、跳过构建、动态可执行程序及错误拒绝等场景。首次探索运行把 `HOME` 隔离但未同步调整 `PATH`，原版 15/17：两个用例的安装成功、后续调用安装的命令却报 `command not found`，是测试环境缺少隔离目录的 `.cjpm/bin`，不是 cjpm 安装失败。把该目录加入测试进程 `PATH` 后，原版及增强版探索运行分别 17/17；统一入口再使用每版独立临时 `HOME` 和相应 `PATH`，两版分别 **28/28 PASS**（HTTP 1、配置 3、安装覆盖 5、本地安装 17、更新 2），稳定化制品异常矩阵另各 **1/1 PASS**。本轮逐例日志及夹具调整摘要在 `test-runs/maple-smoke/run-1790174668-ce1149a9/`，早期隔离环境探索日志在 `test-runs/maple-explore/`。官方测试仓跟踪文件与产品源码未修改，两版 cjpm 摘要与上表一致。这二十八个用例仍只是选定 LLT 子集。

继续加入官方 `uninstall` 下全部四个 `.info`，包括正常卸载、帮助和错误参数。隔离 `HOME` 的探索运行两版各 4/4；统一入口随后在两版各 **32/32 PASS**（HTTP 1、配置 3、安装覆盖 5、本地安装 17、卸载 4、更新 2），稳定化制品异常矩阵另各 **1/1 PASS**。日志在 `test-runs/maple-smoke/run-1790175442-0c33ee03/`，二进制摘要未变。官方 `install/git` 两例虽是本地 Git 仓，但被其 `testlist` 明确排除（注明避免并行问题）；探索运行会提示“不在 testlist”，不计为通过，也未强行改官方清单。

本轮又纳入官方 `update/coverage` 的七个 `.info`：缓存依赖更新、空版本、无效 Git remote、跳过脚本、未知参数、缺失 workspace 成员，以及本地索引刷新。最后一项只访问 `127.0.0.1:39138`，会验证索引返回 500 时的告警与整体更新结果；入口仅对其临时副本规范 `.sh`、`.toml`、`.cj` 行尾，官方跟踪文件不变。两版统一运行各 **39/39 PASS**（前述 32 项加更新 7 项），稳定化制品异常矩阵另各 **1/1 PASS**；逐例日志在 `test-runs/maple-smoke/run-1790176547-80305f39/`。两版二进制摘要仍与上表一致，产品源码未改。

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

- 官方 Maple 框架已跑通上述三十九个选定的 cjpm LLT 用例；后续还分别通过本地打包、依赖树、组织名和 workspace 子集（见下文），另有一个稳定化制品异常矩阵通过。`pexpect`、`fasteners` 尚未安装，也没有运行完整官方 HLT/LLT。原始制品异常矩阵仍有动态 gzip 时间戳波动，本报告不把子集通过外推为整套通过。
- 当前本地官方测试快照的 CJNATIVE cjpm LLT 有 773 个 `.info`，HLT cjpm 有 157 个 `.info`；这些数量是文件计数，不等于可直接运行或已通过数。部分 HLT 发布用例配置了外部中心仓地址与测试凭据，并会执行 `cjpm publish`；未获外部仓写入授权前不运行，也不把其中的凭据复制到报告或演示材料。

2026-09-24 追加官方 `repo/bundle` 的 **23 个本地 LLT 用例**，原版和增强版在隔离 `HOME` 下分别 **23/23 PASS**，共保留 46 份逐例日志于 `test-runs/maple-bundle/bundle-1790223696-c5626f35/`。入口预先核对用例数量和执行命令，只运行本地 `cjpm bundle`，不触及外部发布仓。两版二进制 SHA-256 仍为 `2f624cbe5493fcc686611e22eef7eb30e317c1ec589c18980dd88892875d9646` 和 `6336f0bd1c973c4128717d7684ab13cdc3dce0840b9b8793aa5e599a00dca62a`。该 23 项与此前 39 项是不同选定用例，但未在同一统一入口连续运行，不能称为整套 62/62，更不能称完整 HLT/LLT 通过。

同日继续运行官方 `tree` 下 **17 项**和 `organization` 下 **12 项**本地 LLT：原版、增强版分别 17/17 与 12/12 通过。依赖树日志 34 份位于 `test-runs/maple-tree/tree-1790224129-a37bb849/`，组织名日志 24 份位于 `test-runs/maple-organization/organization-1790224256-52fb157b/`。组织名夹具仅含本地路径依赖；结果证明 cjpm 本地组织名构建/运行兼容，不证明 CjRepo Server 支持组织仓发布。这些批次未在同一入口连续执行，仍不是完整 Maple。

2026-09-25 新增 `maple_local_workspace.py`，对官方 `CJNATIVE/workspace` 的 **52 个本地 LLT 用例**逐例执行原版与增强版对照，两版分别 **52/52 PASS**。入口先核对 52 个 `.info`、所有执行命令及配置文件没有外部 URL/发布操作，随后使用每版独立临时 `HOME`；104 份逐例日志保存在工作区外层 `test-runs/maple-workspace/workspace-1790309933-28de5678/`。原版和增强版二进制 SHA-256 分别为 `2f624cbe5493fcc686611e22eef7eb30e317c1ec589c18980dd88892875d9646`、`6336f0bd1c973c4128717d7684ab13cdc3dce0840b9b8793aa5e599a00dca62a`。两版运行先后与文件缓存不同，逐例耗时不用于性能比较；该批仅证明本地 workspace 子集兼容，不等于完整官方 HLT/LLT。
- 单仓差分已覆盖两个桥接包版本造成的传递约束收敛与不可解冲突，以及旧锁文件的保留和更新；更大规模的传递依赖图、跨仓冲突、其他官方夹具仍待扩展。
- Windows 本轮 `cjpm bundle` 在执行 `cjc -v` 时被 Application Control 阻止，故最新 Windows 五组结果为环境阻断；没有关闭或绕过该策略。
