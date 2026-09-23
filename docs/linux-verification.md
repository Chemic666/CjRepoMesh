# CjRepoMesh Linux 原生验证记录

> 首次执行：2026-09-22；最近全量核心回归：2026-09-23
> 原生构建基线：`b7fc9a2`；统一回归提交：`8e33119`
> 结论：Linux 原生构建、服务启动和四组共享核心端到端回归通过；Docker 验证另行记录

## 环境

| 项目 | 值 |
| --- | --- |
| 宿主系统 | Windows + WSL 2 |
| Linux | Ubuntu 22.04.5 LTS（x86_64） |
| 仓颉 SDK | 1.1.3（cjnative，Linux x64） |
| stdx | 1.1.3.1（Linux x64，static） |
| CMake | 3.22.1 |
| GCC | 11.4.0 |
| Python | 3.10.12 |
| libuv | v1.48.0，提交 `e9f29cb` |

SDK 压缩包 SHA-256 与官方下载页公布值一致：

```text
2b68905afc466e665ae181595c63f96c18d75fd2c1fb6c6f0cb64e179c28d61a
```

## 验证结果

| 场景 | 结果 | 证据 |
| --- | --- | --- |
| 官方 Linux 构建链 | PASS | `Successfully build libfswatcher!`、`Successfully build cjpm!` |
| 增强版 cjpm 可执行文件 | PASS | Linux x86-64 ELF；版本 `1.3.0-alpha.05` |
| CjRepo Server 编译 | PASS | `cjpm build success` |
| CjRepo Server 运行 | PASS | `GET /health` 返回 `{"status":"ok","service":"cjrepo"}` |
| 缺失资源语义 | PASS | 不存在的索引返回 HTTP 404 |
| 多仓候选聚合 | PASS | high 仓提供 1.0.0，low 仓提供 1.0.0/2.0.0，应用实际输出 `low-2.0.0` |
| 离线来源解释 | PASS | 记录版本 2.0.0、仓库 `low`、Registry URL 和 SHA-256 |

## 四组共享核心回归

提交 `3fee985` 新增 Python 标准库编排层，提交 `8e33119` 修复 Windows 受控环境的临时目录 ACL 兼容问题。Windows 与 Linux 共用同一套夹具、断言、安全边界和清理逻辑；PowerShell 与 Bash 仅为平台入口。执行命令：

```bash
source /home/chemic/apps/cangjie-1.1.3/envsetup.sh
export CANGJIE_STDX_PATH=/home/chemic/apps/stdx-1.1.3.1/linux_x86_64_cjnative/static/stdx
cd /home/chemic/work/CjRepoMesh-src
./integration-tests/run-linux.sh
```

运行器在统一入口中实际调用一次 `cjpm build` 编译 CjRepo Server，并依次执行：

| 测试组 | 结果 | 耗时 |
| --- | --- | ---: |
| Multi-repository cjpm | PASS | 59.23s |
| Hosted repository | PASS | 6.56s |
| Proxy repository | PASS | 7.50s |
| Repository sync | PASS | 3.94s |
| **合计** | **4/4 PASS** | **77.25s** |

覆盖内容与 Windows 核心四组一致，包括版本/来源冲突、Replace、Explain、Doctor、Provenance、401 阻断、独占 Namespace、Hosted 并发发布、Proxy 并发填充/TTL/离线/损坏拒绝，以及 Mirror/Sync 鉴权、幂等、部分失败和源仓离线构建。

额外以错误的 `CJREPO_PORT`、存储、上游、Token 和 TTL 污染调用环境，再用 `--skip-server-build` 运行 Hosted、Proxy、Sync，结果 3/3 PASS，耗时 28.71s。这证明运行器会隔离调用者残留的仓库环境变量；该次补充运行不替代上面的真实服务端编译。

测试完成后使用 `ss` 与 `pgrep` 复核固定测试端口和测试进程，未发现残留。运行器自身还会在每组结束时确认端口关闭，并在成功或失败路径统一清理夹具产物、应用缓存、锁文件、Provenance、请求日志和临时存储。

关键来源记录为：

```text
Recorded resolution:
  package: meshdep
  version: 2.0.0
  repository: low
  registry: http://127.0.0.1:39142
  checksum: sha256:19e29fd28e5e77a95b6e9441c065bfc2d651e77443d8bf00e47417032b92a0f4
```

## 构建入口

在已加载 `envsetup.sh` 且设置 `CANGJIE_STDX_PATH` 后：

```bash
cd cjpm/build
python3 build.py build -t release --target native

cd ../../server
../cjpm/dist/cjpm build
```

本次验证使用现有本地源码和依赖，没有在构建过程中下载、安装或解压内容。官方构建脚本在缺少 `cjpm/cpp/third_party/libuv` 时会尝试联网拉取，因此复验前应先准备固定版本的 libuv 源码。

## 边界

- Linux 入口覆盖四组可跨平台核心测试；Windows 一键部署是平台专属第五组，Docker Compose 的独立结果见 `docs/docker-verification.md`；
- 本次使用 WSL 构建副本执行，但所有源代码修改均来自 Windows 主仓库；
- Windows 五组已在相同提交内容上重跑；最终提交前仍必须分别执行 Windows、Linux 和 Docker 回归；
- 尚未运行依赖额外官方测试资产的完整 Maple HLT/LLT。

## 最新四组复核

2026-09-23 在提交 `e5be054` 上，通过 WSL 挂载路径直接运行 Windows 工作区的 `integration-tests/run-linux.sh`。已有增强版 Linux cjpm 被复用，入口实际重新编译当前工作区的 CjRepo Server。四组 **4/4 PASS，总耗时 184.08s**：多仓 151.12s、Hosted 12.87s、Proxy 10.72s、Sync 5.97s。新增菱形依赖图的相容来源和冲突拒绝均纳入多仓组。固定测试端口和 `integration-tests/.tmp` 在结束后无残留。此次没有重编译 cjpm，也没有运行 Windows 原生五组或完整 Maple HLT/LLT。
