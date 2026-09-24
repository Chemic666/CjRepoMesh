# CjRepoMesh 端到端验证

四组核心测试由同一个 Python 标准库运行器编排，Windows 与 Linux 共用夹具、断言、安全边界和清理逻辑；PowerShell 与 Bash 仅负责加载平台环境。Windows 一键部署是平台专属的第五组。

## Windows 全量入口

在已经安装仓颉 SDK、stdx 和 Windows 构建工具的环境中，从项目根目录运行：

```powershell
.\integration-tests\run-all.ps1
```

统一入口不会下载或安装任何依赖，会先运行四组共享核心测试，再运行 Windows 部署测试：

| 测试组 | 主要覆盖 |
| --- | --- |
| Multi-repository cjpm | 多仓聚合、优先级、跨仓传递依赖与冲突、`[replace]`、Explain、Doctor、Provenance、认证屏障、独占路由和旧配置兼容 |
| Hosted repository | 发布、索引、下载、私有读取鉴权、SHA-256、重复版本和并发原子写 |
| Proxy repository | MISS/HIT、私有读取拦截上游访问、并发填充合并、索引 TTL、离线缓存和损坏拒绝 |
| Repository sync | 批量 Mirror/Sync 清单、部分失败汇总、源仓读取与目标仓发布鉴权、幂等和源仓离线构建 |
| Windows deployment | 一条命令构建启动、健康检查、持久化重启、诊断和安全停止 |

可显式指定增强版 cjpm 和环境脚本：

```powershell
.\integration-tests\run-all.ps1 `
  -Cjpm "D:\path\to\cjpm.exe" `
  -EnvSetup "D:\Apps\Cangjie\envsetup.ps1"
```

已有服务端二进制且只需复验运行链路时，可显式使用 `-SkipServerBuild`；正式全量回归不得使用该参数代替服务端编译。

## Linux / WSL 全量入口

先加载现有 Linux SDK 并指定 stdx；脚本不会自行下载、安装或解压依赖：

```bash
source /path/to/cangjie/envsetup.sh
export CANGJIE_STDX_PATH=/path/to/stdx/linux_x86_64_cjnative/static/stdx
./integration-tests/run-linux.sh
```

默认使用 `cjpm/dist/cjpm` 和 `server/target/release/bin/main`。路径不同时使用环境变量覆盖：

```bash
export CJREPOMESH_CJPM=/path/to/enhanced/cjpm
export CJREPOMESH_SERVER=/path/to/cjrepo
./integration-tests/run-linux.sh
```

可只运行单组：

```bash
./integration-tests/run-linux.sh --suite multirepo
./integration-tests/run-linux.sh --suite hosted
./integration-tests/run-linux.sh --suite proxy
./integration-tests/run-linux.sh --suite sync
```

运行器会在开始前拒绝已占用的固定测试端口，在每组结束时回收全部子进程并确认端口关闭。服务端仅构建一次，夹具产物、应用缓存、锁文件、Provenance 和请求日志会在成功或失败后统一清理；服务端测试存储使用被 Git 忽略的 `integration-tests/.tmp/`。

## 官方原版兼容性差分

在 Linux 上准备同一源码基线的官方原版 cjpm 后，可比较旧单仓配置的直接与传递依赖版本、冲突、锁文件转换、依赖树与缓存，并运行本地官方 HTTP 状态 LLT 夹具：

```bash
python3 integration-tests/compatibility/run.py \
  --official-cjpm /path/to/official/cjpm/dist/cjpm \
  --enhanced-cjpm /path/to/CjRepoMesh/cjpm/dist/cjpm \
  --official-fixture /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/repository/coverage/http_status_matrix
```

原版构建与测试范围、实际结果见 `docs/official-compatibility-report.md`。本入口不代替完整 Maple HLT/LLT。

## 官方 Maple 框架选定用例对照

准备独立检出的官方 `cangjie_test_framework`、`cangjie_test`，以及同一源码基线的原版与增强版 Linux cjpm。加载 SDK 与 stdx 后运行：

