# cjpm 多仓实现状态

> 更新日期：2026-10-21
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
- `cjpm repo explain <package> --recorded` 支持离线读取保存的依赖解析结果，仅接受当前支持的 `formatVersion = 1`；记录不代表编译成功；
- 在线 `cjpm repo explain <package>` 是单包候选预览，明确忽略 `cjpm.lock` 与传递依赖约束；`selected version` 是预览候选，实际锁定构建可能不同。要查看实际解析，先构建，再用 `--recorded`；本批不改变原求解器或锁文件格式，也不提供来源基线强制校验。
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

命名仓与多仓模式的缓存现在同时绑定配置名称和经过安全检查的**原始 URL 字符串的完整 SHA-256**，索引与解包源码使用同一个分区：

```text
{cache}/repository/registries/{name}/{sha256(exact-url)}/index/{organization}/...
{cache}/repository/registries/{name}/{sha256(exact-url)}/source/{organization}/{package}-{version}
```

同名仓改为另一个地址会使用新的分区，成功来源记录必须对应新仓的索引与内容；切回原地址可按既有缓存策略复用它自己的缓存。这里不做URL等价归一化，尾斜杠等字符串差异也会分开。令牌不参与缓存身份，普通令牌轮换不清空缓存；这不撤销已下载文件的本地访问权限，同一URL下切换账户/租户时应使用不同仓名或缓存根目录。

**升级注意：** 以前的 `registries/{name}/index` 和 `source` 目录不会删除，也不会自动迁移或被当作新分区读取，因为缺少可靠的原始地址绑定；升级后命名仓首次使用需联网重新预热，不能直接承诺复用旧缓存离线构建。

仅启用一个 `repository.home` 时仍保留旧 `repository/index` 和 `repository/source` 布局，未加入地址分区，以保持原版兼容。此模式更换URL仍须使用新的缓存根目录；从多仓切回此模式时也需核对旧 `home` 缓存，避免沿用原地址的内容。`--recorded` 解释上次保存的依赖解析结果，不检测当前缓存是否被外部修改。记录在依赖解析与下载成功后写入，早于后续编译，不能单独证明整个构建已成功；本次401在解析阶段失败时保留旧记录，但不据此推断所有构建失败都不改记录。

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

## 选源后的增量构建

索引、下载源码和来源记录指向新仓，并不自动保证已有应用target已经使用新内容。两个仓可提供同版本且相同时间戳的包；即使依赖库已重新编译，类型信息的时间戳也可能无法反映需要重新链接的实现变化。

客户端因此将实际源码目录的规范路径加入增量输入身份，命名仓URL分区变化会使旧输入失效。静态主要产物（`.a`或已有LTO路径的`.bc`）以流式SHA-256形成内部内容指纹；最终链接任务沿用现有 `getDepSet` 规则，观察它实际链接的传递静态库。普通中间静态库原来的类型信息依赖规则保留，未改变版本求解、LTO/combine策略或编译器参数。

静态任务的内部缓存哈希增加版本标记，使旧的“只检查产物存在”记录在升级后一次失效；标记只用于缓存判断，不传给编译器。原target和缓存不需要手动清空，首次构建可能重编译静态库；这不表示所有增量编译场景或大项目性能已验收。相同路径下刻意保留全部源码元数据的编辑，以及任意动态库/Obj的时间戳情况，不在本次针对性修复的验证范围。

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
