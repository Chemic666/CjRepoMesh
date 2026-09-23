import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = process.env.CJRM_WORKSPACE;
const SKILL_DIR = process.env.SKILL_DIR;
const RUNTIME_PYTHON = process.env.RUNTIME_PYTHON;
if (![workspaceDir, SKILL_DIR, RUNTIME_PYTHON].every((value) => value && path.isAbsolute(value))) {
  throw new Error("Set absolute CJRM_WORKSPACE, SKILL_DIR and RUNTIME_PYTHON paths");
}

const buildDir = path.join(workspaceDir, ".codex-slides-redesign");
const finalPath = path.join(workspaceDir, "submission", "CjRepoMesh-technical-defense-redesign-2026-09-23.pptx");
const coverImage = new Uint8Array(await fs.readFile(path.join(workspaceDir, "submission", "assets", "cover-registry-mesh.png")));
const securityImage = new Uint8Array(await fs.readFile(path.join(workspaceDir, "submission", "assets", "security-boundary.png")));
const { resolvePresentationFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools", "artifact_tool_utils.mjs")).href,
);
const cn = resolvePresentationFont({ fontFamily: "Microsoft YaHei" });
const en = resolvePresentationFont({ fontFamily: "Bahnschrift" });
const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });

const C = {
  paper: "#F4F2EC", white: "#FFFFFF", ink: "#132A3B", dark: "#0C1724",
  cyan: "#83E2D6", teal: "#158F8B", muted: "#536773", line: "#BECBCD",
  fog: "#D8E1DF", silver: "#B8C9D4",
};

function textBox(slide, content, position, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox", position, fill: "none", line: { fill: "none", width: 0 },
  });
  shape.text = content;
  shape.text.style = {
    typeface: options.font ?? cn,
    fontSize: options.size ?? 26,
    bold: options.bold ?? false,
    color: options.color ?? C.ink,
    alignment: options.align ?? "left",
    verticalAlignment: options.vertical ?? "middle",
    autoFit: "none", wrap: "square",
    insets: { left: 0, right: 0, top: 0, bottom: 0 },
  };
  return shape;
}
function line(slide, x, y, w, fill = C.line, h = 2) {
  return slide.shapes.add({
    geometry: "rect", position: { left: x, top: y, width: w, height: h },
    fill, line: { fill: "none", width: 0 },
  });
}
function image(slide, blob, alt) {
  slide.images.add({ blob, contentType: "image/png", alt, fit: "cover",
    position: { left: 0, top: 0, width: 1280, height: 720 } });
}
function lightSlide(title, page, notes) {
  const slide = deck.slides.add();
  slide.background.fill = C.paper;
  textBox(slide, title, { left: 72, top: 57, width: 1040, height: 70 },
    { size: 43, bold: true });
  line(slide, 72, 148, 1136, C.line, 1);
  textBox(slide, String(page).padStart(2, "0"),
    { left: 1144, top: 649, width: 64, height: 33 },
    { size: 19, font: en, color: C.muted, align: "right" });
  slide.speakerNotes.textFrame.setText(notes);
  return slide;
}

// 1 — cover; artwork is conceptual, not a record of deployed infrastructure.
{
  const slide = deck.slides.add();
  slide.background.fill = C.dark;
  image(slide, coverImage, "Conceptual artwork of multiple package registry servers linked to a private hub");
  textBox(slide, "CjRepoMesh", { left: 72, top: 151, width: 628, height: 105 },
    { size: 76, bold: true, color: C.white, font: en });
  textBox(slide, "仓颉中心仓多仓配置\n与私有化体系建设", { left: 74, top: 273, width: 625, height: 156 },
    { size: 40, bold: true, color: C.white });
  line(slide, 74, 469, 84, C.cyan, 5);
  textBox(slide, "官方技术课题 #6", { left: 74, top: 492, width: 430, height: 42 },
    { size: 24, color: C.silver });
  slide.speakerNotes.textFrame.setText(
    "来源：docs/competition-requirements-matrix.md。封面图片为概念插画，非真实部署现场。\n建议讲述 30 秒：介绍课题、多仓解析层和企业私仓闭环。",
  );
}

