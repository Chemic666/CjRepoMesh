# CjRepoMesh 端到端验证

在已经安装仓颉 SDK、stdx 和 Windows 构建工具的环境中，从项目根目录运行：

```powershell
.\integration-tests\run-all.ps1
```

统一入口不会下载或安装任何依赖，会依次运行五组测试：

| 测试组 | 主要覆盖 |
| --- | --- |
| Multi-repository cjpm | 多仓聚合、优先级、`[replace]`、Explain、Doctor、Provenance、认证屏障、独占路由和旧配置兼容 |
| Hosted repository | 发布、索引、下载、鉴权、SHA-256、重复版本和并发原子写 |
| Proxy repository | MISS/HIT、并发填充合并、索引 TTL、离线缓存和损坏拒绝 |
| Repository sync | 批量 Mirror 清单、部分失败汇总、带令牌增量 Sync、幂等和源仓离线构建 |
| Windows deployment | 一条命令构建启动、健康检查、持久化重启、诊断和安全停止 |

可显式指定增强版 cjpm 和环境脚本：

```powershell
.\integration-tests\run-all.ps1 `
  -Cjpm "D:\path\to\cjpm.exe" `
  -EnvSetup "D:\Apps\Cangjie\envsetup.ps1"
```

脚本遇到子测试抛出的第一处失败即停止，全部通过后打印每组耗时汇总。部分安全测试会故意执行应当失败的客户端命令，因此统一入口以测试断言结果而不是最后一个原生命令的退出码判断整组状态。Proxy 性能测试不纳入功能回归，需独立运行：

```powershell
.\benchmark\proxy\run.ps1
```

当前全量入口验证的是 Windows 本地闭环；它不等价于尚未执行的 Linux/Docker 验证或完整官方 Maple HLT/LLT。
