# Mirror and Repository Sync Integration Test

`run.ps1` 验证两条独立能力：

1. `cjrepo mirror-manifest` 按批量清单主动预取、校验并落盘；
2. 重复镜像整份清单时逐项返回幂等 SKIP，且不访问上游；
3. 清单中存在错误时继续处理后续项，输出成功/失败汇总并返回非零状态；
4. `cjrepo sync` 从 CjRepo Source 拉取并校验制品，通过带令牌的发布协议增量写入 CjRepo Destination；
5. 重复同步返回幂等 SKIP；
6. 关闭 Source 后，Destination 仍可供 cjpm 完成构建运行。

脚本不访问互联网，也不会安装依赖。