```bash
python3 integration-tests/compatibility/maple_smoke.py \
  --framework /path/to/cangjie_test_framework \
  --fixture /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/repository/coverage/http_status_matrix \
  --config-suite /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/config/coverage \
  --install-coverage /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/install/coverage \
  --install-local-suite /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/install/local \
  --uninstall-suite /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/uninstall \
  --update-wrong-config /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/update/wrong_config \
  --update-coverage /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/update/coverage \
  --archive-fixture /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/CJNATIVE/install/coverage/repository_archive_matrix \
  --test-config /path/to/cangjie_test/testsuites/LLT/Tools/cjpm/test.cfg \
  --official-cjpm /path/to/official/cjpm \
  --enhanced-cjpm /path/to/enhanced/cjpm \
  --results-dir /path/to/test-results
```

入口仅在临时副本中把 HTTP 状态与本地索引刷新用例的 `.sh`、`.toml`、`.cj` 行尾规范为 LF；官方 Git 跟踪文件不变。Maple 对官方 HTTP 状态、三个配置、五个安装覆盖、十七个本地安装、四个卸载、两个更新错误配置和七个更新覆盖用例，共三十九个选定用例分别运行两版 cjpm，要求每版 `39/39 PASS`。本地安装、卸载和新增更新用例使用各自独立临时 `HOME`，且把其 `.cjpm/bin` 加入测试进程的 `PATH`，避免污染用户环境并使安装命令可被后续断言找到。本地索引刷新只访问 `127.0.0.1:39138`，入口检查测试端口释放。另外运行 `repository_archive_matrix`：它原样试跑会因官方夹具动态 gzip 时间戳偶发哈希不一致，入口只在测试副本中固定 gzip mtime 为 0，再要求两版各 `1/1 PASS`。结果日志和原始/稳定化测试服务脚本摘要保存在唯一的 `--results-dir/run-*` 中。稳定化矩阵不能表述为未经调整的官方用例通过；该入口也不代表完整 HLT/LLT。

另有 `integration-tests/compatibility/maple_local_bundle.py` 专门运行官方 `LLT/Tools/cjpm/CJNATIVE/repo/bundle` 下的 23 个本地打包用例。它先检查用例数量及命令未变，再逐例以隔离 `HOME` 对照原版和增强版，并将 46 份日志写到指定 `--results-dir`；不运行外部发布用例。参数为 `--framework`、`--bundle-suite`、`--test-config`、`--official-cjpm`、`--enhanced-cjpm`、`--results-dir`，路径含义与上述入口一致。

脚本遇到子测试抛出的第一处失败即停止，全部通过后打印每组耗时汇总。部分安全测试会故意执行应当失败的客户端命令，因此统一入口以测试断言结果而不是最后一个原生命令的退出码判断整组状态。Proxy 性能测试不纳入功能回归，需独立运行：

```powershell
.\benchmark\proxy\run.ps1
```

## Docker 私有仓持久化专项

先通过 `deployment/docker/up.ps1` 构建当前服务端镜像，然后在 Windows 上运行：

```powershell
python integration-tests/docker_persistence.py
```

脚本使用随机命名的独立 Compose 项目、端口、发布/读取令牌和命名卷，不修改正在运行的主项目容器或其数据。它验证无令牌读取/发布均为 401、授权发布后索引和制品可读、强制重建容器后数据及 SHA-256 保留、重复发布仍为 409；结束时只清理该测试项目及其卷。制品是合成字节，仅用于验证服务端协议和持久化，不替代真实 cjpm 打包/安装端到端测试。

共享运行器不包含 Windows 部署或 Docker Compose：前者由 `integration-tests/deployment/run.ps1` 验证，Docker 健康/安全项由 `deployment/docker/doctor.ps1` 验证，持久化专项由上面的独立脚本验证。完整官方 Maple HLT/LLT 也不属于这些入口。
