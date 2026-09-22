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
| Multi-repository cjpm | 多仓聚合、优先级、`[replace]`、Explain、Doctor、Provenance、认证屏障、独占路由和旧配置兼容 |
| Hosted repository | 发布、索引、下载、鉴权、SHA-256、重复版本和并发原子写 |
| Proxy repository | MISS/HIT、并发填充合并、索引 TTL、离线缓存和损坏拒绝 |
| Repository sync | 批量 Mirror/Sync 清单、部分失败汇总、目标仓发布鉴权、幂等和源仓离线构建 |
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

运行器会在开始前拒绝已占用的固定测试端口，在每组结束时回收全部子进程并确认端口关闭。服务端仅构建一次，夹具产物、应用缓存、锁文件、Provenance 和请求日志会在成功或失败后统一清理；服务端存储使用系统临时目录。

脚本遇到子测试抛出的第一处失败即停止，全部通过后打印每组耗时汇总。部分安全测试会故意执行应当失败的客户端命令，因此统一入口以测试断言结果而不是最后一个原生命令的退出码判断整组状态。Proxy 性能测试不纳入功能回归，需独立运行：

```powershell
.\benchmark\proxy\run.ps1
```

共享运行器不包含 Windows 部署或 Docker Compose：前者由 `integration-tests/deployment/run.ps1` 验证，后者由 `deployment/docker/doctor.ps1` 独立验证。完整官方 Maple HLT/LLT 也不属于该入口。
