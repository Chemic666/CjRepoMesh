#!/usr/bin/env python3
"""Assemble a silent seven-minute review draft from clearly labelled proof clips.

The result is an editorial draft, not the required narrated main video or a
physical uncut screen recording. Source clips remain separate for auditing.
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess

from PIL import Image, ImageDraw

from render_doctor_clip import AMBER, BG, MUTED, PANEL, TEAL, WHITE, font


WIDTH, HEIGHT, FPS = 1280, 720, 12


def title_frame(t: float, duration: int, *, outro: bool) -> bytes:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((45, 38, 1235, 682), 28, fill=PANEL)
    draw.rectangle((45, 38, 56, 682), fill=TEAL)
    draw.text((89, 76), "CjRepoMesh  /  仓颉中心仓多仓配置与私有化", font=font(32, bold=True), fill=WHITE)
    draw.text((91, 136), "官方技术课题 #6 · 自动编排的无旁白审阅草稿", font=font(20), fill=MUTED)
    draw.line((90, 187, 1190, 187), fill="#2D4057", width=2)

    if outro:
        if t < 14:
            heading = "已验证 / 仍需如实标注"
            lines = (
                "Linux 四组核心回归 4/4 PASS；Docker Doctor 9/9 PASS。",
                "独占命名空间与认证失败均未向公共仓回退。",
                "Maple 仅选定本地子集通过，完整 HLT/LLT 尚未运行。",
            )
        else:
            heading = "提交前最后两件事"
            lines = (
                "补录真实屏幕的完整无剪切验证过程；审阅并配制正式旁白。",
                "确认公开仓库、视频链接与比赛平台材料要求。",
                "不以关闭 Windows 安全策略换取当前原生复测。",
            )
    elif t < 12:
        heading = "一个原生解析层，连接多仓与私有化闭环"
        lines = (
            "配置多个仓库；聚合允许的候选版本。",
            "原 cjpm 求解器决定版本；同版本才按仓优先级选来源。",
            "Hosted · Proxy · Mirror · Sync 服务企业私有仓。",
        )
    elif t < 24:
        heading = "解析关系"
        lines = (
            "多仓配置  →  路由与命名空间边界  →  原 cjpm 求解器",
            "最终版本  →  来源与 SHA-256 审计  →  私有仓闭环",
            "401 / 403 与独占缺包，不允许降级到公共仓。",
        )
    else:
        heading = "接下来的证据顺序"
        lines = (
            "01  Docker 一键部署状态与 9 项安全诊断",
            "02  认证屏障与公共仓请求数为 0",
            "03  Linux 四组完整终端时间轴回放",
        )
    draw.text((90, 233), heading, font=font(37, bold=True), fill=WHITE)
    for index, line in enumerate(lines):
        draw.text((95, 333 + 70 * index), line, font=font(24), fill=TEAL if index == 0 else MUTED)
    draw.line((90, 615, 1190, 615), fill="#2D4057", width=2)
    draw.text((90, 633), "无旁白草稿 · 证据片段均标注为重放；不可冒充真实屏幕录制", font=font(18), fill=AMBER)
    draw.rounded_rectangle((90, 604, 90 + int(1100 * t / duration), 608), 2, fill=TEAL)
    return canvas.tobytes()


def render_card(ffmpeg: pathlib.Path, output: pathlib.Path, seconds: int, *, outro: bool) -> None:
    command = [
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium",
        "-crf", "19", "-pix_fmt", "yuv420p", str(output),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdin is not None
        for number in range(seconds * FPS):
            process.stdin.write(title_frame(number / FPS, seconds, outro=outro))
        process.stdin.close()
        assert process.stderr is not None
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        if process.wait() != 0:
            raise RuntimeError(f"ffmpeg card failed: {stderr}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doctor", type=pathlib.Path, required=True)
    parser.add_argument("--security", type=pathlib.Path, required=True)
    parser.add_argument("--core", type=pathlib.Path, required=True)
    parser.add_argument("--ffmpeg", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    for path in (args.doctor, args.security, args.core, args.ffmpeg):
        if not path.is_file():
            parser.error(f"Required input is missing: {path}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    intro = args.output.with_name(args.output.stem + "-intro.mp4")
    outro = args.output.with_name(args.output.stem + "-outro.mp4")
    render_card(args.ffmpeg, intro, 35, outro=False)
    render_card(args.ffmpeg, outro, 33, outro=True)
    inputs = (intro, args.doctor, args.security, args.core, outro)
    filter_parts = [
        f"[{index}:v]fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[v{index}]"
        for index in range(len(inputs))
    ]
    filter_parts.append("".join(f"[v{index}]" for index in range(len(inputs))) + "concat=n=5:v=1:a=0[outv]")
    command = [str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-y"]
    for path in inputs:
        command.extend(("-i", str(path)))
    command.extend((
        "-filter_complex", ";".join(filter_parts), "-map", "[outv]", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(args.output),
    ))
    subprocess.run(command, check=True)
    print(f"Wrote silent review draft to {args.output}")


if __name__ == "__main__":
    main()
