#!/usr/bin/env python3
"""Convert util-linux script's classic output/timing logs to asciinema v2.

The result replays authentic terminal bytes and timing. It is not a screen
recording, and does not replace the competition's uncut video requirement.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re


TIMING_LINE = re.compile(r"(?P<delay>\d+(?:\.\d+)?)\s+(?P<size>\d+)\s*$")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-log", type=pathlib.Path, required=True)
    parser.add_argument("--timing-log", type=pathlib.Path, required=True)
    parser.add_argument("--cast", type=pathlib.Path, required=True)
    parser.add_argument("--title", default="CjRepoMesh Linux core verification")
    parser.add_argument("--width", type=int, default=120)
    parser.add_argument("--height", type=int, default=35)
    args = parser.parse_args()
    if args.width < 40 or args.height < 10:
        parser.error("terminal size is too small")
    recorded = args.output_log.read_bytes()
    if not recorded.startswith(b"Script started on "):
        raise ValueError("Output log lacks the util-linux script header")
    header_end = recorded.index(b"\n") + 1
    started_line = recorded[:header_end].decode("utf-8", errors="strict")
    started_match = re.match(r"Script started on (\S+)", started_line)
    if started_match is None:
        raise ValueError("Could not parse the script recording start time")
    started_at = dt.datetime.fromisoformat(started_match.group(1))
    output = recorded[header_end:]
    offset = 0
    elapsed = 0.0
    events: list[list[object]] = []
    for number, line in enumerate(args.timing_log.read_text(encoding="utf-8").splitlines(), start=1):
        match = TIMING_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"Unsupported classic timing format at line {number}: {line!r}")
        delay = float(match.group("delay"))
        size = int(match.group("size"))
        if delay < 0 or size < 0:
            raise ValueError(f"Invalid timing at line {number}")
        elapsed += delay
        chunk = output[offset : offset + size]
        if len(chunk) != size:
            raise ValueError(f"Output ends before timing line {number}")
        offset += size
        if chunk:
            events.append([round(elapsed, 6), "o", chunk.decode("utf-8", errors="replace")])
    trailer = output[offset:]
    if not trailer.lstrip(b"\r\n").startswith(b"Script done on "):
        raise ValueError(f"Timing covers {offset} bytes, output contains {len(output)} bytes")
    header = {
        "version": 2,
        "width": args.width,
        "height": args.height,
        "timestamp": int(started_at.timestamp()),
        "title": args.title,
        "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"},
    }
    args.cast.parent.mkdir(parents=True, exist_ok=True)
    with args.cast.open("w", encoding="utf-8", newline="\n") as cast:
        cast.write(json.dumps(header, ensure_ascii=False, separators=(",", ":")) + "\n")
        for event in events:
            cast.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"Wrote {len(events)} events / {elapsed:.2f}s to {args.cast}")


if __name__ == "__main__":
    main()
