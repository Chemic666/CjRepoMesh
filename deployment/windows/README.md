# Windows 一键部署

该部署入口不下载、不安装任何组件，直接使用本机已有的仓颉工具链构建并启动 CjRepo Server。

## 启动

在项目根目录执行一条命令：

```powershell
.\deployment\windows\start.ps1 -PublishToken "change-this-token"
```

默认监听 `127.0.0.1:8080`，数据持久化到 `deployment/windows/data`。脚本完成服务构建、后台启动和健康检查，运行状态写入 `deployment/windows/run`，日志写入 `deployment/windows/logs`。

该入口显式设置子进程的 `CJREPO_ADDRESS=127.0.0.1`，不会继承外部环境中可能对外开放的监听地址；启动成功或失败后均恢复调用者原有的环境变量。需要其他监听地址时，应使用单独配置的直接启动或容器部署流程。

脚本在构建前检查目标端口是否已被占用，并在健康检查后确认监听端口属于刚启动的进程。该检查使用 Windows 内置的 `Get-NetTCPConnection`；若系统不允许查询监听状态，脚本会报错，不跳过归属检查。

自定义端口、数据目录或代理上游：

```powershell
.\deployment\windows\start.ps1 `
  -Port 8081 `
  -Storage "D:\CjRepoData" `
  -PublishToken "change-this-token" `
  -Upstream "https://upstream.example.com" `
  -ProxyTtlSeconds 86400
```

若仓颉环境尚未加载，可通过 `-EnvSetup` 指定官方 SDK 的环境脚本。开发机默认自动识别 `D:\Apps\Cangjie\envsetup.ps1`。`-NoBuild` 仅用于已经构建过服务端的测试或离线重启。

令牌只通过子进程环境传递，不写入部署状态或日志。共享环境必须设置发布令牌；需要私有读取时另传 `-ReadToken`（同时必须设置 `-PublishToken`），客户端以仓库配置 `token-env` 提供相同的原始 `Authorization` 值。不要把真实令牌字面量留在命令历史；本入口目前仅默认绑定本机回环地址。`ProxyTtlSeconds` 控制代理索引刷新间隔，默认 86400 秒；带版本号并通过 SHA-256 校验的制品按不可变内容缓存。

`-Upstream` 必须是绝对 HTTP(S) 地址，不接受内嵌用户名/密码、查询参数或片段，以免 URL 中的凭据进入部署状态和服务日志。上游鉴权使用 `-UpstreamToken`。

## 检查与停止

```powershell
.\deployment\windows\doctor.ps1
.\deployment\windows\stop.ps1
```

停止脚本会核对 PID、固定服务端路径和精确 UTC 进程启动时间，再通过已绑定的进程对象停止服务；若等待退出超时，会保留部署状态，不会删除持久化数据。诊断脚本使用相同的身份与端口归属检查。

旧版 `run/cjrepo.json` 不含 `processStartTimeUtc`。若对应 PID 仍存在，新脚本会拒绝自动接管或停止：请在任务管理器中核对该 PID 的路径、启动时间及用途后，手动停止确属旧部署的服务，再运行 `start.ps1`。PID 已不存在的陈旧状态由启动/停止脚本清理。不要为通过检查而手填启动时间或删除仍在运行实例的状态文件。

当前版本仅绑定本机回环地址；面向局域网或公网部署前需显式启用读鉴权，并补充 TLS 与反向代理。
