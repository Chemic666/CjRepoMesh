# CjRepoMesh 技术可行性审查

> 审查日期：2026-09-21  
> 结论基线：`Cangjie/cangjie_tools` `main` @ `297800729322f7e04a2f9bc69e524951b6853514`  
> 文档基线：`Cangjie/cangjie_docs` `main` @ `b803781683e0fb84d6b753f6c4605ea45b7e8809`  
> 测试基线：`Cangjie/cangjie_test` `main` @ `1dfa37619f920884e119d7f51266869c8f0fd81e`
> 动态验证：2026-09-22 已在 Windows x86_64 上完成官方 cjpm 源码构建与运行验证

## 1. 结论

**值得报名官方 #6，技术上可行，但原方案需要做四项关键调整。**

1. 不应把多仓能力实现成 `Depot` 外围的一层简单重试。当前版本解析器直接从单一 `Depot` 读取索引，仓库来源尚未进入候选、缓存和锁文件模型。要正确支持同名包、同版本多来源，必须先把“仓库来源”提升为一等数据。
2. 不应新增一套与 `[replace]` 平行的 Override 语法。`cjpm` 已支持入口模块通过 `[replace]` 强制替换间接依赖，并要求中心仓替换项是单一版本。CjRepoMesh 应复用该语义，只补充来源路由或来源固定。
3. `1.3.0-company.1` 不能作为当前 cjpm 的示例版本。当前中心仓版本格式严格为三段纯数字 `x.y.z`，应改成 `1.3.1`，或另行推动版本格式演进（不建议放进比赛 MVP）。
4. “完整镜像整个官方仓”不能仅凭当前公开客户端协议完成。已确认的协议只能按已知包名读取索引和制品，没有发现公开的全仓目录或增量变更流。MVP 应定义为按需 Proxy、按包白名单 Mirror，以及 CjRepo Server 之间通过自有同步 API 做增量 Sync。

最合理的技术路线不是重写解析器，而是：

```text
现有 DepModel / DepAnalysisEngine
              │
              ▼
    RepositoryIndexProvider（新增边界）
              │
              ▼
       RepositoryRouter（新增）
       ├─ 路由与独占规则
       ├─ 仓库优先级
       ├─ 错误分类与回退
       └─ 来源选择与解释轨迹
              │
              ▼
   RegistryClient[]（从 Depot 拆出）
```

原有 `DepRecord` 的版本范围求交、最高版本优先、锁文件优先和冲突回溯算法应保留。

## 2. 研究边界

本次完成了源码、官方手册和官方 HLT/LLT 测试的静态审查，并已完成官方 `cjpm` 的 Windows 动态构建基线：

- Cangjie SDK / `cjc`：`1.1.3`；
- SDK 自带 `cjpm`：`1.1.3`；
- stdx：`1.1.3.1`（`v1.1.3` 与 `v1.1.3.1` 指向同一官方提交）；
- `libuv`：`v1.48.0` @ `e9f29cb984231524e3931aa0ae2c5dae1a32884e`；
- 源码构建的 `cjpm`：`1.3.0-alpha.05`，运行 `-v` 退出码为 0；
- 产物：`target/release/bin/cjpm.exe`，17,746,432 bytes，SHA-256 `4547933C8F8CC1AB455F6E434D424BA931AD17AAF1FC34A01BE180C77F57386A`。

此次构建已验证 SDK、stdx、C++ 桥接库和仓颉源码的本机闭环。官方 HLT/LLT 仍未执行：当前环境未安装 Maple 测试框架，后续不应把“源码可构建”表述成“官方回归已通过”。详细构建记录见 `docs/windows-build-baseline.md`。

官方公开仓库中没有发现中心仓服务端实现或完整服务端 API 规范。下文的协议结论来自当前 `cjpm` 客户端源码与官方测试夹具，可作为兼容实现基线，但不应宣称为完整官方服务端协议。

关键官方证据：

