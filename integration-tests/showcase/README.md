# 连贯企业依赖场景

这个入口把现有功能串成一次真实运行：同名高版本公共包、内部包保护、上游停服、私有副本与离线来源解释。使用真实 `cjpm bundle` 制品、编译与运行，不需要公网仓，也不会下载依赖工具。它是本地合成场景，不代表真实企业部署或官方 Maple 验收。

## 运行

2026-10-26最终候选复演使用客户端`5dd187b5…`和服务端`8b34570e…`，Linux实跑 **7/7、41.41秒**，完整身份见[候选清单](../../docs/candidate-acceptance.md)。本机继续暂停Windows仓颉程序执行，下面Windows命令仅为平台入口说明，不属于本轮复演。Docker接收、真人操作和官方Maple分别验收。

先加载已安装的匹配 SDK/stdx 环境，准备已构建的增强版 cjpm 与 Server。在项目根目录执行；默认连续占用五个本机端口 `39750`～`39754`，已占用时拒绝启动，可用 `--port` 更换起始端口。

Windows CMD（环境加载方法见项目操作说明）：

```cmd
python integration-tests\showcase\run.py --cjpm cjpm\target\release\bin\cjpm.exe
```

Linux：

```bash
# CLIENT_KIT：已校验的完整客户端包目录；DEMO_SERVER：匹配摘要的现有Linux服务端ELF。
# DEMO_REPORT：不存在的新报告目录。先设置这三个绝对路径并加载SDK/stdx环境。
python3 -B "$CLIENT_KIT/verify.py"
python3 -B integration-tests/showcase/run.py --cjpm "$CLIENT_KIT/cjpm" --server "$DEMO_SERVER" --output-dir "$DEMO_REPORT"
```

服务端ZIP中的`image.tar`是容器镜像归档，不能作为`--server`输入；容器接收按[离线服务端说明](../../deployment/portable/README.md)执行。此入口不会下载、解包或构建工具链，也不要求另找设备。

可用 `--server` 指定其他现有服务端；`--output-dir` 指定**不存在的新目录**。默认报告写入被 Git 忽略的 `integration-tests/.tmp/enterprise-report-*`。成功只清理本次自建服务数据与项目，报告保留；失败同时保留夹具。仅停止本次启动的服务，不处理占用端口的其他进程。

## 七个检查点

| 阶段 | 实际验证 | 观察依据 |
| --- | --- | --- |
| 无独占路由的对照 | 可接受范围内的公共 `company::auth 9.0.0` 被选中 | 运行标记、完整来源记录；同一增强客户端，非官方原版对照 |
| 内部命名空间保护 | `company::*` 只去私有仓，选内部 `auth 1.0.0`；普通依赖仍选公共 `meshdep 2.0.0` | 运行标记、版本/来源/摘要；公共入口没有收到内部命名空间请求，包含缓存命中 |
| 错误令牌 | 私有仓返回 401，构建失败且不回退 | 非零退出、401、公共入口请求数不变、没有成功来源记录 |
| 上游停服 | 全新客户端缓存仍能构建 | 上游端口关闭；私有仓及预热且校验过的 Proxy 缓存继续服务 |
| 同步私有副本 | 两个真实包同步成功，重复同步为 `SKIP` | 目标匿名读取 401；授权下载与源归档逐字节一致 |
| 副本独立构建 | 关闭原私有仓与 Proxy 后，全新客户端只用副本构建 | 源端口关闭、运行标记、两包来源均为副本 |
| 离线来源解释 | 所有仓停止后仍显示包名、版本、仓库、地址、SHA-256 | `repo explain --recorded` 输出及来源文件未变 |

服务启动时还会并发发布两个不同组织的包；无路由对照会从冷 Proxy 下载两个包，覆盖共享父目录的并发创建路径。目录锁只保护创建目录，网络下载和不同包写入仍可并行。

`summary.md` 是方便讲解的摘要；`summary.json` 包含阶段事实与时间，`inputs.json` 固定两份二进制、运行器和共享工具摘要，`artifacts.json` 列出本次真实归档摘要，`logs/` 与 HTTP 请求记录供追查。原始日志及失败 JSON 可能包含测试机路径，公开前应审阅，不自动提交报告。

“离线”指指定源服务停止，操作系统仍连网；本演练不测试公网性能、在线备份、自动故障切换、断电持久性或完整 HLT/LLT。完整冷备份恢复另见[恢复专项](../recovery/README.md)。该入口不会生成 PPT 或录像。
