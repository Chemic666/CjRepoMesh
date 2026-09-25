#!/usr/bin/env python3
"""Render every asciinema v2 event on its original, continuous timeline.

The output is a terminal-session replay, not a physical screen recording.
No intervals are removed or sped up.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import re
import subprocess

from PIL import Image, ImageDraw, ImageFont

from render_doctor_clip import BG, MUTED, PANEL, TEAL, WHITE, font


WIDTH, HEIGHT, FPS = 1280, 720, 4
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def load_cast(path: pathlib.Path) -> tuple[dict, list[tuple[float, str]]]:
    with path.open("r", encoding="utf-8") as stream:
        header = json.loads(stream.readline())
        if header.get("version") != 2:
            raise ValueError("Expected asciinema v2 recording")
        events = []
        previous = 0.0
        for number, line in enumerate(stream, start=2):
            at, kind, value = json.loads(line)
            if kind != "o" or not isinstance(value, str) or at < previous:
                raise ValueError(f"Invalid output event at line {number}")
            events.append((float(at), value))
            previous = at
    if not events or "All 4 core suites passed" not in "".join(value for _at, value in events):
        raise ValueError("Cast lacks a complete passing four-suite result")
    return header, events


class Terminal:
    def __init__(self) -> None:
        self.lines = [""]

    def feed(self, text: str) -> None:
        for character in ANSI.sub("", text):
            if character == "\n":
                self.lines.append("")
            elif character == "\r":
                # The captured suite emits CRLF; terminal cursor returns to column zero.
                # Keep existing text until LF, so a progress-update CR cannot erase evidence.
                continue
            elif character == "\b":
                self.lines[-1] = self.lines[-1][:-1]
            elif character >= " " or character == "\t":
                self.lines[-1] += character.expandtabs(4)
        if len(self.lines) > 200:
            self.lines = self.lines[-200:]


def draw_frame(terminal: Terminal, t: float, duration: float, started: str) -> bytes:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((34, 30, 1246, 690), 22, fill=PANEL)
    draw.rectangle((34, 30, 43, 690), fill=TEAL)
    draw.text((67, 55), "CjRepoMesh  /  Linux 四组原始终端回放", font=font(29, bold=True), fill=WHITE)
    clock = f"{int(t // 60):02d}:{int(t % 60):02d} / {int(duration // 60):02d}:{int(duration % 60):02d}"
    draw.text((66, 103), f"录制始于 {started}   ·   连续时间轴 {clock}", font=font(18), fill=MUTED)
    draw.line((66, 145, 1214, 145), fill="#2D4057", width=2)
    draw.rounded_rectangle((66, 167, 1214, 614), 12, fill="#08111F")
    mono = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 18)
    visible: list[str] = []
    for line in terminal.lines:
        if len(line) <= 115:
            visible.append(line)
        else:
            visible.extend(line[i : i + 115] for i in range(0, len(line), 115))
    for i, line in enumerate(visible[-19:]):
        color = TEAL if line.startswith("PASS ") or "PASS (" in line else WHITE
        if line.startswith("FAIL"):
            color = "#FF8B8B"
        draw.text((84, 181 + i * 22), line, font=mono, fill=color)
    draw.line((66, 634, 1214, 634), fill="#2D4057", width=2)
    draw.text((66, 651), "完整时间轴终端回放 / 未剪速；不是实际屏幕录制", font=font(18), fill=MUTED)
    draw.rounded_rectangle((66, 625, 66 + int(1148 * t / duration), 629), 2, fill=TEAL)
    return canvas.tobytes()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cast", type=pathlib.Path, required=True)
    parser.add_argument("--ffmpeg", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if not args.ffmpeg.is_file():
        parser.error(f"ffmpeg not found: {args.ffmpeg}")
    header, events = load_cast(args.cast)
    duration = max(events[-1][0], 1.0)
    started = dt.datetime.fromtimestamp(header["timestamp"], dt.timezone(dt.timedelta(hours=8)))
    started_text = started.strftime("%Y-%m-%d %H:%M:%S CST")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "21", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(args.output),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    terminal = Terminal()
    event_index = 0
    try:
        assert process.stdin is not None
        for frame_number in range(math.ceil(duration * FPS) + 1):
            at = frame_number / FPS
            while event_index < len(events) and events[event_index][0] <= at:
                terminal.feed(events[event_index][1])
                event_index += 1
            process.stdin.write(draw_frame(terminal, at, duration, started_text))
        process.stdin.close()
        assert process.stderr is not None
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        if process.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {stderr}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    print(f"Rendered {len(events)} uncut terminal events over {duration:.2f}s to {args.output}")


if __name__ == "__main__":
    main()
