# CjRepoMesh 答辩材料

## 当前材料与工程入口（2026-10-21）

参赛者已确认初赛正式视频约5分39秒、播放正常，正式模板已填写并本人签字导出PDF，邮件投递成功；这些身份与签字材料仅保存在私有目录。下列2026年9月的DOCX/PPT和视频重放均为历史草稿，不能取代正式材料，也不据其旧“待录制/待签字”文字判断当前提交状态。

决赛PPT暂缓，当前先完善作品。最新[连贯场景](../integration-tests/showcase/README.md)、[源码讲解与演示路线](../docs/demo-runbook.md)、[产物验证范围](../docs/verification-report.md)是工程复验入口；七阶段自动结果不是新屏幕录像。本批URL与并发修复已交付AtomGit与GitHub，提交号和验收边界见[交付记录](../docs/delivery-record.md)，不把较早的材料提交号当作当前代码。

## 2026-09-23～09-26 历史材料与当时状态

- `CjRepoMesh-official-form-draft-2026-09-26.docx`：基于组委会统一模板回填的 5 页技术草稿。已用 Microsoft Word 打开、导出并逐页检查；项目技术内容、作品类型、使用环境和“不申请仓颉 AI 生态贡献加分”已填写。队伍名称、负责人、成员、电话、邮箱、正式视频链接、签字和日期保留为参赛者操作，不能直接当作已签字提交件。
- `CjRepoMesh-technical-defense-redesign-2026-09-23.pptx`：推荐预览的重设计版，8 页可编辑文字，封面和安全案例使用概念插画。插画仅用于视觉表达，不是部署截图或测试证据。
- `CjRepoMesh-technical-defense-2026-09-23.pptx`：8 页可编辑技术答辩稿，按约 7 分钟讲述设计。每页的演讲者备注列出证据文档、讲述重点与建议时间。
- 源文件：`../tools/build-technical-defense-redesign.mjs` 和 `../tools/build-technical-defense.mjs`。它们使用随附的演示文稿运行时制作，不下载项目依赖。重新生成前须将同名 PPTX 和验证回执移至归档位置；最终校验器不会覆盖现有输出。
- 重设计版图片资产保存在 `assets/`，完整生成提示词见 `assets/prompts.md`；两张图片均不含文本和数据。

本稿的数字均为指定提交与环境上的实测记录，并非最终提交的自动验收：公开代码提交 `31567a61` 上 Linux 四组 4/4、230.19 秒，加入 Unix 换行约束后的干净检出 `6c4dbc8a` 上再次 4/4、230.47 秒，两轮之后均核对 Docker Doctor 9/9；当前双公开仓库 `main` 为仅增加验证文档的 `8cd4a821`，已于 2026-09-26 分别匿名检出。官方原版差分 7/7、HTTP LLT 夹具两版各 16/16 对应此前记录。完整 Maple HLT/LLT 和当前 Windows 全量构建仍未完成。第 7 页是**拟录制**的视频路线，不是已完成的视频。

提交前仍需按照 `../docs/submission-checklist.md` 复核最终提交号、平台要求、仓库可访问性，并实际录制主视频和无剪切验证视频。

## 视频辅助素材

- `render_doctor_clip.py` 每次重新执行本项目 Docker Doctor，仅在 9 项和 Overall 全部 PASS 后生成 44 秒重放片段；提供本机 `--ffmpeg` 与 `--output` 路径。
- `render_security_clip.py` 从完整通过的 Linux 四组时间戳日志提取安全断言，只有 401/403 阻断、独占命名空间 404/401/403/500 的公共仓请求数均为 0，且整轮 4/4 PASS 时才生成 64 秒片段。
- `typescript_to_cast.py` 将 `script -m classic -T timing.log -O output.log` 的原始字节和时间记录转换为 asciinema v2 `.cast`，便于原样回放终端输出。
- `render_cast_video.py` 将完整 4/4 PASS 的 `.cast` 逐事件、按原始连续时间轴渲染为 MP4；没有跳过或加速等待段，但它依然只是终端输出回放，不是屏幕捕获。
- `render_main_draft.py` 将片头、Docker、安全边界、完整终端回放和结尾合成为约 7 分钟的无旁白审阅草稿；它是供审稿的编辑版，不是已满足参赛要求的最终主视频。

这些工具生成的是清楚标注的**实测输出重放**，不是实际屏幕的连续录像。素材保留在工作区外层 `test-runs/video/`，未入 Git；主视频与无剪切验证视频仍须完成，并核对画面、字幕和隐私信息。
当前审阅草稿为外层 `test-runs/video/main-review-draft-2026-09-25.mp4`（7:00.42，1280×720，无音轨）。

## 官方统一作品模板

官方模板来自 [cj-codelabs/docs](https://atomgit.com/cj-codelabs/docs)，下载件 SHA-256 为
`e680d2b9e5a2fdde08c93ae786de2cadc1b67e2f6f77e5278f304f41c14effc1`。
`official-form-content.md` 保留十个部分的可审阅技术底稿；`CjRepoMesh-official-form-draft-2026-09-26.docx`
已把这些内容回填到官方模板，并用本机 Microsoft Word 完成 5 页逐页视觉核验。队伍身份、联系信息、
正式视频链接及本人签字仍须补齐；参赛者审阅签字后的 PDF、赛事邮箱确认和发送回执尚未取得。
