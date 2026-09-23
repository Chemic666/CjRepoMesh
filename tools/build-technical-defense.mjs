import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = path.resolve(process.env.CJRM_WORKSPACE ?? "");
const SKILL_DIR = path.resolve(process.env.SKILL_DIR ?? "");
const RUNTIME_PYTHON = process.env.RUNTIME_PYTHON;
const TMP_DIR = path.join(workspaceDir, ".codex-slides");
const FINAL_PPTX = path.join(workspaceDir, "submission", "CjRepoMesh-technical-defense-2026-09-23.pptx");
if (!path.isAbsolute(workspaceDir) || !path.isAbsolute(SKILL_DIR) || !RUNTIME_PYTHON) {
  throw new Error("Set CJRM_WORKSPACE, SKILL_DIR and RUNTIME_PYTHON");
}
const { resolvePresentationFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools", "artifact_tool_utils.mjs")).href
);
const font = resolvePresentationFont({ fontFamily: "Microsoft YaHei" });
const ppt = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const C = { bg: "#101E30", white: "#F5F7F6", accent: "#62D6C7", muted: "#A7B8C8", line: "#39556B" };

function txt(slide, value, x, y, w, h, size, color = C.white, bold = false) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left: x, top: y, width: w, height: h },
    fill: "none",
    line: { fill: "none", width: 0 },
  });
  shape.text = value;
  shape.text.style = {
    typeface: font, fontSize: size, bold, color,
    alignment: "left", verticalAlignment: "middle", autoFit: "none",
    wrap: "square", insets: { left: 0, right: 0, top: 0, bottom: 0 },
  };
  return shape;
}
function rule(slide, y, x = 72, w = 1136) {
  slide.shapes.add({ geometry: "rect", position: { left: x, top: y, width: w, height: 2 }, fill: C.line, line: { fill: "none", width: 0 } });
}
function base(title, number, note) {
  const s = ppt.slides.add();
  s.background.fill = C.bg;
  txt(s, title, 72, 56, 1136, 70, 42, C.white, true);
  rule(s, 145);
  txt(s, `CjRepoMesh  ·  官方技术课题 #6`, 72, 665, 780, 28, 16, C.muted);
  txt(s, String(number).padStart(2, "0"), 1152, 665, 56, 28, 16, C.muted);
  s.speakerNotes.textFrame.setText(note);
  return s;
}

