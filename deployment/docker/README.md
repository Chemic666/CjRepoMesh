# Docker Compose 部署

该部署把 WSL 中已经编译的 Linux CjRepo Server 与两项必要的仓颉运行时库打包进最小运行镜像。最终容器不包含编译器、stdx 源文件或完整 SDK，并以非 root 用户、只读根文件系统和无 Linux capabilities 运行。

## 前置条件

- Docker Desktop 已启动并使用 Linux containers；
- `CjRepoMesh` WSL 中已经完成 Linux 构建；
- 默认路径与 `docs/linux-verification.md` 一致。路径不同时可通过脚本参数覆盖。

脚本不会下载、安装或解压仓颉 SDK。若本机没有 `ubuntu:22.04` 基础镜像，Docker 在构建时会按正常行为拉取它。

## 一键启动

从项目根目录执行：

```powershell
.\deployment\docker\up.ps1
```

脚本会：

1. 从 WSL 复制服务二进制和最小运行时库到被 Git 忽略的临时上下文；
2. 记录每个文件的 SHA-256；
3. 自动生成发布 Token，并仅写入被忽略的 `.env`；
4. 构建、启动并等待 `/health` 通过。

若新服务端在 Windows 工作区的 WSL 挂载路径中构建，可明确指定该 Linux 二进制，避免误用 WSL 原生目录中较早的产物：

```powershell
.\deployment\docker\up.ps1 -ServerBinaryPath ".\server\target\release\bin\main"
```

脚本仍从选定的 WSL 发行版复制运行时库，并在 `.build-context/manifest.json` 记录实际打包文件的 SHA-256。

重复执行且未显式传入 `-PublishToken` 时，脚本会复用已有 `.env` 中的 Token，避免普通重建意外轮换凭据。
启动输出不会回显 Token 值，避免终端日志或演示录屏泄露凭据。

指定端口或上游代理时，Token 使用 `SecureString`，避免明文进入 PowerShell 历史：

```powershell
$publishToken = Read-Host "Publish token" -AsSecureString
$readToken = Read-Host "Read token (optional for private downloads)" -AsSecureString
$upstreamToken = Read-Host "Upstream token (optional)" -AsSecureString
.\deployment\docker\up.ps1 `
  -Port 18080 `
  -PublishToken $publishToken `
  -ReadToken $readToken `
  -Upstream "https://upstream.example.com" `
  -UpstreamToken $upstreamToken
```

在 Windows 上，脚本先确认 `.env` 属于当前用户并非符号链接，再保护空文件或已有文件的访问规则，然后写入 Token，最后读回校验权限：关闭继承且只保留当前用户的完全控制权。重复启动也会重新校验，不要求额外的系统安全特权。`-ReadToken` 为可选项；设置后 Hosted/Proxy 索引和制品读取均需相同的原始 `Authorization` 值，重复启动会沿用已有 `.env` 中的读取令牌。要恢复公开读取，显式运行 `up.ps1 -DisableReadToken`；此开关不能与 `-ReadToken` 同用。发布 Token 由脚本自动生成或沿用，服务端拒绝只配读取令牌、不配发布令牌。Compose 会把 Token 注入运行容器的环境变量，因此拥有本机 Docker 管理权限的用户仍可通过容器检查读取它；Token 不会进入 Git、Docker 构建上下文或镜像层。

## 运行诊断

运行安全与健康诊断：

```powershell
.\deployment\docker\doctor.ps1
```

诊断会检查服务 API、Docker 健康状态、非 root 用户、只读根文件系统、capability、安全选项、仅本机端口绑定及持久化卷。

## 停止与数据

默认停止时保留 Docker 命名卷中的包：

```powershell
.\deployment\docker\down.ps1
```

明确需要同时删除持久化包数据时：

```powershell
.\deployment\docker\down.ps1 -PurgeData
```

`-PurgeData` 不可恢复，应只用于测试环境。

## 冷备份与恢复验证

包数据位于 `cjrepo-data` 命名卷，镜像或容器重建不等于数据备份。实际备份前，应停止本实例及写入该卷的 watcher，确认卷名后导出完整的 `index`、`artifacts` 和组织子目录；凭据和部署参数另行保管。恢复时使用新卷，不覆盖原卷，恢复后核对文件 SHA-256、私有读取及客户端构建，再安排业务切换。不要让两个服务进程同时写同一卷。

仓库提供独立的冷备份演练入口，使用已有本地镜像和真实 cjpm 包：

```cmd
python integration-tests\recovery\docker_backup.py --image cjrepomesh:local --cjpm cjpm\target\release\bin\cjpm.exe
```

它只创建带唯一标记的测试卷和容器，不读取当前 Compose 项目的 `.env` 或操作其数据卷，不拉取镜像。源服务停止后，以只读卷挂载导出 tar，并恢复到另一个新卷；核对完整文件集合和 SHA-256，再验证全新缓存构建、再次发布和重启读取。结束后只清理自己创建的资源；失败先保存容器日志和状态，再清理容器、保留测试卷。可用 `--evidence-dir <新目录>` 保留日志、清单及合成包的备份归档。

该入口验证部署流程，不能对现有业务卷直接执行备份或恢复。当前已验证的镜像、产物与结果见 [验证报告](../../docs/verification-report.md)。在线快照、自动备份调度、业务切换和断电持久性不在通过范围内。

## 安全边界

- 容器内监听 `0.0.0.0` 仅用于 Docker 网络；宿主机发布范围由 Compose 端口映射决定；
- 默认自动生成发布 Token；读取鉴权需显式传入 `-ReadToken`，未启用时仍为公开读取；
- `.env` 和 `.build-context` 均已加入 `.gitignore`，不得手工提交；
- 当前 Docker 方案只支持 Linux x86_64。
