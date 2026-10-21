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