// 1 — short, legible cover.
{
  const s = ppt.slides.add();
  s.background.fill = C.bg;
  txt(s, "CjRepoMesh", 72, 128, 1120, 110, 72, C.white, true);
  txt(s, "仓颉中心仓多仓配置与私有化体系建设", 72, 266, 1120, 72, 39, C.accent, true);
  rule(s, 383, 72, 700);
  txt(s, "技术答辩  /  官方课题 #6", 72, 422, 850, 45, 26, C.white);
  txt(s, "验证口径截至 2026-09-23", 72, 614, 850, 35, 20, C.muted);
  s.speakerNotes.textFrame.setText("定位与课题名称见 docs/competition-requirements-matrix.md；该材料是可编辑答辩稿，不代表已完成视频录制。\n讲述建议：30 秒。先说明多仓、原有求解规则、私有化部署三项主线。");
}
// 2 — problem and invariant.
{
  const s = base("问题：仓库变多，版本规则不能变", 2,
    "来源：docs/competition-requirements-matrix.md；docs/architecture.md。\n讲述建议：45 秒。强调官方课题要求多仓配置和私有化，且不能破坏原有版本选择规则。");
  txt(s, "01", 72, 205, 80, 50, 28, C.accent, true);
  txt(s, "公共源、企业私仓、缓存源需要同时参与候选", 164, 204, 1015, 56, 28);
  rule(s, 290);
  txt(s, "02", 72, 323, 80, 50, 28, C.accent, true);
  txt(s, "版本仍交给 cjpm 原求解器，来源按优先级确定", 164, 322, 1015, 56, 28);
  rule(s, 408);
  txt(s, "03", 72, 441, 80, 50, 28, C.accent, true);
  txt(s, "私有中心仓要能部署、发布、代理与同步", 164, 440, 1015, 56, 28);
}
// 3 — architecture, no decorative diagram.
{
  const s = base("核心设计：选版本与选来源分层", 3,
    "来源：docs/architecture.md；docs/multirepo-implementation.md；docs/official-compatibility-report.md。\n讲述建议：55 秒。Repository Router 汇聚候选及来源，原 cjpm 求解器做版本决策。锁定版本规则及旧 repository.home 行为以官方原版差分验证。");
  txt(s, "Repository Router", 72, 211, 500, 52, 33, C.accent, true);
  txt(s, "按仓库配置收集候选版本\n保留来源、优先级与回退边界", 72, 287, 500, 140, 27);
  txt(s, "原 cjpm 求解器", 690, 211, 500, 52, 33, C.accent, true);
  txt(s, "沿用已有依赖约束与锁定规则\n选择最终版本，再确定制品来源", 690, 287, 500, 140, 27);
  rule(s, 484);
  txt(s, "不改写旧规则；新增独立来源审计 cjpm-provenance.json", 72, 522, 1136, 92, 30, C.white, true);
}
// 4 — four deliverables.
{
  const s = base("四项交付，形成闭环", 4,
    "来源：docs/competition-requirements-matrix.md；docs/architecture.md；docs/docker-verification.md；docs/linux-verification.md。\n讲述建议：60 秒。Mirror 指显式清单镜像，非完整上游仓复制；Sync 为带令牌的仓间同步。");
  const rows = [
    ["多仓配置", "优先级、旧单仓配置兼容、来源解释"],
    ["依赖解析", "跨仓候选、同版选源、[replace] 与认证屏障"],
    ["私有部署", "Windows / Docker 一键流程与持久化诊断"],
    ["代理与同步", "Proxy 缓存、显式清单 Mirror、仓间 Sync"],
  ];
  rows.forEach(([head, body], i) => {
    const y = 195 + i * 106;
    txt(s, head, 72, y, 230, 70, 29, C.accent, true);
    txt(s, body, 320, y, 865, 70, 26);
    if (i < rows.length - 1) rule(s, y + 83);
  });
}
// 5 — security story.
{
  const s = base("安全边界：不让公共高版本“抢包”", 5,
    "来源：docs/verification-report.md（独占命名空间故障矩阵、篡改制品专项）；docs/multirepo-implementation.md。\n讲述建议：60 秒。私仓 company::* 为独占路由；高版本公共同名包不能参与。404/401/403/500 注入时公共仓请求数均为 0。401/403 也不得认证绕过；选中制品 SHA 不符时失败，不回退低优先级伪装成功。");
  txt(s, "私仓 1.0.0", 72, 214, 420, 65, 38, C.white, true);
  txt(s, "公共仓 9.0.0", 700, 214, 470, 65, 38, C.muted, true);
  rule(s, 320);
  txt(s, "company::* 独占路由", 72, 355, 1136, 64, 37, C.accent, true);
  txt(s, "404 / 401 / 403 / 500 故障矩阵：公共仓请求数 = 0", 72, 456, 1136, 65, 29);
  txt(s, "选中制品损坏则拒绝；修复后同一缓存可恢复构建", 72, 552, 1136, 62, 27, C.muted);
}
// 6 — measured evidence.
{
  const s = base("证据：功能与兼容性均有实测", 6,
    "来源：docs/verification-report.md；docs/official-compatibility-report.md；docs/docker-verification.md。\n讲述建议：65 秒。Linux 4/4 为提交 0f0e076 上完整四组回归，710.19 秒；该轮覆盖 662935d 后新增的篡改制品场景。Docker 9/9 在同一提交再次通过；c602c12 修复后此前还有两轮 9/9。官方差分 7/7；官方 HTTP LLT 夹具在原版与增强版各 16/16。不要说完整 Maple HLT/LLT 已通过。");
  txt(s, "4 / 4", 72, 200, 445, 84, 61, C.accent, true);
  txt(s, "Linux 共享核心全量回归", 72, 294, 480, 49, 25);
  txt(s, "9 / 9", 690, 200, 445, 84, 61, C.accent, true);
  txt(s, "Docker 部署诊断 × 2 轮", 690, 294, 490, 49, 25);
  rule(s, 388);
  txt(s, "7 / 7", 72, 425, 445, 84, 61, C.accent, true);
  txt(s, "官方原版 / 增强版单仓差分", 72, 519, 535, 49, 25);
  txt(s, "16 / 16", 690, 425, 445, 84, 61, C.accent, true);
  txt(s, "官方 HTTP LLT 夹具，两版各通过", 690, 519, 510, 49, 25);
}
// 7 — live demo map.
{
  const s = base("拟录制：7 分钟演示路线", 7,
    "来源：docs/demo-runbook.md；docs/docker-verification.md；benchmark/results/proxy-benchmark.md。\n讲述建议：70 秒。此页是拟录制视频的演示顺序，不代表视频已录好。Proxy 基准为本地 HTTP，冷中位 62.76ms/10 次、热中位 33.102ms/50 次，不外推公网性能。现场可只演示 MISS/HIT/断上游仍命中。");
  txt(s, "启动", 72, 205, 230, 46, 30, C.accent, true);
  txt(s, "Compose 一键部署 → Doctor 9/9 → 发布", 72, 260, 1136, 62, 28);
  rule(s, 345);
  txt(s, "解析", 72, 378, 230, 46, 30, C.accent, true);
  txt(s, "跨仓构建 → 独占命名空间 → Explain / Provenance", 72, 432, 1136, 62, 28);
  rule(s, 517);
  txt(s, "流转", 72, 548, 230, 46, 30, C.accent, true);
  txt(s, "Proxy 离线命中 → Mirror 清单 → Sync 后重建", 72, 600, 1136, 42, 27);
}
// 8 — honest finish.
{
  const s = base("完成度与剩余工作", 8,
    "来源：docs/submission-checklist.md；docs/verification-report.md；docs/award-readiness.md。\n讲述建议：55 秒。当前 Windows cjc 被系统 Application Control 阻断，不绕过安全策略；历史 Windows 5/5 不能冒充当前提交结果。完整 Maple HLT/LLT 未运行；视频待录制；提交平台及外部仓库可访问性需要赛前复查。");
  txt(s, "已完成", 72, 200, 230, 49, 30, C.accent, true);
  txt(s, "多仓 + 私仓 + 代理 / 镜像 / 同步；Linux 与 Docker 实测", 72, 259, 1120, 70, 27);
  rule(s, 365);
  txt(s, "仍待验证", 72, 398, 230, 49, 30, C.accent, true);
  txt(s, "当前 Windows 构建受系统拦截；完整 Maple HLT/LLT 未跑", 72, 457, 1120, 70, 27);
  rule(s, 563);
  txt(s, "提交前", 72, 591, 230, 49, 30, C.accent, true);
  txt(s, "录制主视频与无剪切验证；按最终提交号重跑关键链路", 260, 590, 930, 54, 25);
}