- [cangjie_tools 官方仓库](https://gitcode.com/Cangjie/cangjie_tools)
- [中心仓配置解析源码](https://gitcode.com/Cangjie/cangjie_tools/blob/main/cjpm/src/config/central_repository.cj)
- [中心仓 HTTP 客户端源码](https://gitcode.com/Cangjie/cangjie_tools/blob/main/cjpm/src/implement/depot.cj)
- [中心仓依赖求解源码](https://gitcode.com/Cangjie/cangjie_tools/blob/main/cjpm/src/implement/dep_engine.cj)
- [锁文件源码](https://gitcode.com/Cangjie/cangjie_tools/blob/main/cjpm/src/config/lock.cj)
- [官方 cjpm 手册](https://cj-docs.gitcode.com/zh/1.1.3/tools/source_zh_cn/cmd-tools/cjpm_manual.html)
- [官方 cangjie_test 仓库](https://gitcode.com/Cangjie/cangjie_test)
- [stdx.net.http 服务端能力](https://gitcode.com/Cangjie/cangjie_stdx/blob/main/doc/libs_stdx/net/http/http_package_overview.md)

## 3. cjpm 当前架构

```text
main.cj
  │
  ▼
CommandFactory
  │
  ├─ build / check / test / run / install
  ├─ update
  ├─ bundle
  └─ publish
  │
  ▼
resolve()                         loadConfigInfo()
  │                                     │
  ▼                                     ▼
DepModel                         SettingsConfig
  │                              ├─ repository.cache
  │ 收集 path/git/repo 依赖       └─ repository.home
  ▼
DepAnalysisEngine
  │
  ├─ recordLock()
  ├─ analyseRepoDeps()
  ├─ DepRecord：读取索引、求版本交集、排序
  ├─ DepAnalysisState：选择版本、冲突回溯
  └─ downloadRepoDeps()
          │
          ▼
        Depot
          ├─ GET /index/...       元数据索引
          ├─ GET /pkg/.../...     制品下载
          └─ POST /pkg/...        发布
          │
          ▼
~/.cjpm/repository
  ├─ index/{org}/{prefix}/{name}
  └─ source/{org}/{name-version}
          │
          ▼
repoDepCheck() → 包级依赖图 → 编译
          │
          ▼
cjpm.lock（精确版本；无仓库来源和 checksum）
```

官方开发者指南只给出了命令、配置、依赖管理、构建和编译器对接等宏观层次；中心仓的真实实现集中在 `config/central_repository.cj`、`implement/depot.cj`、`implement/dep_engine.cj`、`implement/dep_model.cj` 与 `config/lock.cj`。

## 4. Repository Config 调用链

### 4.1 文件查找顺序

`loadConfigInfo()` 依次检查：

1. 当前工作目录的 `cangjie-repo.toml`；
2. 用户目录 `.cjpm/cangjie-repo.toml`；
3. `$CANGJIE_HOME/tools/config/cangjie-repo.toml`；
4. 仅在适用条件下，以即将废弃的 `CJPM_CONFIG` 覆盖缓存路径。

读取到第一个存在的配置后即返回，**不会合并多层配置**。因此未来的多仓配置也应维持“单文件生效”的兼容语义，除非另行设计并明确文档化配置合并规则。

### 4.2 当前数据结构

```text
SettingsConfig
├─ repository: HashMap<String, RepositoryInfo>
│  ├─ cache: RepositoryInfo(path=...)
│  └─ home:  RepositoryInfo(registry=..., token=...)
└─ global: GlobalRepoConfig(strictTls=true)
```

有利点是 `repository` 本身已经是按名称索引的 `HashMap`，不仅仅是一个定长结构；不利点是 `Depot.loadConfiguration()` 仍硬编码读取 `repository.home`，并把它转成唯一的 `baseUrl`、`token` 和 `localRepo`。

### 4.3 推荐的兼容配置形态

不要直接采用原方案中的 `[[repository.registries]]`。当前 `repository` 被反序列化为 `HashMap<String, RepositoryInfo>`，在它下面塞数组表会与现有类型形态冲突。更低侵入的设计是保留命名表：

```toml
[repository.cache]
path = "${HOME}/.cjpm"

# 旧配置原样有效；只有 home 时进入 legacy-single 模式
[repository.home]
registry = "https://pkg.cangjie-lang.cn/registry"

[repository.company]
registry = "https://repo.company.example/registry"
priority = 100
token-env = "CJPM_COMPANY_TOKEN"

[repository.mirror]
registry = "https://mirror.company.example/registry"
priority = 80

[global]
strict-tls = true
resolution-strategy = "highest-compatible"
fallback = true

[[route]]
pattern = "company::*"
registries = ["company"]
exclusive = true
```

兼容规则应是：

- 只有 `[repository.home]` 时，行为、缓存路径、锁文件和请求顺序与上游完全一致；
- 多于一个 registry 时才启用 Router；
- `token` 继续兼容，但推荐 `token-env`；两者同时出现时报配置错误；
- `strict-tls` 第一版仍保持全局语义，避免一次引入过多配置维度。

## 5. Repository Client 与公开协议

### 5.1 当前客户端

当前没有 `Repository` 接口或抽象层，只有具体类 `Depot`。它承担了配置读取、HTTP、索引缓存、制品下载、checksum 校验和发布等多种职责。

连接超时固定为 30 秒，读取超时固定为 60 秒；HTTP client 调用了 `noProxy()`。这里的“Proxy Repository”应理解为仓库服务端的代理缓存能力，而不是依赖系统 HTTP 代理。

### 5.2 cjpm 客户端实际需要的最小 API

| 用途 | 请求 | 成功响应 |
|---|---|---|
| 读取包索引 | `GET /index/{前2字符}/{接下来1或2字符}/{name}?organization={org}` | 逐行 JSON（每行一个 `ArtifactIndex`） |
| 下载制品 | `GET /pkg/{name}/{version}?organization={org}` | `.cjp` tar.gz 字节 |
| 发布制品 | `POST /pkg/{name}?organization={org}` | 200 |

组织名为空时不附带 `organization` 查询参数，本地缓存中使用 `default` 目录。

`ArtifactIndex` 包含：

```text
organization, name, version,
dependencies, test-dependencies, script-dependencies,
sha256sum, yanked, cjc-version, index-version
```

发布请求体不是普通 multipart：它由“1 字节元数据版本 + 4 字节长度 + metadata JSON + 1 字节制品版本 + 4 字节长度 + tarball”拼接而成。服务端 MVP 必须兼容这个 framing。

### 5.3 认证的重要源码事实

当前源码只在 `POST publish` 上设置 `Authorization` header。索引 GET 和制品 GET 没有设置该 header；这与官方手册中“交互请求会附带用户 token”的笼统表述并不完全一致。

因此，真正支持“读权限私有仓”需要同时修改客户端：

- 为 index/download 附加凭证；
- 支持从环境变量取 token；
- 保持旧 `home.token` 的 header 格式兼容；
- 服务端可同时接受 legacy raw token 和显式 Bearer token，逐步迁移。

如果不改客户端，第一版私有仓只能做到“发布受保护、读取匿名”，不满足企业私有仓的合理安全预期。

## 6. Dependency Resolver 调用链

### 6.1 入口

`build/check` 最终进入 `resolve()`：

1. `loadLockFile()` 读取 `cjpm.lock`；
2. 创建 `DepModel`；
3. `DepModel.resolve()` 先把锁定的中心仓版本交给 `DepAnalysisEngine.recordLock()`；
4. `depCheck()` 递归处理本地和 Git 依赖，把中心仓依赖收集到 `repoDepList`；
5. `analyseRepoDeps()` 处理中心仓依赖；
6. 解析成功后下载源码并回到 `repoDepCheck()` 验证模块配置；
7. 形成包级拓扑图并继续编译。

### 6.2 版本选择

`DepRecord`：

- 从本地索引或远端更新后的索引中读取所有未 yanked 版本；
- 按当前需求范围筛选；
- 按 `SingleVersion` 降序排序；
- 优先复用仍满足约束的锁定版本，否则选最高可用版本。

`DepAnalysisState` 与 `DepAnalysisEngine.doStateProcessing()`：

- 逐个固定模块版本；
- 从所选版本的 index 引入传递依赖；
- 新约束使已选版本失效时回退状态并禁用冲突版本；
- 直到找到无冲突组合，或所有候选均失败。

这套逻辑就是应保留的原始 Dependency Resolution。多仓不应另写一套版本求解器。

### 6.3 多仓接入的正确切点

当前 `DepRecord` 直接接收一个 `Depot` 并通过它获取 index，这正是最合适的切点。建议改为接收 `RepositoryIndexProvider`：

```text
DepRecord
  └─ provider.listCandidates(fullName, requirement)
       → [VersionCandidate(version, registryId, checksum, index)]
```

随后仍由 `DepRecord` 做版本范围筛选和排序。最终状态除 `fixedVersionMap` 外，增加 `fixedSourceMap`，下载时使用与所选版本绑定的 registry。

## 7. “仓库优先级”必须先定语义

这是整个项目最大的设计问题，而不是编码问题。

假设：

```text
private(priority=100): foo 1.0.0
official(priority=10): foo 2.0.0
requirement: [1.0.0, 3.0.0)
```

至少有三种合理但结果不同的策略：

1. `first-match`：先选 private，再在 private 内选 1.0.0；
2. `highest-compatible`：合并所有仓的版本，选 2.0.0；相同版本才按仓库优先级选来源；
3. `source-pinned`：优先复用锁文件记录的仓库与版本。

建议：

- 单仓配置固定为 legacy 行为；
- 多仓默认采用 `highest-compatible`，最符合“仓库路由不替代 cjpm 版本解析”的设计原则；
- 如赛事评委把“优先级查找”明确解释为 first-match，再提供显式策略开关；
- exclusive namespace 在进入候选合并之前裁剪仓库集合，因此不会泄漏私有包名到公共仓。

如果同一 `name + version` 在多个仓的 checksum 不一致，默认应报冲突而不是静默按优先级选择。企业修补包应优先发布为新的三段数字版本（例如 `1.3.1`），而不是复用相同版本或使用当前不支持的 `1.3.0-company.1`。

## 8. Cache 当前行为与必须修改点

当前路径：

```text
{cache}/repository/index/{org}/{prefix1}/{prefix2}/{name}
{cache}/repository/source/{org}/{name}-{version}
```

路径中没有 registry id。同名同版本来自不同仓时会直接碰撞；一旦源码目录存在，后续构建会跳过下载，也不会重新验证缓存 checksum。

多仓模式至少应改成：

```text
{cache}/repository/registries/{registryId}/index/...
{cache}/repository/registries/{registryId}/source/{org}/{name}-{version}
```

兼容方案：

- legacy-single 模式继续读写旧目录；
- 启用多仓后使用新目录；
- 不自动移动或删除旧缓存；
- provenance 记录 registry id 与 checksum；
- 安全模式在缓存命中时验证 manifest/checksum，至少对来源切换和首次复用执行验证。

服务端采用 content-addressed blob storage 是合理的，但不要把它与 cjpm 当前客户端缓存模型混为一谈。

## 9. Lockfile 与来源追踪

当前 `cjpm.lock` 版本为 0，主体只有 `requires` 和 `scripts`。中心仓依赖通过 `DepInfo.version` 记录精确版本，没有 registry、checksum 或解析原因。

比赛 MVP 有两个选择：

### 方案 A：独立 provenance 文件（推荐 MVP）

保留 `cjpm.lock` 完全不动，新增例如 `cjpm.provenance.json`：

```text
package, version, registry, checksum, route, fallback, override
```

优点是兼容风险低、便于 explain；缺点是来源固定不是原子地存在于 lock 中。

### 方案 B：lock v1

为 `DepInfo` 增加可选 `registry` 和 `checksum`，并让新版本 reader 同时支持 v0/v1。优点是语义完整，缺点是旧 cjpm 会拒绝新 lock 或忽略新字段，回滚体验更差。

建议初赛用 A，决赛或上游合入阶段再设计 B。

## 10. Override 的方案修正

当前 `cjpm.toml` 已有 `[replace]`：

```toml
[replace]
crypto = { version = "1.3.1" }
```

源码还明确校验中心仓替换必须是单一版本。因此原方案中的：

```toml
[[repository.overrides]]
...
```

应删除，避免产生两套相互竞争的替换语义。

真正缺失的是“替换后的包应来自哪个仓”。第一版可由 namespace/route 规则解决；若确实需要单包来源选择，可增加非版本语义的 source pin，例如：

```toml
[[route]]
pattern = "crypto"
registries = ["company"]
exclusive = true
```

## 11. Security-aware Fallback

当前 `Depot` 以 `(Bool, String)` 和异常表达错误，不足以安全实现 fallback。应先引入结构化错误：

```text
NotFound(404)
Unauthenticated(401)
Forbidden(403)
RateLimited(429)
ServerError(5xx)
ConnectTimeout / ReadTimeout / ConnectionRefused
TlsFailure
IntegrityFailure
ProtocolFailure
```

建议默认规则：

| 错误 | 非独占路由 | 独占路由 |
|---|---|---|
| 404 | 尝试下一仓 | 仅在允许集合内继续 |
| timeout / connection / 5xx | `fallback=true` 时继续 | 仅在允许集合内继续 |
| 429 | 可配置；默认继续到可信公共候选 | 不越界 |
| 401 / 403 | 立即失败 | 立即失败 |
| TLS / checksum / protocol | 立即失败 | 立即失败 |

此外，exclusive route 必须在发请求之前生效，保证 `company::*` 不会被发送到 public registry，防止的不只是错误下载，还包括私有包名泄漏。

## 12. CjRepo Server 可行性

仓颉 `stdx.net.http` 同时提供客户端和服务端（`Server`、`ServerBuilder`、handler/distributor），`std.fs`、JSON serialization、SHA-256 和 tar/gzip 能力也已在 cjpm 本身使用。因此用仓颉实现轻量服务端不存在语言能力阻塞。

### Hosted MVP

必须实现：

- 上述 3 个 cjpm 兼容端点；
- 解析 publish framing；
- 校验 metadata 与 tarball checksum；
- 按组织、包名、版本维护 NDJSON index；
- 文件系统 CAS blob；
- token read/publish/admin 三类权限；
- 原子写入（临时文件 + rename）与重复版本 409；
- health、审计日志和基础 metrics。

### Proxy

技术上直接可行：按请求从 upstream 获取 index/artifact，验证 checksum 后写本地缓存，再按相同协议返回。需要定义 TTL、离线缓存和上游错误策略。

### Mirror

当前已确认协议没有全仓 catalog。初赛应实现：

- 包白名单或组织白名单的计划同步；或
- “曾被代理请求过的包”定时刷新；
- 不宣称能够无条件发现并镜像官方仓所有包。

### Sync

CjRepo Server 之间新增私有管理 API（例如 manifest/change feed）最稳妥。仅用公开的 index + artifact 接口无法拿到完整展示元数据，也无法高效枚举全仓。增量同步应以 `(org, name, version, checksum)` 为幂等键。

## 13. 具体修改点清单

| 文件/模块 | 当前职责 | 建议修改 |
|---|---|---|
| `config/central_repository.cj` | 单仓配置模型和查找 | 扩展 registry 字段、route、策略校验；保留 home 兼容模式 |
| `implement/depot.cj` | 配置、HTTP、缓存、发布混合 | 拆成 `RegistryClient`、typed error、credential provider |
| 新增 router 模块 | 无 | 路由、优先级、exclusive、fallback、trace |
| `implement/dep_engine.cj` | 版本求解、索引读取、下载 | 用 provider 取候选；状态同时记录 version 与 source |
| `implement/dep_model.cj` | 收集依赖并驱动 engine | 传入 router/context；保持 replace 语义 |
| `implement/update.cj` | 刷新单一本地 index | 按 registry 刷新并隔离错误 |
| `implement/central_repository.cj` | install/download | 使用解析后的来源和新缓存路径 |
| `config/lock.cj` | lock v0 | MVP 保持；后续评估 v1 双读 |
| `config/dependencies.cj` | `DepInfo` | 仅 lock v1 时增加来源字段 |
| `command/factory.cj`、`command/cjpm.cj` | 子命令入口与帮助 | 增加原生 `repo explain/doctor` |
| `config/meta_data.cj` | 官方 index/meta 模型 | 尽量不改，服务端直接复用协议模型 |
| 官方测试仓对应用例 | HLT/LLT | 保留旧用例，增加多仓和安全矩阵 |

## 14. 官方测试基线

官方测试不在 `cangjie_tools/cjpm` 目录内，而在 `Cangjie/cangjie_test`：

- HLT：`testsuites/HLT/Tools/cjpm/repo`，当前检出的子树有约 1066 个文件，覆盖 bundle、download、index、install、publish；
- index HLT 已覆盖 dependency type、multiple module、replace、version range；
- LLT：`testsuites/LLT/Tools/cjpm/CJNATIVE`，包含 central dependency、配置、install、update 和 repository 状态码覆盖；
- 官方已有一个本地 Python HTTP server 测试 400/403/418/429/500 等响应，非常适合扩展成多仓 fallback 安全矩阵；
- HLT/LLT 使用 Maple 测试框架。

兼容性验收不应只比较“能否 build”，至少应比较：

```text
legacy config 下：
upstream cjpm.lock == CjRepoMesh cjpm.lock
upstream selected versions == CjRepoMesh selected versions
upstream success/failure == CjRepoMesh success/failure
官方 cjpm HLT/LLT 无新增回归
```

新增测试要覆盖同包跨仓不同版本、同版本不同 checksum、401/403 不回退、exclusive 不发公共请求、缓存隔离、锁定来源、并发下载和离线 cache hit。

## 15. 功能可行性与工作量

| 能力 | 可行性 | 主要难点 |
|---|---|---|
| 多仓配置 | 高 | 兼容配置与校验 |
| 优先级 | 中高 | 跨仓同包版本语义必须先定 |
| Namespace Routing | 高 | 请求前裁剪候选，模式规则明确化 |
| Fallback | 中高 | typed error、并发和安全边界 |
| Override | 高 | 已有 `[replace]`，只需来源路由 |
| Source Pinning | 中 | cache/lock/provenance 一致性 |
| Hosted Registry | 高 | publish framing、原子索引更新 |
| Proxy | 高 | TTL、离线语义、checksum |
| 白名单 Mirror | 中高 | 包集合和调度 |
| 全仓 Mirror | 低/待接口 | 缺公开 catalog/change feed |
| CjRepo-to-CjRepo Sync | 高 | 自定义管理 API、幂等与恢复 |
| Docker 一键部署 | 高 | 打包 runtime/stdx/OpenSSL、镜像体积 |
| explain / doctor | 高 | 需要 Router 产生结构化 trace |
| Dashboard / MCP | 高但后置 | 不属于关键路径 |

粗略单人工程量（熟悉仓颉后）：

```text
基线环境、构建与官方测试         2–4 人日
客户端抽象与 legacy 兼容         5–8 人日
多仓/router/cache/provenance     8–12 人日
Hosted Server                    8–12 人日
Proxy + 白名单 Mirror + Sync     8–12 人日
集成测试、部署、文档、演示       8–12 人日
-------------------------------------------
初赛完整工程版                  39–60 人日
```

一名开发者建议预留 8–12 周；两名开发者并行、且一人专注 cjpm、一人专注 server 时，约 5–7 周。Dashboard 与 MCP 再增加约 1–3 周。以上是侦察阶段估算，不是承诺排期。

## 16. 修订后的 MVP

### 必须完成

1. 上游 cjpm 可构建，官方中心仓相关 HLT/LLT 基线通过；
2. legacy `[repository.home]` 行为和 lock 完全兼容；
3. 多 registry 配置与确定性排序；
4. `highest-compatible` 策略，或经官方确认后的 priority 策略；
5. registry-aware cache；
6. public + private 混合构建；
7. exclusive namespace；
8. 结构化错误和 security-aware fallback；
9. 复用 `[replace]` 做单版本强制替换；
10. provenance sidecar；
11. 仓颉实现的 Hosted Server；
12. Proxy cache；
13. Docker Compose 一键部署；
14. 自动化兼容性、故障与安全测试；
15. `cjpm repo explain` 与最小 `doctor`。

### 初赛可降级

- Mirror：只做白名单/已访问包定时刷新；
- Sync：只做 CjRepo-to-CjRepo 增量同步；
- Dashboard：仅 metrics 或极简只读页；
- AI/MCP：不进关键路径；
- lock v1：以 provenance sidecar 替代。

## 17. 开发顺序

```text
P0  安装匹配 SDK/stdx，构建上游 cjpm，跑官方测试
P1  为 Depot/HTTP 建 characterization tests
P2  抽出 RegistryClient 和 typed error，legacy 行为不变
P3  引入 registry-aware cache 与候选来源模型
P4  实现 Router、exclusive route、解释 trace
P5  接入 DepRecord/DepAnalysisEngine，完成双仓解析
P6  实现安全回退与 provenance
P7  实现 Hosted Server 三个兼容端点
P8  实现 Proxy 与离线 cache
P9  Docker Compose、doctor、端到端演示
P10 白名单 Mirror 与 CjRepo Sync
P11 Benchmark、安全报告、决赛增强
P12 Dashboard / MCP
```

在 P2 前不要开发 Server UI；在 P5 前不要承诺跨仓同名包的最终选择语义；在官方测试基线跑通前不要大规模改 `DepAnalysisEngine`。

## 18. 主要风险

1. **语义风险（最高）**：赛事所谓“优先级查找”对跨仓版本集合的确切含义尚不明确。
2. **回归风险（高）**：`Depot` 与解析器耦合在 `DepRecord` 内，粗暴替换容易改变锁文件与回溯顺序。
3. **缓存污染（高）**：不先加入 registry 维度就实现多仓，会出现来源串包。
4. **认证风险（高）**：当前 GET 请求不携带 token，私有读权限不能只做服务端。
5. **镜像范围风险（中高）**：缺少公开 catalog/change feed，不能把白名单同步包装成全量镜像。
6. **协议稳定性（中）**：服务端协议是从客户端源码推导的，可能存在未公开约束。
7. **工具链风险（低至中）**：SDK/stdx 和源码构建已实测通过；剩余风险是 Maple 官方回归环境与 Docker runtime 打包。
8. **上游漂移（中）**：`main` 更新频繁，应固定参赛基线并定期 rebase，而不是每天追 HEAD。

## 19. 是否值得正式报名 #6

**值得。** 该题与现有 cjpm 的边界非常清晰：上游已经有中心仓协议、版本解析、checksum、publish/bundle 与大量测试，但恰好缺少多仓来源模型、私有读认证、仓库路由和可部署服务端。这意味着项目既不是空中楼阁，也不会沦为简单 Web CRUD。

报名成立的前提是把项目叙事收紧为：

> 在不重写 cjpm 版本求解器的前提下，将仓库来源变成可路由、可固定、可解释、可审计的一等数据，并提供与 cjpm 协议兼容的仓颉原生 Hosted/Proxy/Sync 服务。

若赛程不足 6 周且只有一名开发者，应主动砍掉 Dashboard、MCP、全量 Mirror、lock v1 和复杂 RBAC，集中完成客户端多仓闭环、Hosted、Proxy、安全回退和官方回归证据。

## 20. 正式编码前必须向官方确认的三个问题

1. “按优先级查找”是 first-match，还是所有仓版本集合合并后以优先级做同版本来源决策？
2. 赛事验收中的 Mirror 是否接受包白名单/按需镜像，还是必须全量同步；若要求全量，是否会提供 catalog/change feed？
3. 私有仓是否要求下载鉴权；若要求，官方预期的 `Authorization` 格式是 legacy raw token 还是 Bearer？

这三个答案会影响协议和数据模型，应在 P2/P3 前锁定。
