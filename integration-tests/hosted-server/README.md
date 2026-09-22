# Hosted Registry Integration Test

`run.ps1` 使用本地已有的仓颉工具链完成以下验证，不访问网络：

1. 编译并启动仓颉原生 CjRepo Server；
2. 验证健康检查和错误发布令牌的 401 响应；
3. 验证服务端拒绝 SHA-256 不匹配的制品；
4. 使用 `cjpm publish` 发布包，并验证重复发布的 409 响应；
5. 验证 cjpm 索引协议；
6. 下载制品并比对 SHA-256；
7. 使用增强版 cjpm 从 CjRepo Server 解析、下载、编译并运行依赖。
8. 两个相同版本并发发布时恰好一个成功、一个返回 409，索引和制品保持完整。

```powershell
.\run.ps1
```