// 2 — one invariant, with the three implementation responsibilities nearby.
{
  const slide = lightSlide("目标约束", 2,
    "来源：docs/competition-requirements-matrix.md；docs/architecture.md。\n建议讲述 45 秒：仓库可增加，版本求解规则须保持；私有仓须能部署并流转制品。");
  textBox(slide, "仓库可以变多，\n版本规则保持不变。",
    { left: 72, top: 199, width: 735, height: 188 },
    { size: 49, bold: true, color: C.ink });
  line(slide, 846, 204, 2, C.teal, 320);
  const rows = [
    ["路由", "汇聚候选版本与来源"],
    ["求解", "沿用 cjpm 原有规则"],
    ["私仓", "部署、发布与包流转"],
  ];
  rows.forEach(([label, body], i) => {
    const y = 206 + i * 111;
    textBox(slide, label, { left: 884, top: y, width: 290, height: 43 },
      { size: 27, bold: true, color: C.teal });
    textBox(slide, body, { left: 884, top: y + 42, width: 310, height: 45 },
      { size: 21, color: C.muted });
  });
  textBox(slide, "同一版本的来源，由仓库优先级决定。",
    { left: 72, top: 544, width: 755, height: 64 },
    { size: 28, color: C.muted });
}

// 3 — the key architectural distinction is editable text, not a raster diagram.
{
  const slide = lightSlide("选版本与选来源分层", 3,
    "来源：docs/architecture.md；docs/multirepo-implementation.md；docs/official-compatibility-report.md。\n建议讲述 55 秒：Router 汇聚候选及来源，原 cjpm 求解器保留版本决策；来源审计另存 cjpm-provenance.json，不冒充 lockfile。");
  textBox(slide, "01", { left: 72, top: 201, width: 230, height: 113 },
    { size: 99, bold: true, color: C.teal, font: en });
  textBox(slide, "Repository Router", { left: 72, top: 323, width: 525, height: 58 },
    { size: 34, bold: true, font: en });
  textBox(slide, "候选版本  /  仓库来源  /  安全回退",
    { left: 72, top: 389, width: 535, height: 66 }, { size: 25, color: C.muted });
  line(slide, 642, 205, 2, C.line, 315);
  textBox(slide, "02", { left: 686, top: 201, width: 230, height: 113 },
    { size: 99, bold: true, color: C.teal, font: en });
  textBox(slide, "原 cjpm 求解器", { left: 686, top: 323, width: 515, height: 58 },
    { size: 34, bold: true });
  textBox(slide, "依赖约束  /  锁定规则  /  最终版本",
    { left: 686, top: 389, width: 515, height: 66 }, { size: 25, color: C.muted });
  line(slide, 72, 556, 1136, C.line, 1);
  textBox(slide, "来源与 SHA-256 另存 cjpm-provenance.json",
    { left: 72, top: 571, width: 1136, height: 56 },
    { size: 27, bold: true, color: C.ink });
}

// 4 — deliverables as an editorial list, not UI cards.
{
  const slide = lightSlide("四项交付", 4,
    "来源：docs/competition-requirements-matrix.md；docs/architecture.md；docs/docker-verification.md；docs/linux-verification.md。\n建议讲述 60 秒：Mirror 是显式清单镜像，不是完整复制上游仓；Sync 是仓间同步。");
  const rows = [
    ["01", "多仓配置", "优先级、旧配置兼容与来源解释"],
    ["02", "依赖解析", "跨仓候选、同版选源、[replace] 与认证屏障"],
    ["03", "私有部署", "Windows / Docker 一键流程与持久化诊断"],
    ["04", "代理与同步", "Proxy 缓存、清单 Mirror 与仓间 Sync"],
  ];
  rows.forEach(([number, label, body], i) => {
    const y = 192 + i * 111;
    textBox(slide, number, { left: 72, top: y, width: 113, height: 65 },
      { size: 48, bold: true, font: en, color: C.teal });
    textBox(slide, label, { left: 215, top: y + 3, width: 265, height: 58 },
      { size: 30, bold: true });
    textBox(slide, body, { left: 522, top: y + 4, width: 665, height: 58 },
      { size: 23, color: C.muted });
    if (i < rows.length - 1) line(slide, 72, y + 84, 1136, C.line, 1);
  });
}

