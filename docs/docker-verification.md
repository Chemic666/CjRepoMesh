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

2026-09-23 在 P1 回归中再次执行 `up.ps1 → doctor.ps1 → down.ps1`，9 项仍全部 PASS，容器停止后命名卷保留。回归同时发现启动脚本会回显发布 Token；提交 `de2da77` 改为隐藏输出、使用 `SecureString` 接收显式 Token，并将 `.env` ACL 收紧为仅当前 Windows 用户。Docker Desktop 随后停止，因此这一步当时仅完成输出脱敏与 ACL 静态/权限测试；后续容器复核见下节。

## 凭据保护与重复启动复核

2026-09-23 复测时发现：已收紧 ACL 的 `.env` 上重复调用原 `Set-Acl` 会因 `SeSecurityPrivilege` 不足而失败，Compose 容器因此未启动。提交 `c602c12` 改为只写入文件访问规则，不再重设所有者；写凭据前先确认文件非符号链接、归当前用户所有并已收紧权限，写后再次读回校验。无凭据临时文件上首次与重复调用保护函数均成功。现有 `.env` 的读回结果是关闭继承、仅当前用户一条 FullControl 允许规则。

修复后两次实际执行 `up.ps1 → doctor.ps1 → down.ps1`，每次 Docker 安全/健康诊断均 **9/9 PASS**，启动输出没有回显 Token，Compose 容器结束后已移除、命名数据卷保留。用户已有的独立容器 `magical_bartik` 全程保持健康；本轮使用本地 `ubuntu:22.04` 镜像，没有下载或安装依赖。显式 `-PublishToken` 的 SecureString 参数形式尚未另做端到端容器复测，不把默认自动/复用 Token 路径等同于该分支验证。

## 边界

- 当前镜像打包流程只支持 Linux x86_64；
- 构建前需要已完成 WSL Linux 编译，并准备 Docker 基础镜像；
- 上述历史 Docker 运行只验证发布端令牌（原始 `Authorization` 值），未启用或验证后来新增的可选读取令牌；
- 本记录不等同于公网安全审计、长期压力测试或多节点高可用验证。

## 最新一键部署诊断

2026-09-23 在提交 `e5be054` 上执行标准 `up.ps1 → doctor.ps1 → down.ps1`，诊断 **9/9 PASS**，包括非 root、只读根文件系统、无新权限、localhost 绑定、持久化卷和健康 API。打包脚本读取已有 WSL 服务端二进制，SHA-256 为 `5cedbde24bf02f71d0a68da50808af9b639d6b04da4d10af9034a88c53ac44de`；产品源码自前次基线 `0f0e076` 未修改，本轮未将 Windows 挂载路径新编译的二进制复制入镜像。Compose 容器和网络已移除，命名卷保留，原独立容器 `magical_bartik` 仍为 healthy。未重复真实发布与持久化重建场景，也未测试显式 `-PublishToken` 分支。

## 2026-09-24 当前镜像复核

开机后先确认 Docker Desktop 与项目 WSL 已启动、`ubuntu:22.04` 基础镜像本地存在、项目 Compose 服务原本未运行。新增 `up.ps1 -ServerBinaryPath` 参数，明确打包本工作区最新 Linux 服务端；`.build-context/manifest.json` 中 `cjrepo` SHA-256 与源产物一致，均为 `afb896fd886525dc91ff01b9eadb3731e632e7defcbfbe8b74db5d488902d61f`。此二进制已通过同日 Linux 四组完整回归。`up.ps1` 使用已有发布令牌启动后，`doctor.ps1` **9/9 PASS**；未开启读取令牌时，合法格式但不存在的索引和制品仍返回 404。

随后仅对项目 Compose 容器临时注入随机 `CJREPO_READ_TOKEN` 并重建，不修改 `.env` 中保存的凭据或命名数据卷。两类读取请求无令牌均返回 401，正确令牌下对不存在资源返回 404；测试结束后再次重建恢复原配置，`doctor.ps1` 再次 **9/9 PASS**。

之后通过正式一键脚本复核用户入口：`up.ps1 -ReadToken` 启动后，无令牌读取为 401、正确令牌读取缺失资源为 404；`up.ps1 -DisableReadToken` 后公开读取恢复为 404。两参数互斥检查通过，最终 `doctor.ps1` 仍 **9/9 PASS**。项目容器保持运行且健康，命名数据卷保留；此前独立容器 `magical_bartik` 开机后为停止状态，本轮未触碰它。此复核没有重复真实发布、持久化重建或显式 `-PublishToken` 参数分支。
