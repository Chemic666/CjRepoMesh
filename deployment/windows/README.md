# Windows 一键部署

该部署入口不下载、不安装任何组件，直接使用本机已有的仓颉工具链构建并启动 CjRepo Server。

## 启动

在项目根目录执行一条命令：

```powershell
.\deployment\windows\start.ps1 -PublishToken "change-this-token"
```

默认监听 `127.0.0.1:8080`，数据持久化到 `deployment/windows/data`。脚本完成服务构建、后台启动和健康检查，运行状态写入 `deployment/windows/run`，日志写入 `deployment/windows/logs`。

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

令牌只通过子进程环境传递，不写入部署状态或日志。共享环境必须设置发布令牌。`ProxyTtlSeconds` 控制代理索引刷新间隔，默认 86400 秒；带版本号并通过 SHA-256 校验的制品按不可变内容缓存。

## 检查与停止

```powershell
.\deployment\windows\doctor.ps1
.\deployment\windows\stop.ps1
```

停止脚本会核对 PID 对应的可执行文件路径后再终止进程，不会删除持久化数据。当前版本仅绑定本机回环地址；面向局域网或公网部署前仍需补充 TLS、读鉴权及反向代理。
