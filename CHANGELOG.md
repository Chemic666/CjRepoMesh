# Changelog

本文件记录 CjRepoMesh 对仓颉 `cangjie_tools` 的参赛扩展。上游工具链版本为
`1.3.0-alpha.05`；下列内容尚未作为独立正式版本发布。

## Unreleased 2026-09-25

### Added

- 为 cjpm 增加多仓配置、候选版本聚合、同版本来源优先级、独占命名空间、`token-env` 认证、仓库感知缓存与来源 SHA-256 审计；保留原有依赖求解与 `[replace]` 语义。
- 增加 `cjpm repo explain` 和 `cjpm repo doctor`，分别解释解析来源与诊断连接、认证及回退边界。
- 增加仓颉原生 CjRepo Server，支持 Hosted、Proxy 缓存、清单式 Mirror、CjRepo-to-CjRepo Sync、组织名隔离、私有读取令牌和周期 watcher。
- 提供 Docker Compose、Windows 部署脚本、跨平台端到端集成测试、官方 Maple 本地子集兼容性入口与可复验 Proxy 基准。
- 增加答辩材料、部署与验证报告，以及明确标为“实测输出重放”的视频辅助素材生成脚本。

### Security and reliability

- 通过 `.gitattributes` 固定 Unix Shell 和 Python 入口为 LF，避免 Windows `core.autocrlf=true` 检出后 WSL 因 `bash\r` 无法启动脚本。
- 401/403 认证或授权失败时阻止跨仓回退；独占命名空间下缺包或上游故障时不访问公共仓。
- 发布和代理缓存校验 SHA-256；并发首次填充按有界包键锁分片；Sync 在传输前比较索引与制品校验和，Mirror 只公开已验证的本地版本。
- Docker 服务默认非 root、只读根文件系统、丢弃 Linux capabilities，仅绑定本机端口并使用持久化命名卷。

### Verification

- 2026-09-25：从当前源码重建服务端后，Linux 四组核心回归 4/4 PASS、255.51 秒；Docker Doctor 9 项及 Overall PASS。完整时间戳终端记录保存在本地外层 `test-runs/video/`，详见 `docs/verification-report.md`。
- 在公开提交 `31567a61` 上四组 4/4、230.19 秒；修复换行后在 Windows 干净工作树 `6c4dbc8a` 上再次四组 4/4、230.47 秒，失败和成功日志分别保留在外层 `test-runs/`。
- 官方 Maple 仅选定本地子集分别通过，未运行完整 HLT/LLT；当前 Windows 原生复测受系统 Code Integrity 对未签名 SDK 的拦截限制。历史结果与当前结果分开列示，不合并宣称。

### Known limits

- Mirror 是显式清单镜像，不是官方中心仓全量复制；watcher 是单进程轮询，尚无持久化游标、字节级断点续传或多实例协调。
- `cjpm-provenance.json` 是独立来源审计文件，不是官方 lockfile。
