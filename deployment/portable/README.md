# CjRepoMesh 离线服务端交付包

适用于单实例、Linux amd64 容器。接收端需要 Python 3.10+、已运行的 Docker Engine 与 Docker Compose v2；启动服务不需要仓颉 SDK、源码仓库或开发机 WSL。开发者运行仓颉项目仍需匹配的 SDK/stdx 及增强版 cjpm，本包不包含客户端。

## 接收端首次启动

将完整交付目录复制到可写目录。在该目录执行以下命令；Linux 将 `python` 换成 `python3`：

```console
python verify.py
docker load --input image.tar
python verify.py --docker
python configure.py --port 8080
docker compose -f compose.yaml --env-file .env up -d --no-build --pull never
docker compose -f compose.yaml --env-file .env ps
```

等待容器变为 healthy，访问 `http://127.0.0.1:8080/health`。如果端口已占用，应先在初始化时选择其他端口。首次配置会生成独立的 Compose 项目名、发布令牌和读取令牌，保存至 `.env`，不输出令牌值。Windows 先设置并验证当前用户独占的文件权限，Linux 使用0600；不修改系统安全策略。再次配置会拒绝覆盖已有 `.env`，重启直接沿用原文件。

如果权限初始化失败，可能保留空 `.env`，此时没有写入令牌。容器入口要求读写令牌均非空，缺失时拒绝启动，不会降级为匿名读写。确认文件为空并排除权限问题后，才移除该空文件重新初始化；不要删除已有部署的凭据文件。

该包固定使用清单中的镜像，不构建、不自动拉取。校验包括全部交付文件的大小及SHA-256；`--docker`另核对已导入镜像身份和镜像内服务端摘要。完整性检查不证明发行者身份，应通过可信渠道确认清单摘要。附带 LICENSE 为项目许可；镜像包含Ubuntu用户空间及仓颉运行时，不包含完整SDK。

校验与初始化以当前调用脚本所在目录为准，已知交付文件必须是普通文件；不能用指向另一交付目录的 `verify.py` 或 `configure.py` 链接替代。这样可避免校验别的包或把新凭据写到别处。它不提供对恶意替换整个包或并发篡改的真实性保证。

默认只绑定本机回环地址，读取和发布均需相应令牌。此包先解决独立交付；跨机器访问、HTTPS入口及团队接入应另行配置和验证，不以本地健康检查代替。

本包服务端的Proxy/Mirror/Sync上游读取与Sync发布不自动跟随HTTP跳转。请配置直接提供索引、制品或发布响应的端点；遇到3xx先修正仓库/网关地址，不把另一个地址的响应当作原仓库成功，也不自动转发发布包体。需要重定向的服务必须先调整端点，本包不提供自动跨端点跳转兼容。

出站TCP连接默认最多等待30秒/次。需要调整时，在本部署受保护的 `.env` 中加入 `CJREPO_CONNECT_TIMEOUT_SECONDS=10`，有效范围为整数1–300；省略时使用30，空值或非法值令服务启动失败，诊断不回显原值。Compose通过现有 `env_file` 将其传入容器，仅在宿主命令行设置变量不足以完成配置；修改后使用本页显式Compose命令重建服务以生效，并保留原项目名、凭据和数据卷。原库15秒读写超时不变；此选项只约束每次TCP建连，不约束DNS、TLS握手或完整同步总时长。

## 运行中的部署诊断

服务healthy后，在原交付目录执行：

```console
python verify.py --running
```

此模式先校验交付文件，再从原 `.env` 读取项目名和端口；通过显式Compose文件定位唯一实例，核对运行/健康状态、镜像与容器内服务端摘要、项目/服务标签、数据卷名称及标签、非root/只读根/禁止额外capability与privileged等权限限制和精确回环端口绑定。最后只访问本机健康接口，不使用代理或跟随跳转，不回显Docker检查结果、令牌或错误正文。未启动/已停服、改了项目名或容器不匹配均失败，不把其他健康服务当作本部署。HTTP已能响应时Docker仍可能处于starting，应等待其健康检查完成后再运行。

诊断不创建、启停容器或修改配置/数据；容器内只执行读取摘要的sha256sum。它只确认运行环境中读写令牌非空，不比对 `.env` 中的令牌或验证实际私有读写权限，成功后仍须按团队示例验证发布/下载及真实构建。`--running`与`--docker`互斥：前者检查现有部署，后者检查已加载镜像并临时运行摘要命令；普通文件校验不需要Docker。

## 凭据与客户端

在受保护环境中读取 `.env`，将 `CJREPO_READ_TOKEN` 配到客户端进程环境变量，再由 `cangjie-repo.toml` 的 `token-env` 引用；发布操作使用 `CJREPO_PUBLISH_TOKEN`。开发与CI应分别使用自己的本地缓存；本版令牌为实例级读/写区分，不是逐用户或逐组织授权。

同机读取端的最小配置如下；发布时改为引用发布令牌所在的环境变量：

```toml
[repository.cache]
path = "./cjpm-cache"
[repository.home]
registry = "http://127.0.0.1:8080"
token-env = "CJREPO_READ_TOKEN"
```

不要上传 `.env` 或包含它的已初始化目录。Docker管理权限可以查看容器环境变量。Compose文件使用 `.env` 作为容器凭据来源；执行命令前核对当前进程没有覆盖 `COMPOSE_PROJECT_NAME`、`CJREPO_HOST_PORT` 的同名变量。所有命令显式使用 `-f compose.yaml`，防止同目录额外覆盖文件或 `COMPOSE_FILE` 改变已校验的镜像、端口和挂载配置。

## 停止与重建

```console
docker compose -f compose.yaml --env-file .env down
docker compose -f compose.yaml --env-file .env up -d --no-build --pull never
```

普通 `down` 保留命名数据卷；不要加 `-v`。保留 `.env` 中的项目名，重建才能重新连接该卷。不要重跑初始化、随意换项目名或让多个服务进程共用可写存储。只保留镜像不构成数据备份；应停服后另行备份完整数据卷、配置和凭据，恢复到新卷核对后再切换。

## 制作端

源码仓库中使用已构建的本地服务端镜像执行：

```console
python deployment/portable/package.py --image cjrepomesh:delivery-20261021 --output ../CjRepoMesh-offline
```

制作端创建按完整镜像ID命名的本地别名并导出镜像，复制白名单文件，记录服务端及交付文件摘要。只接受新输出目录，不读取开发部署的 `.env`、SDK目录、客户端缓存或业务卷。生成目录包含 `image.tar`、`compose.yaml`、`configure.py`、`verify.py`、`README.md`、`LICENSE` 和 `manifest.json`；复制这七份文件即可交付。若制作失败，应保留失败输出供检查，新运行使用另一个空目录。

输出路径已存在时，包括悬空目录链接，应在访问Docker前拒绝；不通过解析链接将它当作新的目标路径。旧交付归档不自动更新，领取新包时核对清单与归档摘要，保留原部署的配置和数据。

当前包为试点交付，未提供自动升级、自动备份、故障切换或容量保证。实际执行记录以源码仓库的验证报告为准。
