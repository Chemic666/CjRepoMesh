# CjRepoMesh Docker Compose 验证记录

> 执行日期：2026-09-23  
> 部署实现基线：`233f7c8`  
> 结论：镜像构建、一键启动、真实发布、容器重建持久化和安全诊断全部通过

## 环境与制品

| 项目 | 值 |
| --- | --- |
| Docker | Docker Desktop，Linux containers |
| 基础镜像 | `ubuntu:22.04` |
| 基础镜像摘要 | `sha256:b8b6ee6aa931ecd9d0d952abc34dc0e5f7c6a30c6bb71b079fe399fde0329c02` |
| 目标架构 | Linux x86_64 |
| 最终镜像 | `cjrepomesh:local` |
| 最终镜像大小 | 159,045,490 bytes |
| Docker 构建上下文 | 约 15 MB；服务二进制和两项仓颉运行时库 |

本次 Docker 构建不在容器中重新编译仓颉源码，也不执行 `apt install`。准备脚本从已验证的 WSL 构建中复制最小运行产物，并记录 SHA-256：

| 文件 | 大小 | SHA-256 |
| --- | ---: | --- |
| `cjrepo` | 10,625,480 bytes | `5cedbde24bf02f71d0a68da50808af9b639d6b04da4d10af9034a88c53ac44de` |
| `libcangjie-runtime.so` | 4,380,408 bytes | `6ac1c91488100ef87c273bd9ab5015f712bc91f566f3bac74150a4485d2adc36` |
| `libboundscheck.so` | 71,720 bytes | `3ad04fe38be88d5123078bd11d78cbc82377c114f6e6514b393ecd374e559bb7` |

## 一键部署结果

执行：

```powershell
.\deployment\docker\up.ps1
```

结果：

- 自动准备被 Git 忽略的最小构建上下文；
- 自动生成发布 Token，并在重复部署时稳定复用；
- 镜像成功构建，容器成功启动；
- `GET /health` 返回 `{"status":"ok","service":"cjrepo"}`；
- 端口仅发布到宿主机 `127.0.0.1:8080`。

## 真实仓库与持久化验证

使用仓颉测试包 `meshdep 2.0.0` 完成：

1. 携带自动生成的 Token 发布，HTTP 状态 200；
2. 索引查询返回 HTTP 200；
3. 下载制品与原制品 SHA-256 一致；
4. 执行 `down.ps1` 销毁容器但保留命名卷；
5. 再次执行 `up.ps1` 重建容器；
6. 旧制品仍可下载，SHA-256 再次一致。

这证明数据来自 Docker 持久化卷，而不是进程内状态或旧容器文件层。

## 安全与运行诊断

执行：

```powershell
.\deployment\docker\doctor.ps1
```

实测 9 项全部 PASS：

```text
Container running        PASS
Docker healthy           PASS
Non-root user            PASS
Read-only root           PASS
Capabilities dropped     PASS
No new privileges        PASS
Localhost binding        PASS
Persistent volume        PASS
Registry API             PASS
Overall                  PASS
```

具体约束包括：

- 容器用户为 `10001:10001`；
- 根文件系统只读；
- Linux capabilities 全部移除；
- 启用 `no-new-privileges`；
- `/tmp` 为受限 tmpfs；
- 包数据只写入 `/var/lib/cjrepo` 命名卷；
- 默认不向局域网暴露端口。

## 边界

- 当前镜像打包流程只支持 Linux x86_64；
- 构建前需要已完成 WSL Linux 编译，并准备 Docker 基础镜像；
- 读取端尚未鉴权，发布端使用 Bearer Token；
- 本记录不等同于公网安全审计、长期压力测试或多节点高可用验证。
