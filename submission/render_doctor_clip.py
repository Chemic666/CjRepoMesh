#!/usr/bin/env python3
"""Render a clearly labelled replay of a fresh Docker Doctor result.

This is a presentation clip, not a continuous screen recording. The Doctor
command is executed on each invocation and must pass before a clip is made.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import subprocess

from PIL import Image, ImageDraw, ImageFont


ROOT = pathlib.Path(__file__).resolve().parents[1]
WIDTH, HEIGHT, FPS, SECONDS = 1280, 720, 12, 44
FONT_PATH = pathlib.Path("C:/Windows/Fonts/msyh.ttc")
BG = "#0B1423"
PANEL = "#14243A"
WHITE = "#F3F7FB"
MUTED = "#9FB2C8"
TEAL = "#54E0C5"
AMBER = "#FFC66D"


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    font_path = pathlib.Path("C:/Windows/Fonts/msyhbd.ttc") if bold else FONT_PATH
    if not font_path.exists():
        raise RuntimeError(f"Required CJK font is missing: {font_path}")
    return ImageFont.truetype(str(font_path), size)


def doctor_result() -> list[str]:
    run = subprocess.run(
        ["powershell.exe", "-NoProfile", "-File", str(ROOT / "deployment/docker/doctor.ps1")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=90,
    )
    if run.returncode != 0:
        raise RuntimeError(f"Docker Doctor failed; clip not produced:\n{run.stdout}\n{run.stderr}")
    lines = [line.strip() for line in run.stdout.splitlines() if line.strip()]
    expected = (
        "Container running", "Docker healthy", "Non-root user", "Read-only root",
        "Capabilities dropped", "No new privileges", "Localhost binding",
        "Persistent volume", "Registry API", "Overall",
    )
    if len(lines) != len(expected):
        raise RuntimeError(f"Unexpected Doctor output: {lines!r}")
    for line, label in zip(lines, expected):
        if not re.fullmatch(rf"{re.escape(label)}\s+PASS", line):
            raise RuntimeError(f"Doctor check did not pass: {line!r}")
    return lines


def draw_frame(t: float, lines: list[str], commit: str, date: str) -> bytes:
    frame = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(frame)
    draw.rounded_rectangle((45, 38, 1235, 682), 28, fill=PANEL)
    draw.rectangle((45, 38, 56, 682), fill=TEAL)
    draw.text((88, 73), "CjRepoMesh  /  本机部署核验", font=font(37, bold=True), fill=WHITE)
    draw.text((90, 136), f"{date}  ·  代码提交 {commit}", font=font(19), fill=MUTED)
    draw.line((90, 180, 1190, 180), fill="#2D4057", width=2)

    if t < 8:
        draw.text((90, 246), "私有仓服务已启动", font=font(50, bold=True), fill=WHITE)
        draw.text((92, 326), "现在运行只读诊断，核对容器、隔离与 API。", font=font(27), fill=MUTED)
        draw.rounded_rectangle((90, 420, 1190, 485), 12, fill="#08111F")
        draw.text((111, 433), ">  .\\deployment\\docker\\doctor.ps1", font=font(27), fill=TEAL)
    elif t < 35:
        draw.text((90, 210), "Docker Doctor  /  实测输出", font=font(31, bold=True), fill=WHITE)
        draw.rounded_rectangle((90, 267, 1190, 584), 14, fill="#08111F")
        visible = min(10, max(0, int((t - 8) / 2.5) + 1))
        for i, line in enumerate(lines[:visible]):
            label = line.rsplit("PASS", 1)[0].strip()
            col = i // 5
            row = i % 5
            x = 116 + col * 536
            y = 293 + row * 55
            draw.text((x, y), label, font=font(22), fill=WHITE)
            draw.text((x + 410, y), "PASS", font=font(22, bold=True), fill=TEAL)
    else:
        draw.text((90, 221), "9 项检查 + Overall 通过", font=font(46, bold=True), fill=WHITE)
        draw.text((92, 322), "非 root · 只读根目录 · 最小权限 · 本机端口", font=font(27), fill=TEAL)
        draw.text((92, 383), "持久化卷与 Registry API 同时通过。", font=font(27), fill=MUTED)
        draw.text((92, 460), "下一段：多仓解析与安全边界", font=font(26, bold=True), fill=AMBER)

    draw.line((90, 615, 1190, 615), fill="#2D4057", width=2)
    draw.text((90, 631), "实测输出重放 / 非连续屏幕录像；原始验证需另行保留", font=font(19), fill=MUTED)
    draw.rounded_rectangle((90, 604, 90 + int(1100 * t / SECONDS), 608), 2, fill=TEAL)
    return frame.tobytes()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if not args.ffmpeg.is_file():
        raise SystemExit(f"ffmpeg not found: {args.ffmpeg}")
    lines = doctor_result()
    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    timestamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M CST")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium",
        "-crf", "19", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(args.output),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdin is not None
        for frame_number in range(FPS * SECONDS):
            process.stdin.write(draw_frame(frame_number / FPS, lines, commit, timestamp))
        process.stdin.close()
        assert process.stderr is not None
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        if process.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {stderr}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    print(f"Doctor 9/9 PASS; rendered {SECONDS}s replay to {args.output}")


if __name__ == "__main__":
    main()
