# 官方 cjpm 兼容性差分记录

> 执行日期：2026-09-23
> 项目测试入口：`ee513df`；cjpm 产品源码自 `b10ced9` 未变化
> 结论：本机可执行的单仓差分 3/3 通过；官方仓库 HTTP 状态 LLT 夹具在原版、增强版上各 16/16 断言通过。完整 Maple HLT/LLT 尚未运行。

## 对照基线与环境

| 项目 | 取值 |
| --- | --- |
| 官方 cjpm 源码 | `Cangjie/cangjie_tools` 提交 `2978007`，即项目修改前的基线 |
| 官方测试源码 | `Cangjie/cangjie_test` 提交 `1dfa37619f920884e119d7f51266869c8f0fd81e` |
| 增强版 cjpm 源码 | 本仓库 `b10ced9`；至 `ee513df` 仅新增测试与文档，未改 cjpm 源码 |
| 运行系统 | WSL 2 / Ubuntu 22.04.5 x86_64 |
| 编译器 / stdx | Cangjie 1.1.3 cjnative / stdx 1.1.3.1 |
| Python | 3.10.12 |
| 官方 cjpm 二进制 SHA-256 | `2f624cbe5493fcc686611e22eef7eb30e317c1ec589c18980dd88892875d9646` |
| 增强版 cjpm 二进制 SHA-256 | `99a50281b529849a8a509640d6e39dcf891ea90ba3dbfe4011f9b62a5781d8e9` |

原版以本地 Git 提交单独检出，并在 WSL 使用已有 SDK、stdx 和 libuv 执行官方 `cjpm/build/build.py build -t release --target native`，输出 `Successfully build libfswatcher!` 与 `Successfully build cjpm!`。未下载、安装或解压依赖。两版 `cjpm -v` 均为 `1.3.0-alpha.05`。

## 单仓行为差分

入口为 `integration-tests/compatibility/run.py`，使用现有 `integration-tests/multirepo/app-legacy` 与本地 `low` 测试仓。每个版本的应用在独立临时目录中运行；应用配置均使用旧 `[repository.home]`，不会启用多仓配置。脚本实际执行原版和增强版各一次 `cjpm run` 与 `cjpm tree --no-tests`，并比较完整 `cjpm.lock` 文本与旧索引缓存路径。

| 场景 | 原版与增强版共同结果 | 差分 |
| --- | --- | --- |
| 固定版本 `meshdep = "2.0.0"` | 运行输出包含 `low-2.0.0`；锁文件记录 2.0.0 | 锁文件完全一致；规范化依赖树一致；旧缓存布局一致 |
| 范围 `[1.0.0, 3.0.0)` | 从 1.0.0/2.0.0 中选择 2.0.0，运行输出包含 `low-2.0.0` | 锁文件完全一致；规范化依赖树一致；旧缓存布局一致 |
| 混合双依赖 | 同一旧仓同时解析范围内 `meshdep` 和 `company::auth 1.0.0`，输出包含 `low-2.0.0`、`private-1.0.0` | 两个依赖的完整锁文件一致；规范化依赖树一致；旧缓存布局一致 |

结果：**3/3 PASS**。每个应用的 `meshdep` 索引均保存在旧路径 `cache/repository/index/default/me/sh/meshdep`，没有创建 `cache/repository/registries`。这直接支持“单仓版本选择、直接依赖图和 `repository.home` 行为在这些夹具下保持一致”；它不证明所有传递依赖组合都一致。

## 官方 LLT 仓库状态夹具

运行官方 `testsuites/LLT/Tools/cjpm/CJNATIVE/repository/coverage/http_status_matrix` 的 `run_matrix.sh`。脚本自身用 `|| true` 容纳预期失败，因此本项目的运行器额外读取官方 `.info`，逐条检查实际输出中的 16 条 `ASSERT: scan` 文字，而非仅看脚本退出码。

| 被测程序 | 索引错误 4 条 | 下载错误 5 条 | 发布错误与中断 7 条 | 总计 |
| --- | ---: | ---: | ---: | ---: |
| 官方原版 cjpm | PASS | PASS | PASS | 16/16 PASS |
| CjRepoMesh 增强版 cjpm | PASS | PASS | PASS | 16/16 PASS |

官方测试仓在 Windows 上检出为 CRLF。运行器仅在临时副本中把 `.sh`、`.toml`、`.cj` 转成 LF，使官方脚本的行尾 `sed` 匹配生效；未修改官方测试仓。临时服务进程、39137/39142 端口和测试数据已清理。

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

- `maple` 运行器在当前 WSL `PATH` 中不可用，因此没有运行完整官方 HLT/LLT；本报告只声称上述一个官方 LLT 夹具的 16 条断言。
- 单仓差分目前覆盖单个或两个直接依赖；多包传递依赖冲突、锁定旧版本后的回溯、其他官方夹具仍待扩展。
- Windows 本轮 `cjpm bundle` 在执行 `cjc -v` 时被 Application Control 阻止，故最新 Windows 五组结果为环境阻断；没有关闭或绕过该策略。
