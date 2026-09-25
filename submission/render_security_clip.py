#!/usr/bin/env python3
"""Render an explicitly labelled security-test replay from a passing core run."""

from __future__ import annotations

import argparse
import pathlib
import subprocess

from PIL import Image, ImageDraw

from render_doctor_clip import AMBER, BG, MUTED, PANEL, TEAL, WHITE, font


ROOT = pathlib.Path(__file__).resolve().parents[1]
WIDTH, HEIGHT, FPS, SECONDS = 1280, 720, 12, 64
CHECKS = (
    ("401 认证失败", "lower-priority requests=0", "401 blocks fallback; lower-priority requests=0"),
    ("403 权限拒绝", "lower-priority requests=0", "403 blocks fallback; lower-priority requests=0"),
    ("独占命名空间 · 404", "public requests=0", "exclusive namespace blocks public fallback after 404; public requests=0"),
    ("独占命名空间 · 401", "public requests=0", "exclusive namespace blocks public fallback after 401; public requests=0"),
    ("独占命名空间 · 403", "public requests=0", "exclusive namespace blocks public fallback after 403; public requests=0"),
    ("独占命名空间 · 500", "public requests=0", "exclusive namespace blocks public fallback after 500; public requests=0"),
)


def verify_log(path: pathlib.Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    for _label, _value, assertion in CHECKS:
        if f"PASS {assertion}" not in raw:
            raise ValueError(f"Required test evidence is missing: {assertion}")
    if "=== Multi-repository cjpm: PASS" not in raw or "All 4 core suites passed" not in raw:
        raise ValueError("Full Linux core run did not pass; security clip not produced")
    first = raw.splitlines()[0]
    if not first.startswith("Script started on "):
        raise ValueError("Expected a util-linux script recording")
    return first.removeprefix("Script started on ").split(" ", 1)[0]


def frame_at(t: float, commit: str, recorded_at: str) -> bytes:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((45, 38, 1235, 682), 28, fill=PANEL)
    draw.rectangle((45, 38, 56, 682), fill=TEAL)
    draw.text((88, 73), "CjRepoMesh  /  安全边界实测", font=font(37, bold=True), fill=WHITE)
    draw.text((90, 136), f"录制 {recorded_at}  ·  代码提交 {commit}", font=font(19), fill=MUTED)
    draw.line((90, 180, 1190, 180), fill="#2D4057", width=2)

    if t < 8:
        draw.text((90, 250), "失败不能变成公网回退", font=font(46, bold=True), fill=WHITE)
        draw.text((92, 331), "测试同时验证返回状态与公共仓请求计数。", font=font(27), fill=MUTED)
        draw.text((92, 412), "高版本诱饵 9.0.0 也不能绕过 company::* 独占路由。", font=font(25), fill=AMBER)
    elif t < 53:
        draw.text((90, 208), "断言来自本次 Linux 核心回归", font=font(30, bold=True), fill=WHITE)
        draw.rounded_rectangle((90, 267, 1190, 572), 14, fill="#08111F")
        visible = min(len(CHECKS), max(0, int((t - 8) / 7) + 1))
        for i, (label, value, _assertion) in enumerate(CHECKS[:visible]):
            y = 291 + i * 45
            draw.text((112, y), label, font=font(22), fill=WHITE)
            draw.text((706, y), value, font=font(21, bold=True), fill=TEAL)
    else:
        draw.text((90, 231), "公共仓请求数 = 0", font=font(48, bold=True), fill=TEAL)
        draw.text((92, 322), "404 / 401 / 403 / 500 均未越过独占路由", font=font(26), fill=WHITE)
        draw.text((92, 396), "Linux 四组完整回归：4 / 4 PASS", font=font(30, bold=True), fill=AMBER)

    draw.line((90, 615, 1190, 615), fill="#2D4057", width=2)
    draw.text((90, 631), "测试日志重放 / 非连续屏幕录像；原始验证需另行保留", font=font(19), fill=MUTED)
    draw.rounded_rectangle((90, 604, 90 + int(1100 * t / SECONDS), 608), 2, fill=TEAL)
    return canvas.tobytes()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=pathlib.Path, required=True)
    parser.add_argument("--ffmpeg", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if not args.ffmpeg.is_file():
        parser.error(f"ffmpeg not found: {args.ffmpeg}")
    recorded_at = verify_log(args.log)
    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
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
        for number in range(FPS * SECONDS):
            process.stdin.write(frame_at(number / FPS, commit, recorded_at))
        process.stdin.close()
        assert process.stderr is not None
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        if process.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {stderr}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    print(f"Rendered {SECONDS}s security replay to {args.output}")


if __name__ == "__main__":
    main()
