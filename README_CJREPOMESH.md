# CjRepoMesh

CjRepoMesh 是面向仓颉与 cjpm 的原生多仓依赖和企业私有仓基础设施，目标是完成仓颉生态创新开发挑战赛技术课题 #6 的四项交付：多仓与优先级、依赖冲突与强制替换、私有中心仓一键部署，以及代理/镜像/同步。

## 当前可运行能力

- cjpm 命名多仓配置、优先级和禁用仓库；
- 跨仓版本聚合，继续由原 cjpm 求解器选择版本；
- 同版本按仓库优先级确定来源；
- 404/5xx 回退，401/403 安全阻断；
- `token-env` 私有读认证；
- `exclusive` 命名空间路由和 Dependency Confusion 防护；
- 单仓旧配置和缓存布局兼容；
- 仓颉原生 CjRepo Server 健康检查、索引和制品下载；
- CjRepo Server 到增强版 cjpm 的端到端构建验证。

## 验证入口

```powershell
integration-tests\multirepo\run.ps1
integration-tests\hosted-server\run.ps1
```

当前未完成发布、鉴权、Docker 一键部署、Proxy、Mirror 和 Sync，不应把本阶段描述为完整参赛版本。详细进度见 [参赛与获奖就绪度](docs/award-readiness.md) 和 [官方验收矩阵](docs/competition-requirements-matrix.md)。
