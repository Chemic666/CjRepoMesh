# CjRepo Server

仓颉原生的 CjRepoMesh 私有中心仓服务端。当前已提供可运行的 HTTP 服务骨架、健康检查，以及默认 organization 的 Hosted Registry 只读协议切片（索引和制品下载）。随后在同一进程内增加发布、鉴权、Proxy 和 Sync API。

## 本地运行

先加载仓颉环境并设置 `CANGJIE_STDX_PATH`，然后执行：

```powershell
cjpm run
```

默认监听 `127.0.0.1:8080`，可通过 `CJREPO_PORT` 修改端口。存储目录默认为当前目录下的 `storage`，可通过 `CJREPO_STORAGE` 修改。

健康检查：

```text
GET /health
```

## Hosted Registry 只读布局

```text
storage/
├── index/default/<前两字符>/<随后字符>/<包名>
└── artifacts/default/<包名>/<版本>/<包名>-<版本>.cjp
```

当前兼容的 cjpm 请求：

```text
GET /index/<前两字符>/<随后字符>/<包名>
GET /pkg/<包名>/<版本>
```

服务端会拒绝包含危险路径片段的请求；不存在的索引或制品返回 404。
