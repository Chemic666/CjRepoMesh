# cjpm 多仓实现状态

> 更新日期：2026-09-22  
> 状态：首个端到端闭环已运行；不是完整赛事交付版

## 已实现

- 命名仓库配置：`priority`、`enabled`、`token-env`；
- 仓库名校验与确定性优先级排序；
- Repository Router；
- 多仓索引聚合；
- 原 cjpm 版本求解器继续决定最终版本；
- 同版本来源按仓库优先级确定；
- 版本与来源仓的内存映射；
- 从选定仓库下载并校验 SHA-256；
- 多仓索引、源码缓存隔离；
- 404、5xx 回退；
- 401、403 等安全错误不回退；
- 私有仓 GET 请求令牌；
- Namespace Routing；
- `exclusive = true` 私有命名空间隔离；
- 多仓 `cjpm update`；
- 原生 `[replace]` 单版本强制替换在多仓候选与下载链路中保持生效；
- `cjpm repo explain <package>` 复用真实 Router 与 DepRecord 输出解析决策；
- `cjpm-provenance.json` 原子记录最终版本、仓库名称、地址与 SHA-256；
- `cjpm repo explain <package> --recorded` 支持离线审计上一次真实构建；
- 旧 `repository.home` 配置和缓存路径兼容。

当前已验证的配置示例：

```toml
[repository.cache]
path = "./cache"

[repository.private]
registry = "https://repo.company.example"
priority = 100
token-env = "CJPM_PRIVATE_TOKEN"

[repository.official]
registry = "https://pkg.cangjie-lang.cn/registry"
priority = 10

[[route]]
namespace = "company::*"
registry = "private"
exclusive = true

[global]
strict-tls = true
```

`exclusive = true` 表示匹配的包只会访问目标仓库；404、401 或 5xx 都不会越过这条边界访问其他仓库。

当前版本选择语义：

```text
所有允许仓库的版本候选
        ↓
原 cjpm 版本范围与冲突求解
        ↓
最终版本
        ↓
若该版本存在于多个仓库，按 priority 选择来源
```

因此，仓库优先级不覆盖版本求解。例如高优先级仓只有 1.0.0、低优先级仓有 2.0.0，需求允许二者时仍选择 2.0.0。这符合“不得破坏原有依赖解析规则”的要求。

强制替换继续使用 cjpm 已有语义：

```toml
[dependencies]
meshdep = "[1.0.0, 3.0.0)"

[replace]
meshdep = "1.0.0"
```

这里 `[replace]` 决定必须使用 1.0.0；Repository Router 再从能提供该版本的仓库中按优先级选源，并在允许的错误类型上回退。当前没有另造 `repository.overrides`，也不允许 `[replace]` 绕过独占命名空间和认证边界。

## 自动验证

入口：`integration-tests/multirepo/run.ps1`

| 场景 | 期望 | 当前结果 |
|---|---|---|
| 跨仓版本聚合 | 选择最高兼容版本 | PASS |
| 同版本来源冲突 | 高优先级仓获胜 | PASS |
| `[replace]` 强制版本 | 宽范围依赖被锁定到指定单版本 | PASS |
| 替换版本来源回退 | 优先仓 404 后从下一仓取得同一版本 | PASS |
| 替换版本不存在 | 明确失败并指出 `replace` 制品不存在 | PASS |
| `repo explain` | 普通解析与替换场景的版本、来源和校验和与真实构建一致 | PASS |
| 来源持久化 | 构建后仓库离线，仍能解释上次选定来源与校验和 | PASS |
| 404 | 回退下一仓 | PASS |
| 5xx | 回退下一仓 | PASS |
| 401 | 立即失败，不访问下一仓 | PASS |
| token-env | 缺失失败，正确令牌成功 | PASS |
| `company::*` 独占路由 | 公共仓请求数为 0 | PASS |
| 私有仓 404 | 禁止回退含同名高版本包的公共仓 | PASS |
| 单仓兼容 | run/update/旧缓存路径正常 | PASS |
| 官方 HTTP 状态矩阵 | 原错误行为不变 | PASS |

## 明确未完成

- 仓库级 fallback 配置开关；
- TLS/网络异常的结构化分类；
- `cjpm repo doctor`；
- 多仓 install/publish 的显式目标仓选择；
- 完整 Maple HLT/LLT。

在来源持久化完成前，不应宣称锁文件能够复现仓库来源。当前 Dependency Confusion 防护仅覆盖显式配置的独占路由，不等于所有命名空间自动受保护。
