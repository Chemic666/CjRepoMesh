# CjRepoMesh Linux 原生验证记录

> 执行日期：2026-09-22  
> 参赛源码提交：`b7fc9a2`  
> 结论：Linux 原生构建、服务启动和关键多仓闭环通过；Docker 尚未验证

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

- 本记录证明 WSL 2 中的 Linux 原生编译和关键运行链路，不等同于 Docker Compose 一键部署验证；
- Linux 下尚未提供与 `integration-tests/run-all.ps1` 等价的全量统一入口；
- 五组完整端到端回归仍以 Windows 验证报告为准；
- 尚未运行依赖额外官方测试资产的完整 Maple HLT/LLT。