// 5 — security artwork only supports the story; all proof remains editable.
{
  const slide = deck.slides.add();
  slide.background.fill = C.dark;
  image(slide, securityImage, "Conceptual private registry security boundary illustration");
  textBox(slide, "独占命名空间", { left: 72, top: 55, width: 625, height: 76 },
    { size: 43, bold: true, color: C.white });
  line(slide, 72, 154, 80, C.cyan, 4);
  textBox(slide, "私仓 1.0.0", { left: 72, top: 212, width: 575, height: 68 },
    { size: 42, bold: true, color: C.white });
  textBox(slide, "公共同名包 9.0.0", { left: 72, top: 287, width: 575, height: 56 },
    { size: 30, color: C.silver });
  textBox(slide, "0", { left: 72, top: 373, width: 170, height: 122 },
    { size: 110, bold: true, color: C.cyan, font: en });
  textBox(slide, "次公共仓请求", { left: 205, top: 410, width: 383, height: 69 },
    { size: 32, bold: true, color: C.white });
  textBox(slide, "404 / 401 / 403 / 500 故障注入均成立",
    { left: 72, top: 538, width: 680, height: 56 },
    { size: 24, color: C.silver });
  slide.speakerNotes.textFrame.setText(
    "来源：docs/verification-report.md，独占命名空间故障矩阵与篡改制品专项。图片为概念插画，不是系统截图。\n建议讲述 60 秒：company::* 独占路由下，私仓 1.0.0 与公共 9.0.0 同名；404/401/403/500 四类故障中公共仓请求数均为 0。制品 SHA 不符也必须失败，不改从低优先级仓下载。",
  );
}

// 6 — one hero metric and three supporting measurements.
{
  const slide = lightSlide("实测证据", 6,
    "来源：docs/verification-report.md；docs/official-compatibility-report.md；docs/docker-verification.md。\n建议讲述 65 秒：0f0e076 上 Linux 四组全量 4/4，用时 710.19 秒；同一提交 Docker 诊断 9/9。官方原版与增强版单仓差分 7/7；官方 HTTP LLT 夹具在两版各 16/16。完整 Maple HLT/LLT 未跑。");
  textBox(slide, "4/4", { left: 72, top: 193, width: 520, height: 155 },
    { size: 142, bold: true, font: en, color: C.teal });
  textBox(slide, "Linux 共享核心全量回归", { left: 79, top: 348, width: 550, height: 62 },
    { size: 29, bold: true });
  textBox(slide, "提交 0f0e076 · 710.19 秒", { left: 80, top: 420, width: 505, height: 46 },
    { size: 22, color: C.muted });
  line(slide, 642, 199, 2, C.line, 325);
  const metrics = [
    ["9/9", "Docker 部署诊断"],
    ["7/7", "官方原版 / 增强版差分"],
    ["16/16", "HTTP LLT 夹具，两版各通过"],
  ];
  metrics.forEach(([value, label], i) => {
    const y = 206 + i * 107;
    textBox(slide, value, { left: 691, top: y, width: 235, height: 70 },
      { size: 57, bold: true, font: en, color: C.ink });
    textBox(slide, label, { left: 929, top: y + 9, width: 268, height: 59 },
      { size: 21, color: C.muted });
    if (i < 2) line(slide, 691, y + 84, 506, C.line, 1);
  });
}

