# Mirror and Repository Sync Integration Test

`run.ps1` 验证两条独立能力：

1. `cjrepo mirror` 按显式包和版本主动预取、校验并落盘，重复执行不访问上游；
2. `cjrepo sync` 从 CjRepo Source 拉取并校验制品，通过带令牌的发布协议增量写入 CjRepo Destination；
3. 重复同步返回幂等 SKIP；
4. 关闭 Source 后，Destination 仍可供 cjpm 完成构建运行。

脚本不访问互联网，也不会安装依赖。