await fs.mkdir(TMP_DIR, { recursive: true });
await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });
const candidatePath = path.join(TMP_DIR, "candidate.pptx");
await (await PresentationFile.exportPptx(ppt)).save(candidatePath);
const result = await finalizePresentation({
  explicitTotalSlideCount: 8,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [],
  workspaceDir,
  candidatePath,
  finalPath: FINAL_PPTX,
  pythonExecutable: RUNTIME_PYTHON,
  integrityValidatorPath: path.join(SKILL_DIR, "container_tools", "inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL_DIR, "container_tools", "inspect_presentation_layout_geometry.py"),
  layoutArgs: ["--expected-slide-size-emu", "12192000,6858000", "--validate-heading-fit"],
  fontPolicy: { basis: "design", families: [font] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(TMP_DIR, "validation-final.json"),
});
const checkedPpt = await PresentationFile.importPptx(await FileBlob.load(FINAL_PPTX));
for (let i = 0; i < checkedPpt.slides.items.length; i++) {
  const preview = await checkedPpt.export({ slide: checkedPpt.slides.items[i], format: "png", scale: 1 });
  await fs.writeFile(path.join(TMP_DIR, `slide-${i + 1}.png`), new Uint8Array(await preview.arrayBuffer()));
}
console.log(JSON.stringify({ finalPath: FINAL_PPTX, slideCount: checkedPpt.slides.items.length, sha256: result.finalSha256 }));
