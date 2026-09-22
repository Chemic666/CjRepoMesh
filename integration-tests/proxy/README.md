# Proxy Registry Integration Test

`run.ps1` 在本机启动一个测试上游和仓颉原生 CjRepo Proxy，验证：

1. 首次构建发生 Cache MISS；
2. 索引和制品分别只访问上游一次；
3. 缓存落盘前验证索引身份和制品 SHA-256；
4. 关闭上游并清空 cjpm 客户端缓存后，Cache HIT 仍可完成构建运行。

脚本不访问互联网，也不会安装依赖。
