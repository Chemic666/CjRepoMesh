# cjpm 多仓实现状态

> 更新日期：2026-10-20
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
- `cjpm repo doctor [package]` 逐仓检查真实 Metadata API，并标识允许或禁止回退；
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

仓库配置严格检查已提供字段的类型：`priority` 是整数，`enabled`、`exclusive`、`strict-tls` 是布尔值，地址、令牌环境变量名和路由名称是字符串。可选字段省略时保留原默认值；`exclusive = "true"`、`enabled = "false"` 等写法会在访问仓库前失败，不会静默转成默认值。字符串字段也在原始 TOML 层检查，未加引号的日期/时间不能冒充字符串；其他 cjpm 配置文件仍使用原转换规则。错误提示只包含字段名和预期类型，不回显配置值。

仓库地址只接受不含用户名/密码、查询参数、片段、反斜线及 ASCII 空白/控制字符的 HTTP(S) 基地址；authority 中的百分号编码也拒绝，因此当前不接受带 zone identifier 的 IPv6 地址。鉴权使用 `token-env`，地址可以带普通反向代理路径。该约束会在仓库请求、在线解释及新来源记录之前检查；离线 `--recorded` 也会拒绝显示旧来源记录中的不安全地址，原文件不被自动改写。

回退规则按明确响应分类：404 与 5xx 可尝试下一个允许仓库；400、401、403、429、连接拒绝、连接重置、读取超时、截断响应和损坏索引均停止。独占路由只允许目标仓库，即使它返回 404 或 5xx，也不会访问公共仓。`doctor` 会独立探测所有允许的仓库，其探测不等于依赖解析发生回退。

缓存以配置中的仓库名称作为隔离身份，不以 URL 自动重新分区。把同一名称改指向无关服务时，必须同时更换仓库名称及缓存根目录；旧单仓 `home` 则使用新的缓存根目录。否则旧索引和源码可能继续命中，不能把新配置地址理解为本次发生了重新下载。`--recorded` 只解释成功构建时保存的记录，不检测当前缓存是否被外部修改。

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
| 菱形跨仓传递依赖 | 两分支汇聚同一底层版本，三包来源与 SHA-256 一致 | PASS（Linux 多仓单组） |
| 菱形分支版本冲突 | 两分支要求互斥底层版本时明确失败 | PASS（Linux 多仓单组） |
| 同版本来源冲突 | 高优先级仓获胜 | PASS |
| `[replace]` 强制版本 | 宽范围依赖被锁定到指定单版本 | PASS |
| 替换版本来源回退 | 优先仓 404 后从下一仓取得同一版本 | PASS |
| 替换版本不存在 | 明确失败并指出 `replace` 制品不存在 | PASS |
| `repo explain` | 普通解析与替换场景的版本、来源和校验和与真实构建一致 | PASS |
| 来源持久化 | 构建后仓库离线，仍能解释上次选定来源与校验和 | PASS |
| `repo doctor` | 正常仓逐仓 200；401 显示认证屏障并返回失败 | PASS |
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
- 多仓 install/publish 的显式目标仓选择；
- 完整 Maple HLT/LLT。

在来源持久化完成前，不应宣称锁文件能够复现仓库来源。当前 Dependency Confusion 防护仅覆盖显式配置的独占路由，不等于所有命名空间自动受保护。
