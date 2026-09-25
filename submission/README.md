# CjRepoMesh 答辩材料

- `CjRepoMesh-technical-defense-redesign-2026-09-23.pptx`：推荐预览的重设计版，8 页可编辑文字，封面和安全案例使用概念插画。插画仅用于视觉表达，不是部署截图或测试证据。
- `CjRepoMesh-technical-defense-2026-09-23.pptx`：8 页可编辑技术答辩稿，按约 7 分钟讲述设计。每页的演讲者备注列出证据文档、讲述重点与建议时间。
- 源文件：`../tools/build-technical-defense-redesign.mjs` 和 `../tools/build-technical-defense.mjs`。它们使用随附的演示文稿运行时制作，不下载项目依赖。重新生成前须将同名 PPTX 和验证回执移至归档位置；最终校验器不会覆盖现有输出。
- 重设计版图片资产保存在 `assets/`，完整生成提示词见 `assets/prompts.md`；两张图片均不含文本和数据。

本稿的数字均为指定提交与环境上的实测记录，并非最终提交的自动验收：Linux 4/4 和 Docker 9/9 最近一次复核对应 `0f0e076`；官方原版差分 7/7、HTTP LLT 夹具两版各 16/16 对应此前记录。完整 Maple HLT/LLT 和当前 Windows 全量构建仍未完成。第 7 页是**拟录制**的视频路线，不是已完成的视频。

提交前仍需按照 `../docs/submission-checklist.md` 复核最终提交号、平台要求、仓库可访问性，并实际录制主视频和无剪切验证视频。

## 视频辅助素材

- `render_doctor_clip.py` 每次重新执行本项目 Docker Doctor，仅在 9 项和 Overall 全部 PASS 后生成 44 秒重放片段；提供本机 `--ffmpeg` 与 `--output` 路径。
- `render_security_clip.py` 从完整通过的 Linux 四组时间戳日志提取安全断言，只有 401/403 阻断、独占命名空间 404/401/403/500 的公共仓请求数均为 0，且整轮 4/4 PASS 时才生成 64 秒片段。
- `typescript_to_cast.py` 将 `script -m classic -T timing.log -O output.log` 的原始字节和时间记录转换为 asciinema v2 `.cast`，便于原样回放终端输出。

这些工具生成的是清楚标注的**实测输出重放**，不是实际屏幕的连续录像。素材保留在工作区外层 `test-runs/video/`，未入 Git；主视频与无剪切验证视频仍须完成，并核对画面、字幕和隐私信息。
