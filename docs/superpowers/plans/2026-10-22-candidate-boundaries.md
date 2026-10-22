# 候选解释与负载边界实施计划

> **For agentic workers:** Use superpowers:executing-plans inline; finish with one fresh review.

**Goal:** 落实已确认的候选解释、资源大小边界和当前状态收敛，保持求解器与协议兼容。

**Architecture:** 在线explain只展示单包候选预览，实际解析继续用recorded。服务端在入口统一验证大小配置，发布和上游读取有界；不引入数据库或改写存储事务。

**Tech Stack:** 现有仓颉/stdx，Python标准库，已有Linux/Docker验证环境。

**Spec:** 用户已确认上一轮分析并要求实施；本文件记录本批具体设计。原求解器、官方lockfile和现有认证/完整性边界不变。

## Global Constraints

- Windows是源码来源；不执行Windows仓颉、不调整系统防护；保留全部历史产物和证据。
- 默认制品上限128MiB，环境变量CJREPO_MAX_ARTIFACT_BYTES允许1–1073741824；默认上游索引4MiB，CJREPO_MAX_INDEX_BYTES允许1–67108864；发布元数据固定上限1MiB。非法/空值退出2，不回显输入。
- 发布总帧最多为制品上限+1MiB+10字节；分块读取累计超限拒绝413，帧声明长度超限也拒绝413。普通帧/摘要错误保留400，鉴权仍先于读取。
- 上游索引/制品按实际读取字节有界，超限不保存数据；Proxy返回502，Mirror/Sync明确失败。不得仅信Content-Length，不回显包内容。
- 本批只提供大小限制；不是流式落盘、总期限、并发配额或完整资源耗尽防护。
- 只推送atomgit/main与github/main，GitHub保留noreply独立历史；不推送origin、不强推、不发布Release。

## Tasks

- [x] 在线解释：新增真实锁定1.0.0/候选2.0.0回归，旧版失败；输出Candidate preview与锁/完整图未参与说明，保留selected version等已有字段；recorded与真实构建仍为1.0.0。
- [x] 大小边界：初版旧2/18、新18/18；审查后隔离元数据断言并补临界值、分块上游与Mirror/Sync，最终同脚本旧3/24、新24/24。产品未改，不重复无关核心/TLS测试。
- [x] 固定ba9b客户端/8fc3服务端，原生核心4/4、TLS19/19与24/24；新整包联合接收27/27、bad0镜像最终大小24/24。证据留外层私有目录。
- [x] 更新当前候选入口、架构/状态说明和准确验证记录，不将旧产物容量/恢复成绩移算。最终独立审查无必须修复项；按持续授权交付，实际提交/双端推送身份以交付记录及远端核对为准。

## Review Focus

- 声明大小与实际大小分别检查，分块无Content-Length也受限；临界值不误拒绝。
- 未授权大请求不读包体，上游超限不污染既有缓存/索引；失败后同实例仍可正常工作。
- 不将候选预览说成锁定或传递依赖求解；不将recorded说成当前构建成功证明。
- 新产物身份与历史证据分离；不上传凭据、日志、工具或本地实验材料。
