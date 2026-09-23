"""Replay USB diagnostic CSV through the production acquisition interface.

Run: python -m tools.replay_sensor_capture CAPTURE.csv --segments 8
Multiple rotated parts must be supplied in their original chronological order.
"""

import argparse
from collections import Counter
import csv
import json

from hardware.protocol import E_DATA_REPORT, protocol_parser
from hardware.sensor_frame import DeviceLayout, SensorFrameAssembler


def replay(paths, layout, *, byteorder="little"):
    assembler = SensorFrameAssembler(layout)
    buffer = bytearray()
    frames = dropped = 0
    first = last = None
    issues = Counter()
    received_ns = 0
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as source:
            for row in csv.DictReader(source):
                received_ns = int(row["monotonic_ns"])
                buffer.extend(bytes.fromhex(row["raw_hex"]))
                while True:
                    ret, kind, _, packet, _ = protocol_parser(buffer, frame_index_byteorder=byteorder)
                    if ret != 0:
                        break
                    if kind != E_DATA_REPORT:
                        continue
                    frame = assembler.feed(packet, received_ns)
                    issues.update(i.code for i in assembler.pop_issues())
                    if frame is not None:
                        frames += 1
                        dropped += frame.dropped_frames_before
                        if first is None:
                            first = frame.frame_index
                        last = frame
    assembler.expire(received_ns + 1_000_000_000)
    issues.update(i.code for i in assembler.pop_issues())
    return {
        "segments": len(layout.segments), "bits_per_frame": layout.bit_count,
        "sample_rate_hz": 1000, "frames": frames,
        "first_frame_index": first,
        "last_frame_index": last.frame_index if last else None,
        "sample_span_s": last.sample_time_s if last else None,
        "missing_frames": dropped, "issues": dict(issues),
        "trailing_bytes": len(buffer),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--segments", type=int, required=True)
    parser.add_argument("--byteorder", choices=("little", "big"), default="little")
    args = parser.parse_args()
    print(json.dumps(replay(args.paths, DeviceLayout.linear(args.segments), byteorder=args.byteorder), indent=2))


if __name__ == "__main__":
    main()
