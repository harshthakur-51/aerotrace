"""Run an airborne experiment while a board diagnoses the same public observations as they arrive.

The experiment controller polls the simulator and owns every fault command. Each public
observation it records is also sent to the board over the text link, and the board's reply
and screen are saved beside the recording. The board never receives a fault command or flag.
After the run, the saved replies are compared with what Python computes from the recording.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import time

from . import c_port, device_check
from . import screen as screen_layout
from .airborne_experiment import CASES, PROPULSION_CASES, run_experiment
from .airborne_profile import iter_profile_observations
from .airborne_record import load_settings
from .sequence_reasoning import _sequence_rows


REPLIES = "board-replies.jsonl"
CHECK = "board-check.json"


class BoardObserver:
    """Forward each public observation to the link partner and keep what it answers.

    A link failure stops the forwarding and is reported; it never reaches the experiment
    controller, which must stay free to clear the faults it set.
    """

    def __init__(self, transport, output, *, bounds=None, tables=None, echo=print):
        self.transport, self.output, self.echo = transport, Path(output), echo
        self.tables = tables or c_port.model_tables()
        self.timed = device_check.greet(transport, self.tables["model"]["model_id"])
        self._pending = c_port.stream_header(0, bounds, self.tables)
        self._log = None
        self._shown = None
        self.failure = None
        self.polls = 0

    def accept(self, record):
        if self.failure is not None:
            return
        try:
            self._forward(_sequence_rows([record])[1][0])
        except Exception as error:  # The experiment continues without the board.
            self.failure = f"{type(error).__name__}: {error}"
            self.echo(f"BOARD LINK STOPPED at poll {record.get('sample_index')}: {self.failure}")

    def _forward(self, row):
        index = str(row["sample_index"])
        lines = self._pending + c_port.poll_lines(row, self.tables) + ["screen"]
        self._pending = []
        started = time.perf_counter()
        self.transport.write(("\n".join(lines) + "\n").encode("ascii"))
        entry = {"sample_index": row["sample_index"], "reply": device_check._reply(self.transport, index)}
        if self.timed:
            words = device_check._read(self.transport).split()
            if len(words) != 3 or words[0] != "t":
                raise device_check.LinkError("Expected a timing line")
            entry.update(extract_us=int(words[1]), fit_us=int(words[2]))
        words = device_check._read(self.transport).split()
        if len(words) != 2 or words[0] != "screen":
            raise device_check.LinkError("Expected a screen line")
        entry.update(screen=words[1], round_trip_s=time.perf_counter() - started)
        if self._log is None:
            self._log = (self.output / REPLIES).open("x", encoding="utf-8", newline="\n")
        self._log.write(json.dumps(entry) + "\n")
        self._log.flush()
        self.polls += 1
        pages = screen_layout.pages_from_hex(words[1])
        text = screen_layout.as_text(screen_layout.decode(pages))
        if text != self._shown:
            self._shown = text
            (self.output / f"board-screen-{row['sample_index']:04d}.png").write_bytes(screen_layout.png(pages))
            self.echo(f"--- board screen at poll {index} ---\n{text}")

    def close(self):
        if self._log is not None:
            self._log.close()
        self.transport.close()


def check_replies(output, *, bounds=None, tables=None):
    """Compare the saved board replies with Python's fit of the recorded observations."""
    output = Path(output)
    tables = tables or c_port.model_tables()
    rows = _sequence_rows(iter_profile_observations(output / "observations.jsonl"))[1]
    replies = {}
    path = output / REPLIES
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            replies[entry["sample_index"]] = entry
    mismatches, missing, framed = [], [], 0
    for row, (_, _, expected) in zip(rows, c_port.stream_exchanges([("live", rows, bounds)], tables)):
        entry = replies.get(row["sample_index"])
        framed += not expected.endswith("none")
        if entry is None:
            missing.append(row["sample_index"])
        elif entry["reply"] != expected:
            mismatches.append(row["sample_index"])
    report = {"polls_recorded": len(rows), "polls_answered": len(replies), "polls_with_evidence_frame": framed,
              "polls_identical_to_python": len(rows) - len(missing) - len(mismatches),
              "mismatching_polls": mismatches, "unanswered_polls": missing}
    for key in ("extract_us", "fit_us", "round_trip_s"):
        values = [entry[key] for entry in replies.values() if key in entry]
        if values:
            median, high, worst = device_check.spread(values)
            report[key] = {"median": median, "percentile_95": high, "maximum": worst}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New folder for the recording and board replies")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--board-port", help="Serial port of a board running embedded/firmware, for example COM3")
    target.add_argument("--harness", action="store_true", help="Use the PC harness in place of a board")
    target.add_argument("--check-only", action="store_true", help="Only recheck the replies saved in --output")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--case", choices=tuple(CASES | PROPULSION_CASES), default="isolated_yellow_edp")
    parser.add_argument("--config", type=Path, help="Qualification settings JSON")
    parser.add_argument("--ptu", choices=("auto", "off"), help="Required PTU switch setting for propulsion trials")
    parser.add_argument("--active-seconds", type=float, default=8.0)
    parser.add_argument("--recovery-seconds", type=float, default=5.0)
    parser.add_argument("--max-wait-seconds", type=float, default=120.0)
    parser.add_argument("--maximum-postfault-local-seconds", type=float, default=60.0)
    parser.add_argument("--port", type=int, default=8088, help="Simulator property server port")
    parser.add_argument("--response-bounds", type=Path, help="Optional mechanism-to-effect delay bounds JSON")
    args = parser.parse_args()
    bounds = json.loads(args.response_bounds.read_text(encoding="utf-8")) if args.response_bounds else None
    failure = None
    if not args.check_only:
        if args.case not in PROPULSION_CASES:
            parser.error("The board reads the propulsion observation profile; choose a propulsion case")
        with tempfile.TemporaryDirectory() as directory:
            if args.harness:
                transport = device_check.HarnessTransport(c_port.build_host(directory), timed=True)
            else:
                transport = device_check.SerialTransport(args.board_port, baud=args.baud)
            observer = BoardObserver(transport, args.output, bounds=bounds)
            print(f"Board link ready on {args.board_port or 'the PC harness'}", flush=True)
            try:
                run_experiment(args.output, args.case, load_settings(args.config),
                               active_s=args.active_seconds, recovery_s=args.recovery_seconds,
                               max_wait_s=args.max_wait_seconds,
                               maximum_postfault_local_s=args.maximum_postfault_local_seconds, port=args.port,
                               on_observation=observer.accept,
                               ptu_selected=None if args.ptu is None else args.ptu == "auto")
            finally:
                observer.close()
            failure = observer.failure
    report = check_replies(args.output, bounds=bounds)
    report["link_failure"] = failure
    (args.output / CHECK).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
    if failure or report["mismatching_polls"] or report["unanswered_polls"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