// 7 — the storyboard stays explicitly unrecorded.
{
  const slide = lightSlide("拟录制的 7 分钟演示", 7,
    "来源：docs/demo-runbook.md；docs/docker-verification.md。\n建议讲述 70 秒：这是计划录制的主视频路线，不代表视频已经完成。完整无剪切验证也仍待录制。Proxy 性能数据来自本地 HTTP，不外推公网。");
  const scenes = [
    ["00:00–01:20", "启动", "Compose 部署、健康检查与 Doctor 9/9"],
    ["01:20–04:05", "解析", "跨仓构建、独占命名空间、Explain 与来源审计"],
    ["04:05–07:00", "流转", "Proxy 离线命中、清单 Mirror、Sync 后构建"],
  ];
  scenes.forEach(([time, label, body], i) => {
    const y = 194 + i * 145;
    textBox(slide, time, { left: 72, top: y, width: 232, height: 52 },
      { size: 24, font: en, color: C.teal });
    textBox(slide, label, { left: 338, top: y - 1, width: 185, height: 56 },
      { size: 36, bold: true });
    textBox(slide, body, { left: 546, top: y, width: 648, height: 76 },
      { size: 24, color: C.muted });
    if (i < scenes.length - 1) line(slide, 72, y + 104, 1136, C.line, 1);
  });
}

// 8 — finish with a truthful boundary, not a success claim.
{
  const slide = deck.slides.add();
  slide.background.fill = C.dark;
  textBox(slide, "完成度与边界", { left: 72, top: 59, width: 1080, height: 74 },
    { size: 44, bold: true, color: C.white });
  line(slide, 72, 157, 1136, "#456070", 1);
  textBox(slide, "已证实", { left: 72, top: 218, width: 485, height: 62 },
    { size: 36, bold: true, color: C.cyan });
  textBox(slide, "多仓解析与私仓闭环\nLinux 4/4 · Docker 9/9",
    { left: 72, top: 298, width: 495, height: 130 },
    { size: 29, color: C.white });
  line(slide, 628, 217, 2, "#456070", 265);
  textBox(slide, "尚待完成", { left: 685, top: 218, width: 493, height: 62 },
    { size: 36, bold: true, color: C.cyan });
  textBox(slide, "当前 Windows 构建环境复测\n完整 Maple HLT/LLT 与视频",
    { left: 685, top: 298, width: 515, height: 130 },
    { size: 29, color: C.white });
  line(slide, 72, 551, 1136, "#456070", 1);
  textBox(slide, "提交前按最终提交号复核，并录制主视频与无剪切验证。",
    { left: 72, top: 580, width: 1090, height: 65 },
    { size: 26, color: C.silver });
  slide.speakerNotes.textFrame.setText(
    "来源：docs/submission-checklist.md；docs/verification-report.md；docs/award-readiness.md。\n建议讲述 55 秒：Windows cjc 受系统 Application Control 拦截，不绕过安全策略；历史 Windows 5/5 不冒充本次通过。完整 Maple HLT/LLT 未跑，视频未录。",
  );
}

await fs.mkdir(buildDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });
const candidatePath = path.join(buildDir, "candidate.pptx");
await (await PresentationFile.exportPptx(deck)).save(candidatePath);
const result = await finalizePresentation({
  explicitTotalSlideCount: 8,
  requiredNativeTableOwnerSlides: [], requiredNativeChartOwnerSlides: [],
  workspaceDir, candidatePath, finalPath,
  pythonExecutable: RUNTIME_PYTHON,
  integrityValidatorPath: path.join(SKILL_DIR, "container_tools", "inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL_DIR, "container_tools", "inspect_presentation_layout_geometry.py"),
  layoutArgs: ["--expected-slide-size-emu", "12192000,6858000", "--validate-heading-fit"],
  fontPolicy: { basis: "design", families: [cn, en] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(buildDir, "validation.json"),
});
const checkedDeck = await PresentationFile.importPptx(await FileBlob.load(finalPath));
for (let i = 0; i < checkedDeck.slides.items.length; i++) {
  const preview = await checkedDeck.export({ slide: checkedDeck.slides.items[i], format: "png", scale: 1 });
  await fs.writeFile(path.join(buildDir, `slide-${i + 1}.png`),
    new Uint8Array(await preview.arrayBuffer()));
}
console.log(JSON.stringify({ finalPath, slideCount: checkedDeck.slides.items.length, sha256: result.finalSha256 }));
