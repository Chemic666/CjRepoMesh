# cjpm Windows 构建基线

> 验证日期：2026-09-22  
> 平台：Windows x86_64  
> 源码：`Cangjie/cangjie_tools` @ `297800729322f7e04a2f9bc69e524951b6853514`

## 1. 已验证结果

| 项目 | 结果 |
|---|---|
| Cangjie Compiler | `1.1.3 (cjnative)` |
| Target | `x86_64-w64-mingw32` |
| SDK 自带 cjpm | `1.1.3` |
| stdx | `1.1.3.1` |
| llvm-mingw | `20220906` / Clang `15.0.0` / MSVCRT |
| CMake | `3.31.10` |
| Ninja | `1.13.2` |
| libuv | `v1.48.0` @ `e9f29cb984231524e3931aa0ae2c5dae1a32884e` |
| 源码构建 cjpm | `1.3.0-alpha.05` |
| 构建结果 | `cjpm build success` |
| 运行结果 | `cjpm.exe -v` 退出码 0 |

产物：

```text
D:\Projects\CjRepoMesh\upstream-cangjie-tools\cjpm\target\release\bin\cjpm.exe
size: 17746432 bytes
baseline sha256: 4547933C8F8CC1AB455F6E434D424BA931AD17AAF1FC34A01BE180C77F57386A
current modified sha256: 5807027C6BE56A578033F24D8A146BB50FF90C450B1FAA2C851F32D436843C23
```

## 2. 本机路径

```text
CANGJIE_HOME       = D:\Apps\Cangjie
CANGJIE_STDX_PATH  = D:\Apps\Cangjie\stdx\1.1.3.1\windows_x86_64_cjnative\static\stdx
MINGW_PATH         = D:\Apps\Cangjie\build-tools\llvm-mingw-20220906-msvcrt-x86_64
CMake              = D:\Apps\Cangjie\build-tools\cmake-3.31.10-windows-x86_64
Ninja              = D:\Apps\Cangjie\build-tools\ninja-1.13.2
```

## 3. Windows/Ninja 特殊处理

上游 `build/build.py` 在 Windows 上硬编码使用 `MinGW Makefiles` 和 `mingw32-make`。本机使用已安装的 Ninja 代替 make，未修改上游源码。

`cpp/llvm-mingw-toolchain.cmake` 把 `CMAKE_SYSROOT` 设置为 `${MINGW_PATH}/x86_64-w64-mingw32`，而 20220906 Windows 发布包的头文件位于 `${MINGW_PATH}/include`。上游 Python 脚本会把整个 `include` 复制到 target 目录。为避免修改已安装工具链，本次通过后置的编译参数把 sysroot 重定向 llvm-mingw 根目录：

```text
-DCMAKE_C_FLAGS=--sysroot=<MINGW_PATH>
-DCMAKE_CXX_FLAGS=--sysroot=<MINGW_PATH>
```

这使 `libuv.a` 和 `libfswatcher.a` 在不复制头文件、不修改上游源码的情况下成功生成。两个静态库被放入 `cjpm/cpp/out/`，随后执行官方文档给出的 `cjpm build -o cjpm`。

## 4. 尚未完成

- Maple 测试框架尚未准备；
- 已手工运行官方 LLT 中的本地 `http_status_matrix` 夹具，脚本退出码为 0，已观测到 index/download/publish 的 400、403、404、409、418、429、500 和连接中断分支；
- 官方 cjpm 完整 HLT/LLT 尚未运行；
- 尚未建立上游 cjpm 与 CjRepoMesh 的差分回归报告。

因此，当前结论是“官方 cjpm 可构建、产物可运行，且一组本地 Repository LLT 夹具已通过”，不是“官方测试已全部通过”。

## 5. 首次改动后的回归

2026-09-22 已加入第一批向后兼容的多仓配置骨架：

- `RepositoryInfo` 支持 `priority`、`enabled` 与 `token-env`；
- `SettingsConfig.getRegistryNames()` 过滤本地 cache 与禁用仓，并按优先级降序、名称升序产生确定顺序；
- `Depot` 可按仓库名称加载配置，默认参数仍为 `home`；
- `token` 与 `token-env` 互斥，环境变量缺失时明确失败；
- 未改变现有调用点，旧单仓路径继续使用 `repository.home` 与原缓存目录。

修改后结果：

| 验证 | 结果 |
|---|---|
| 源码重新构建 | 通过，`cjpm build success` |
| 产物运行 | 通过，`1.3.0-alpha.05` |
| 官方 `http_status_matrix` 本地夹具 | 通过，脚本退出码 0 |
| 覆盖的旧行为 | index/download/publish 状态码与连接中断处理 |

## 6. 多仓解析首个可运行闭环

在配置骨架之上，已完成并实测：

- 按 `priority` 降序建立 Repository Router；
- 聚合各仓版本候选，继续交给原 `DepRecord` 选择最高兼容版本；
- 两仓存在同名同版本时，由仓库优先级确定制品来源；
- 记录内存态 `package + version -> Depot` 映射，从选定来源下载；
- 多仓缓存使用 `repository/registries/<name>/...` 隔离；
- 单一 `repository.home` 继续使用原 `repository/...` 目录；
- 404、5xx 可以尝试下一仓；401 不允许回退；
- GET 索引与制品请求支持 `token-env` 令牌；
- `company::*` 形式的 Namespace Routing 与独占仓库限制；
- `cjpm update` 可逐仓刷新已缓存索引。

`integration-tests/multirepo/run.ps1` 已一次性通过以下场景：

1. 高优先级仓提供 1.0.0、低优先级仓提供 2.0.0时，原求解器选择 2.0.0；
2. 两仓同时提供 1.0.0 时，从高优先级仓下载；
3. 404 回退；
4. 5xx 回退；
5. 401 阻断回退，低优先级仓请求数为 0；
6. `token-env` 缺失失败、正确令牌成功；
7. 旧式 `repository.home` 的 run、update 和缓存路径保持兼容。
8. 独占命名空间只访问私有仓；私有仓 404 时也不访问含更高版本同名包的公共仓。

当前仍未完成锁文件 provenance、`repo explain`，也尚未运行 Maple 全量 HLT/LLT。
