# Hosted Registry Integration Test

`run.ps1` 使用本地已有的仓颉工具链完成以下验证，不访问网络：

1. 编译并启动仓颉原生 CjRepo Server；
2. 验证健康检查；
3. 验证 cjpm 索引协议；
4. 下载制品并比对 SHA-256；
5. 使用增强版 cjpm 从 CjRepo Server 解析、下载、编译并运行依赖。

```powershell
.\run.ps1
```
