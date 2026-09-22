# CjRepoMesh

CjRepoMesh 是面向仓颉与 cjpm 的原生多仓依赖和企业私有仓基础设施，目标是完成仓颉生态创新开发挑战赛技术课题 #6 的四项交付：多仓与优先级、依赖冲突与强制替换、私有中心仓一键部署，以及代理/镜像/同步。

## 当前可运行能力

- cjpm 命名多仓配置、优先级和禁用仓库；
- 跨仓版本聚合，继续由原 cjpm 求解器选择版本；
- 原生 `[replace]` 强制版本在多仓下生效，并遵循仓库优先级与回退规则；
- `cjpm repo explain <package>` 展示需求、替换、路由、候选版本、来源仓和 SHA-256；
- 构建生成 `cjpm-provenance.json`，`repo explain --recorded` 可在仓库离线时审计来源；
- `cjpm repo doctor [package]` 逐仓诊断配置、认证、元数据 API 与安全回退判定；
- 同版本按仓库优先级确定来源；
- 404/5xx 回退，401/403 安全阻断；
- `token-env` 私有读认证；
- `exclusive` 命名空间路由和 Dependency Confusion 防护；
- 单仓旧配置和缓存布局兼容；
- 仓颉原生 CjRepo Server 健康检查、发布、索引和制品下载；
- 发布令牌校验、服务端 SHA-256 复核和重复版本冲突保护；
- Proxy Cache MISS/HIT、上游状态透传、缓存前 SHA-256 校验；
- 上游离线后的缓存构建，以及损坏上游制品拒绝；
- 并发发布原子化与并发 Proxy 首次填充合并，避免索引/制品损坏和重复上游请求；
- Proxy 索引 TTL 刷新，版本化制品保持校验后不可变缓存；
- 按指定包/版本主动 Mirror，重复执行幂等且不访问上游；
- 带令牌的 CjRepo-to-CjRepo 增量 Sync，源仓离线后目标仓可独立构建；
- Windows 一条命令完成构建、后台启动和健康检查，支持安全停止与持久化重启；
- 可重复 Proxy Benchmark，保留 Cold/Warm 原始样本及 Median/P95 报告；
- CjRepo Server 到增强版 cjpm 的端到端构建验证。

## 验证入口

```powershell
integration-tests\multirepo\run.ps1
integration-tests\hosted-server\run.ps1
integration-tests\proxy\run.ps1
integration-tests\sync\run.ps1
integration-tests\deployment\run.ps1
benchmark\proxy\run.ps1
```

Windows 一键部署入口见 `deployment/windows/start.ps1`。当前未完成 organization 支持、读鉴权、按包细粒度锁、批量 Mirror 清单、断点续传和 Docker/Linux 部署验证，不应把本阶段描述为完整参赛版本。详细进度见 [参赛与获奖就绪度](docs/award-readiness.md) 和 [官方验收矩阵](docs/competition-requirements-matrix.md)。
