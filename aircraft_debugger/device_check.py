"""Send telemetry polls to the embedded core over its text link and compare every reply with Python.

The link partner is a board running embedded/firmware on a serial port, or the PC harness
as a child process. Both run embedded/link/at_text_link.c, so the same check covers both.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import time

from . import c_port


_MAX_NOISE_LINES = 200


class LinkError(RuntimeError):
    """The link partner did not answer as the text link requires."""


class HarnessTransport:
    """The PC harness reading standard input, standing in for a board."""

    def __init__(self, executable, *, timed=False):
        command = [str(executable), *(["--timed"] if timed else []), "-"]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def write(self, data):
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def readline(self):
        return self.process.stdout.readline()

    def close(self):
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.wait(timeout=10)


class SerialTransport:
    """A board on a serial port. Opening the port usually resets the board."""

    def __init__(self, port, *, baud=115200, timeout_s=5.0):
        try:
            import serial
        except ImportError as error:
            raise LinkError("Talking to a board needs pyserial: python -m pip install pyserial") from error
        self.port = serial.Serial(port, baudrate=baud, timeout=timeout_s)

    def write(self, data):
        self.port.write(data)
        self.port.flush()

    def readline(self):
        return self.port.readline()

    def close(self):
        self.port.close()


def _read(transport):
    """Return the next line, or raise when the partner is silent or gone."""
    line = transport.readline()
    if not line:
        raise LinkError("The link partner sent nothing before the timeout")
    return line.decode("ascii", errors="replace").strip()


def greet(transport, model_id):
    """Wait for the partner's greeting, check its model and return whether it sends timing lines."""
    transport.write(b"hello\n")
    for _ in range(_MAX_NOISE_LINES):
        words = _read(transport).split()
        if len(words) in (3, 4) and words[0] == "aerotrace" and words[2] == "ready":
            if words[1] != model_id:
                raise LinkError(f"The link partner was built for model {words[1]}, not {model_id}")
            return words[3:] == ["timed"]
    raise LinkError("The link partner did not send its greeting")


def _reply(transport, sample_index):
    """Skip unrelated lines, such as boot or log output, up to the reply for this poll."""
    for _ in range(_MAX_NOISE_LINES):
        line = _read(transport)
        if line == "error malformed line":
            raise LinkError(f"The link partner rejected a line of poll {sample_index}")
        if line.startswith(f"{sample_index} "):
            return line
    raise LinkError(f"The link partner did not reply to poll {sample_index}")


def run_streams(transport, streams, tables=None, *, fit=True):
    """Send each (name, schema 3 rows, raw bounds) stream poll by poll and compare the replies.

    Returns the poll counts, the mismatching polls and, when the partner reports them, the
    microseconds it spent in extraction and in the fit for every poll.
    """
    tables = tables or c_port.model_tables()
    timed = greet(transport, tables["model"]["model_id"])
    report = {"polls": 0, "framed": 0, "mismatches": [], "timed": timed,
              "extract_us": [], "fit_us": [], "round_trip_s": []}
    for label, lines, expected in c_port.stream_exchanges(streams, tables, fit=fit):
        started = time.perf_counter()
        transport.write(("\n".join(lines) + "\n").encode("ascii"))
        reply = _reply(transport, expected.split(" ", 1)[0])
        if timed:
            words = _read(transport).split()
            if len(words) != 3 or words[0] != "t" or not (words[1].isdigit() and words[2].isdigit()):
                raise LinkError(f"Expected a timing line after poll {label}")
            report["extract_us"].append(int(words[1]))
            report["fit_us"].append(int(words[2]))
        report["round_trip_s"].append(time.perf_counter() - started)
        report["polls"] += 1
        report["framed"] += not expected.endswith("none")
        if not c_port.same_poll(expected, reply, fit=fit):
            report["mismatches"].append(label)
    return report


def spread(values):
    """Median, 95th percentile and maximum of a non-empty list."""
    ordered = sorted(values)
    return statistics.median(ordered), ordered[min(len(ordered) - 1, (95 * len(ordered)) // 100)], ordered[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--port", help="Serial port of a board running embedded/firmware, for example COM5")
    target.add_argument("--harness", action="store_true",
                        help="Check the PC harness as a child process (its timing clock is coarse)")
    parser.add_argument("--baud", type=int, default=115200, help="Serial speed of the board's console")
    parser.add_argument("--check", nargs="+", type=Path, required=True, metavar="OBSERVATIONS",
                        help="Airborne recordings to send")
    parser.add_argument("--response-bounds", type=Path, help="Optional mechanism-to-effect delay bounds JSON")
    args = parser.parse_args()
    bounds = json.loads(args.response_bounds.read_text(encoding="utf-8")) if args.response_bounds else None
    with tempfile.TemporaryDirectory() as directory:
        try:
            streams = [(str(path), c_port.recording_rows(path), bounds) for path in args.check]
            if args.harness:
                transport = HarnessTransport(c_port.build_host(directory), timed=True)
            else:
                transport = SerialTransport(args.port, baud=args.baud)
            try:
                report = run_streams(transport, streams)
            finally:
                transport.close()
        except (OSError, ValueError, LinkError, c_port.CompilerUnavailable) as error:
            parser.exit(1, f"Device check failed: {error}\n")
    print(f"{report['polls'] - len(report['mismatches'])} of {report['polls']} polls identical "
          f"({report['framed']} with an evidence frame)")
    if report["timed"] and report["polls"]:
        for name, key in (("Extraction", "extract_us"), ("Fit", "fit_us")):
            median, high, worst = spread(report[key])
            print(f"{name} time reported by the link partner: median {median:.0f} us, "
                  f"95th percentile {high} us, maximum {worst} us")
    if report["polls"]:
        median, high, worst = spread(report["round_trip_s"])
        print(f"Round trip per poll over the link: median {1000 * median:.1f} ms, "
              f"95th percentile {1000 * high:.1f} ms, maximum {1000 * worst:.1f} ms")
    if report["mismatches"]:
        parser.exit(1, "Mismatching polls: " + ", ".join(report["mismatches"][:10]) + "\n")


if __name__ == "__main__":
    main()
