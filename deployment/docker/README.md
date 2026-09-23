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

重复执行且未显式传入 `-PublishToken` 时，脚本会复用已有 `.env` 中的 Token，避免普通重建意外轮换凭据。
启动输出不会回显 Token 值，避免终端日志或演示录屏泄露凭据。

指定端口或上游代理时，Token 使用 `SecureString`，避免明文进入 PowerShell 历史：

```powershell
$publishToken = Read-Host "Publish token" -AsSecureString
$upstreamToken = Read-Host "Upstream token (optional)" -AsSecureString
.\deployment\docker\up.ps1 `
  -Port 18080 `
  -PublishToken $publishToken `
  -Upstream "https://upstream.example.com" `
  -UpstreamToken $upstreamToken
```

`.env` 写入后会在 Windows 上移除继承权限，只保留当前用户的完全控制权。Compose 会把 Token 注入运行容器的环境变量，因此拥有本机 Docker 管理权限的用户仍可通过容器检查读取它；Token 不会进入 Git、Docker 构建上下文或镜像层。

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

## 安全边界

- 容器内监听 `0.0.0.0` 仅用于 Docker 网络；宿主机发布范围由 Compose 端口映射决定；
- 默认自动生成发布 Token，读取端当前仍未鉴权；
- `.env` 和 `.build-context` 均已加入 `.gitignore`，不得手工提交；
- 当前 Docker 方案只支持 Linux x86_64。
