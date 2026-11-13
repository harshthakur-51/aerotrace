"""Generate the embedded core's model tables and check the C fit against the Python fit."""

from __future__ import annotations

import argparse
import json
from math import inf, nextafter
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from . import propulsion_features as propulsion
from .airborne_profile import iter_profile_observations
from .diagnostic_features import MAXIMUM_OBSERVATION_GAP_SIM_S, build_feature_frames
from .evidence import THRESHOLDS
from .hypotheses import _predictions, generated_model
from .observations import CHANNELS
from .sequence_reasoning import (
    _LOCAL_WITNESSES, _STATUSES, _catalogue_orders, _fit_epoch, _response_bounds, _sequence_rows,
)


REPOSITORY = Path(__file__).resolve().parents[1]
EMBEDDED = REPOSITORY / "embedded"
MODEL_FILES = ("aerotrace_model.h", "aerotrace_model.c")
# sequence_reasoning._timing_constraints applies this rule by name.
_EXCLUDED_PATHS = {"inventory_before_pressure": "blue_pressure_loss"}
_STATES = {"not_observed": 0, "observed": 1, "unknown": 2}
_RELATION_STATES = {"not_applicable": 0, "unknown": 1, "consistent": 2, "contradicted": 3}
_CODES = {"compatible": "C", "unconfirmed": "U", "contradicted": "D",
          "excluded_by_dependency": "D", "excluded_by_timing": "T"}
_MAX_GROUPS = 5
# The channels the extractor reads, in wire order. The other profile channels only
# contribute to the two connection flags of a poll.
EXTRACT_CHANNELS = (
    "sim_time", "paused", "aircraft", "generator_2_voltage", "ac_bus_2", "blue_quantity", "blue_pressure",
    "main_gear_1_wow", "main_gear_2_wow", "height_agl", "engine_2_n2", "engine_2_fuel_flow",
    *propulsion.SUPPLY_CHANNELS,
)
_SUPPORTED_AIRCRAFT = {"A320-200-CFM", "A320-200-IAE", "A320neo-CFM", "A320neo-PW"}  # evidence.analyze_observations
_PROPULSION_CONSTANTS = (
    "USEFUL_SOURCE_PSI", "LOW_YELLOW_PRESSURE_PSI", "INSUFFICIENT_SOURCE_PSI", "MINIMUM_YELLOW_QUANTITY_RAW",
    "SUPPLY_SETTLING_SIM_S", "MAXIMUM_READING_SKEW_SIM_S", "MAXIMUM_SUPPLY_GAP_SIM_S",
)


class CompilerUnavailable(RuntimeError):
    pass


def model_tables(model=None):
    """Flatten the generated Python model into the indices and bit masks the C core uses."""
    model = model or generated_model()
    roots, facts = list(model["roots"]), list(model["facts"])
    relations = list(dict.fromkeys(rule["id"] for rule in model["temporal_constraints"]))

    def mask(names, order):
        return sum(1 << order.index(name) for name in set(names))

    required, reached = [], []
    for root in roots:
        _, paths = _predictions([root], model)
        required.append(mask((path["fact"] for path in paths if path["necessity"] == "required"), facts))
        reached.append(mask((path["fact"] for path in paths), facts))
    constraints = []
    for rule in model["temporal_constraints"]:
        name, kind, fact = rule["id"], "AT_RULE_NONE", 0
        if name in _LOCAL_WITNESSES:
            kind, fact = "AT_RULE_LOCAL_WITNESS", facts.index(_LOCAL_WITNESSES[name][0])
        elif name in _EXCLUDED_PATHS:
            kind, fact = "AT_RULE_EXCLUDED_PATH", facts.index(_EXCLUDED_PATHS[name])
        unless = roots.index(rule["unless_root"]) if rule.get("unless_root") else -1
        constraints.append((relations.index(name), roots.index(rule["root"]), unless, kind, fact))
    orders = _catalogue_orders(model)
    sets, histories, first = [], [], [0]
    for candidate in model["candidates"]:
        sets.append((candidate["id"], mask(candidate["roots"], roots)))
        for groups in orders[frozenset(candidate["roots"])]:
            histories.append((len(sets) - 1, [mask(group, roots) for group in groups]))
        first.append(len(histories))
    channels = list(EXTRACT_CHANNELS)
    thresholds = {name.upper(): value for name, value in THRESHOLDS.items()}
    thresholds.update({name: getattr(propulsion, name) for name in _PROPULSION_CONSTANTS})
    thresholds["MAXIMUM_OBSERVATION_GAP_SIM_S"] = MAXIMUM_OBSERVATION_GAP_SIM_S
    thresholds.update({f"RETAINED_{name.upper()}": level for name, level in propulsion._RETAINED_DRIVE_LEVELS.items()})
    return {"model": model, "roots": roots, "facts": facts, "relations": relations, "required": required,
            "reached": reached, "constraints": constraints, "sets": sets, "histories": histories, "first": first,
            "channels": channels, "thresholds": thresholds,
            "supply": [channels.index(name) for name in propulsion.SUPPLY_CHANNELS],
            "propulsion_facts": [(facts.index(fact), channels.index(channel), propulsion._EFFECT_THRESHOLDS[fact])
                                 for fact, (channel, _) in propulsion.PROPULSION_FACTS.items()],
            "drive_losses": [(relations.index(relation), channels.index(channel), below)
                             for relation, (channel, below) in propulsion._DRIVE_LOSSES.items()]}


def render_model(tables=None):
    """Return the generated header and source text."""
    tables = tables or model_tables()
    roots, facts, relations = tables["roots"], tables["facts"], tables["relations"]
    note = "/* Generated by `python -B -m aircraft_debugger.c_port --write-model`. Do not edit. */\n"

    def enum(prefix, names):
        return "enum {\n" + "".join(f"    {prefix}_{name.upper()} = {index},\n" for index, name in enumerate(names)) + "};\n"

    def strings(name, values, count):
        return (f"const char *const {name}[{count}] = {{\n"
                + "".join(f"    {json.dumps(value)},\n" for value in values) + "};\n")

    def numbers(kind, name, count, values, width=8, fmt="0x{:02x}"):
        rows = [", ".join(fmt.format(value) for value in values[start:start + width])
                for start in range(0, len(values), width)]
        return f"const {kind} {name}[{count}] = {{\n" + "".join(f"    {row},\n" for row in rows) + "};\n"

    header = note + f"""#ifndef AEROTRACE_MODEL_H
#define AEROTRACE_MODEL_H

#include <stdint.h>

#define AT_MODEL_ID {json.dumps(tables["model"]["model_id"])}
#define AT_ROOT_COUNT {len(roots)}
#define AT_FACT_COUNT {len(facts)}
#define AT_RELATION_COUNT {len(relations)}
#define AT_CONSTRAINT_COUNT {len(tables["constraints"])}
#define AT_SET_COUNT {len(tables["sets"])}
#define AT_HISTORY_COUNT {len(tables["histories"])}
#define AT_MAX_GROUPS {_MAX_GROUPS}
#define AT_CHANNEL_COUNT {len(tables["channels"])}
#define AT_SUPPLY_CHANNEL_COUNT {len(tables["supply"])}
#define AT_PROPULSION_FACT_COUNT {len(tables["propulsion_facts"])}
#define AT_DRIVE_LOSS_COUNT {len(tables["drive_losses"])}

/* Detector thresholds. Suffixes give the unit: V volts, PSI pounds per square inch, RAW model
 * quantity units, S seconds (SIM simulator clock, LOCAL receiving clock), READINGS a count. */
{"".join(f"#define AT_T_{name} {value!r}{chr(10)}" for name, value in tables["thresholds"].items())}
#define AT_RULE_NONE 0
#define AT_RULE_LOCAL_WITNESS 1
#define AT_RULE_EXCLUDED_PATH 2

{enum("AT_ROOT", roots)}
{enum("AT_FACT", facts)}
{enum("AT_RELATION", relations)}
{enum("AT_CHANNEL", tables["channels"])}
/* A temporal rule on `root`. It is waived when `unless_root` (-1 for none) is also present. */
typedef struct {{
    uint8_t relation;
    uint8_t root;
    int8_t unless_root;
    uint8_t rule;
    uint8_t fact;
}} at_constraint_t;

/* One onset history: its mechanism set and the ordered onset groups as root bit masks, 0-terminated. */
typedef struct {{
    uint8_t set;
    uint8_t group[AT_MAX_GROUPS];
}} at_history_t;

/* An effect that is observed when its channel reads below a threshold. */
typedef struct {{
    uint8_t fact;
    uint8_t channel;
    double below;
}} at_propulsion_fact_t;

/* A source output that counts as lost below a threshold while engine drive is retained. */
typedef struct {{
    uint8_t relation;
    uint8_t channel;
    double below;
}} at_drive_loss_t;

extern const char *const AT_CHANNEL_ID[AT_CHANNEL_COUNT];
extern const uint8_t AT_SUPPLY_CHANNEL[AT_SUPPLY_CHANNEL_COUNT];
extern const at_propulsion_fact_t AT_PROPULSION_FACT[AT_PROPULSION_FACT_COUNT];
extern const at_drive_loss_t AT_DRIVE_LOSS[AT_DRIVE_LOSS_COUNT];
extern const char *const AT_ROOT_ID[AT_ROOT_COUNT];
extern const char *const AT_FACT_ID[AT_FACT_COUNT];
extern const char *const AT_RELATION_ID[AT_RELATION_COUNT];
/* Bit f is set when the root reaches fact f through a required path, or through any path. */
extern const uint8_t AT_ROOT_REQUIRED[AT_ROOT_COUNT];
extern const uint8_t AT_ROOT_REACHED[AT_ROOT_COUNT];
extern const at_constraint_t AT_CONSTRAINT[AT_CONSTRAINT_COUNT];
extern const uint8_t AT_SET_ROOTS[AT_SET_COUNT];
/* Histories of set s occupy AT_HISTORY[AT_SET_FIRST_HISTORY[s]] up to AT_SET_FIRST_HISTORY[s + 1]. */
extern const uint16_t AT_SET_FIRST_HISTORY[AT_SET_COUNT + 1];
extern const at_history_t AT_HISTORY[AT_HISTORY_COUNT];

#endif
"""
    constraint_rows = "".join(
        f"    {{{relation}, {root}, {unless}, {kind}, {fact}}},\n"
        for relation, root, unless, kind, fact in tables["constraints"])
    history_rows = "".join(
        "    {" + f"{index}, {{" + ", ".join(f"0x{group:02x}" for group in groups + [0] * (_MAX_GROUPS - len(groups)))
        + "}},\n" for index, groups in tables["histories"])
    source = note + f"""#include "aerotrace_model.h"

{strings("AT_ROOT_ID", roots, "AT_ROOT_COUNT")}
{strings("AT_FACT_ID", facts, "AT_FACT_COUNT")}
{strings("AT_RELATION_ID", relations, "AT_RELATION_COUNT")}
{numbers("uint8_t", "AT_ROOT_REQUIRED", "AT_ROOT_COUNT", tables["required"])}
{numbers("uint8_t", "AT_ROOT_REACHED", "AT_ROOT_COUNT", tables["reached"])}
const at_constraint_t AT_CONSTRAINT[AT_CONSTRAINT_COUNT] = {{
{constraint_rows}}};

{numbers("uint8_t", "AT_SET_ROOTS", "AT_SET_COUNT", [roots for _, roots in tables["sets"]])}
{numbers("uint16_t", "AT_SET_FIRST_HISTORY", "AT_SET_COUNT + 1", tables["first"], fmt="{}")}
const at_history_t AT_HISTORY[AT_HISTORY_COUNT] = {{
{history_rows}}};

{strings("AT_CHANNEL_ID", tables["channels"], "AT_CHANNEL_COUNT")}
{numbers("uint8_t", "AT_SUPPLY_CHANNEL", "AT_SUPPLY_CHANNEL_COUNT", tables["supply"], fmt="{}")}
const at_propulsion_fact_t AT_PROPULSION_FACT[AT_PROPULSION_FACT_COUNT] = {{
{"".join(f"    {{{fact}, {channel}, {below!r}}},{chr(10)}" for fact, channel, below in tables["propulsion_facts"])}}};

const at_drive_loss_t AT_DRIVE_LOSS[AT_DRIVE_LOSS_COUNT] = {{
{"".join(f"    {{{relation}, {channel}, {below!r}}},{chr(10)}" for relation, channel, below in tables["drive_losses"])}}};
"""
    return header, source


def write_model():
    for name, text in zip(MODEL_FILES, render_model()):
        (EMBEDDED / "core" / name).write_text(text, encoding="utf-8", newline="\n")


def frame_case(name, frame, bounds, tables):
    """Serialize one evidence frame and its validated response bounds for the PC harness."""
    roots, facts = tables["roots"], tables["facts"]
    lines = [f"case {name}"]
    for root, effects in bounds.items():
        for effect, (minimum, maximum) in effects.items():
            lines.append(f"b {roots.index(root)} {facts.index(effect)} {float(minimum).hex()} {float(maximum).hex()}")
    for index, fact_id in enumerate(facts):
        fact = frame["facts"][fact_id]
        interval = fact["onset_interval"] if fact["state"] == "observed" else None
        lower = interval["lower_sim_time_s"] if interval else None
        upper = interval["upper_sim_time_s"] if interval else 0.0
        covered = bool(interval and interval["covered_through_confirmation"])
        # An absent lower bound is sent as the latest time before the upper bound. A core that
        # wrongly reads it gets the tightest possible onset floor, which the comparison then exposes.
        lines.append(f"f {index} {_STATES[fact['state']]} {int(lower is not None)} {int(covered)} "
                     f"{float(nextafter(upper, -inf) if lower is None else lower).hex()} {float(upper).hex()}")
    for index, relation_id in enumerate(tables["relations"]):
        relation = frame["temporal_relations"].get(relation_id, {})
        times = []
        if relation_id in _LOCAL_WITNESSES:
            channel = _LOCAL_WITNESSES[relation_id][1]
            times = [point["sim_time_s"] for point in relation.get("evidence", []) if point["channel"] == channel]
        lines.append(f"r {index} {_RELATION_STATES[relation.get('status', 'unknown')]} {int(bool(times))} "
                     f"{float(min(times, default=0.0)).hex()}")
    lines.append("end")
    return "\n".join(lines) + "\n"


def expected_line(name, epoch, tables):
    """Format the Python fit exactly as embedded/host/at_replay.c prints the C fit."""
    set_ids = [identifier for identifier, _ in tables["sets"]]
    histories = epoch["histories"]
    unique = epoch["unique_history_within_model"]
    minimal = sum(1 << set_ids.index(identifier) for identifier in epoch["minimal_possible_mechanism_sets"])
    support = []
    for fit in epoch["mechanism_sets"]:
        item = fit["dependency_evidence_support"]
        percent = -1 if item["percent"] is None else item["percent"]
        support.append(f"{percent}:{item['supported_checks']}:{item['total_checks']}:"
                       f"{item['unconfirmed_checks']}:{item['contradicted_checks']}")
    return " ".join([
        name, "0",
        "".join(_CODES[fit["dependency_status"]] for fit in epoch["mechanism_sets"]),
        "".join(_CODES[item["status"]] for item in histories),
        f"{minimal:08x}",
        str(next((index for index, item in enumerate(histories) if item is unique), -1)),
        *(str(epoch["history_counts"][status]) for status in _STATUSES),
        ",".join(support),
    ])


def _msvc_environment_script():
    program_files = os.environ.get("ProgramFiles(x86)")
    locator = Path(program_files or "", "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not program_files or not locator.is_file():
        return None
    found = subprocess.run(
        [str(locator), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
         "-property", "installationPath"], capture_output=True, text=True, check=False).stdout.strip().splitlines()
    script = Path(found[0], "VC", "Auxiliary", "Build", "vcvars64.bat") if found else None
    return script if script and script.is_file() else None


def build_host(directory):
    """Compile the PC harness with the first available C compiler and return the executable path."""
    directory = Path(directory)
    sources = [EMBEDDED / "core" / name for name in ("aerotrace_core.c", "aerotrace_extract.c", "aerotrace_model.c")]
    sources += [EMBEDDED / "link" / "at_text_link.c", EMBEDDED / "host" / "at_replay.c"]
    include, link = EMBEDDED / "core", EMBEDDED / "link"
    compiler = os.environ.get("CC") or next((name for name in ("cc", "gcc", "clang") if shutil.which(name)), None)
    if compiler:
        output = directory / "at_replay"
        command = [compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic", f"-I{include}", f"-I{link}",
                   *map(str, sources), "-o", str(output), "-lm"]
    else:
        environment = _msvc_environment_script() if os.name == "nt" else None
        if environment is None:
            raise CompilerUnavailable("No C compiler found. Set CC, or install gcc, clang or MSVC Build Tools.")
        output = directory / "at_replay.exe"
        script = directory / "build.cmd"
        files = " ".join(f'"{path}"' for path in sources)
        script.write_text(
            f'@echo off\r\ncall "{environment}" >nul || exit /b 1\r\n'
            f'cl /nologo /std:c11 /O2 /W4 /WX /I"{include}" /I"{link}" {files} /Fo"{directory}\\\\" /Fe"{output}"\r\n',
            encoding="utf-8", newline="")
        command = ["cmd", "/d", "/c", str(script)]
    # A stray quote in PATH makes the MSVC environment script fail to parse.
    environment_variables = {**os.environ, "PATH": os.environ.get("PATH", "").replace('"', "")}
    built = subprocess.run(command, capture_output=True, text=True, check=False, env=environment_variables)
    if built.returncode != 0 or not output.is_file():
        raise RuntimeError(f"The embedded core did not compile:\n{built.stdout}\n{built.stderr}")
    return output


def run_harness(executable, text, directory):
    """Run the PC harness on text-link lines and return its reply lines."""
    case_file = Path(directory) / "cases.txt"
    case_file.write_text(text, encoding="ascii", newline="\n")
    command = [str(executable), str(case_file)]
    run = subprocess.run(command, capture_output=True, text=True, check=False)
    if run.returncode != 0:
        raise RuntimeError(f"The PC harness failed: {run.stderr}")
    return run.stdout.splitlines()


def compare(cases, executable, directory, tables=None):
    """Fit each (name, frame, raw bounds) case in Python and in C. Return (case count, mismatching names)."""
    tables = tables or model_tables()
    model = tables["model"]
    catalogue = _catalogue_orders(model)
    text, expected, labels = [], [], []
    for label, frame, raw_bounds in cases:
        name = str(len(labels))
        labels.append(label)
        bounds = _response_bounds(raw_bounds, model)
        text.append(frame_case(name, frame, bounds, tables))
        expected.append(expected_line(name, _fit_epoch(frame, model, bounds, catalogue), tables))
    actual = run_harness(executable, "".join(text), directory)
    if len(actual) != len(expected):
        raise RuntimeError(f"The PC harness returned {len(actual)} results for {len(expected)} cases")
    return len(expected), [label for label, want, got in zip(labels, expected, actual) if want != got]


def _bits(value):
    return struct.pack(">d", float(value)).hex()


def frame_signature(frame, tables):
    """Format an evidence frame exactly as embedded/host/at_replay.c prints an extracted frame."""
    facts, relations = [], []
    for fact_id in tables["facts"]:
        fact = frame["facts"][fact_id]
        interval = fact["onset_interval"] if fact["state"] == "observed" else None
        lower = interval["lower_sim_time_s"] if interval else None
        covered = bool(interval and interval["covered_through_confirmation"])
        facts.append(f"{_STATES[fact['state']]}:{int(lower is not None)}:{int(covered)}:{_bits(lower or 0.0)}:"
                     f"{_bits(interval['upper_sim_time_s'] if interval else 0.0)}")
    for relation_id in tables["relations"]:
        relation = frame["temporal_relations"][relation_id]
        times = []
        if relation_id in _LOCAL_WITNESSES:
            channel = _LOCAL_WITNESSES[relation_id][1]
            times = [point["sim_time_s"] for point in relation["evidence"] if point["channel"] == channel]
        relations.append(f"{_RELATION_STATES[relation['status']]}:{int(bool(times))}:{_bits(min(times, default=0.0))}")
    return ",".join(facts) + " " + ",".join(relations)


def poll_lines(row, tables):
    """Serialize the channels the extractor reads from one validated poll."""
    readings = row["readings"]
    base_connected = any(reading["reachable"] for name, reading in readings.items() if name in CHANNELS)
    lines = [f"s {row['sample_index']} {float(row['received_monotonic_s']).hex()} {int(row['connected'])} "
             f"{int(base_connected)} {int('external_power_output' in readings)}"]
    for index, channel in enumerate(tables["channels"]):
        reading = readings.get(channel)
        if reading is None:
            continue
        value, time = reading["value"], reading["sim_time_s"]
        if channel == "aircraft":
            value = 2 if value == "A320-200-CFM" else int(value in _SUPPORTED_AIRCRAFT)
        lines.append(f"c {index} {int(reading['valid'])} {int(reading['reachable'])} {int(time is not None)} "
                     f"{float(value if reading['valid'] else 0.0).hex()} {float(time or 0.0).hex()} "
                     f"{float(reading['received_monotonic_s']).hex()}")
    lines.append("go")
    return lines


def compare_streams(streams, executable, directory, tables=None, *, fit=True):
    """Extract and fit each (name, schema 3 rows, raw bounds) stream after every poll, in Python and in C.

    Returns the number of polls, the number that produced a frame, and the mismatching polls.
    With fit=False only the extracted evidence frames are compared.
    """
    tables = tables or model_tables()
    text, expected, labels, framed = stream_expectations(streams, tables, fit=fit)
    actual = run_harness(executable, text, directory)
    if len(actual) != len(expected):
        raise RuntimeError(f"The PC harness returned {len(actual)} results for {len(expected)} polls")
    return len(expected), framed, [label for label, want, got in zip(labels, expected, actual)
                                   if not same_poll(want, got, fit=fit)]


def same_poll(want, got, *, fit=True):
    return want == (got if fit or want.endswith("none") else got[:len(want)])


def stream_exchanges(streams, tables, *, fit=True):
    """Yield (label, lines to send, reply Python expects) for every poll of every stream.

    The first poll of a stream also carries the stream header and its response bounds.
    """
    model = tables["model"]
    catalogue = _catalogue_orders(model)
    roots, facts = tables["roots"], tables["facts"]
    for number, (label, rows, raw_bounds) in enumerate(streams):
        bounds = _response_bounds(raw_bounds, model)
        lines = [f"stream {number}"]
        lines += [f"b {roots.index(root)} {facts.index(effect)} {float(low).hex()} {float(high).hex()}"
                  for root, effects in bounds.items() for effect, (low, high) in effects.items()]
        frames = build_feature_frames(rows, generated=True, sequence_prefixes=True)["frames"]
        for row, prefix in zip(rows, frames):
            frame = prefix["sequence_epoch"]
            lines += poll_lines(row, tables)
            expected = f"{row['sample_index']} 0 none"
            if frame is not None:
                fitted = expected_line("", _fit_epoch(frame, model, bounds, catalogue), tables) if fit else " "
                expected = f"{row['sample_index']} 0 {frame_signature(frame, tables)}{fitted}"
            yield f"{label}@{row['sample_index']}", lines, expected
            lines = []


def stream_expectations(streams, tables, *, fit=True):
    """Serialize the streams for the PC harness and compute the lines Python expects back."""
    text, expected, labels = [], [], []
    for label, lines, reply in stream_exchanges(streams, tables, fit=fit):
        text += lines
        expected.append(reply)
        labels.append(label)
    framed = sum(not reply.endswith("none") for reply in expected)
    return "\n".join(text) + "\n", expected, labels, framed


def recording_rows(path):
    """Read one schema 2 or 3 airborne recording as the schema 3 rows the sequence fit uses."""
    return _sequence_rows(iter_profile_observations(Path(path)))[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-model", action="store_true", help="Regenerate embedded/core/aerotrace_model.[ch]")
    parser.add_argument("--check", nargs="+", type=Path, metavar="OBSERVATIONS",
                        help="Compare C with Python on these recordings after every poll")
    parser.add_argument("--response-bounds", type=Path, help="Optional mechanism-to-effect delay bounds JSON")
    args = parser.parse_args()
    if args.write_model:
        write_model()
    if args.check:
        bounds = json.loads(args.response_bounds.read_text(encoding="utf-8")) if args.response_bounds else None
        with tempfile.TemporaryDirectory() as directory:
            try:
                executable = build_host(directory)
            except CompilerUnavailable as error:
                parser.exit(1, f"{error}\n")
            total, failures = 0, []
            for path in args.check:
                try:
                    rows = recording_rows(path)
                    count, framed, wrong = compare_streams([(str(path), rows, bounds)], executable, directory)
                except (OSError, ValueError) as error:
                    print(f"{path}: not usable as a schema 2 or 3 airborne recording ({error})")
                    continue
                print(f"{path}: {count - len(wrong)} of {count} polls identical ({framed} with an evidence frame)")
                total += count
                failures += wrong
        print(f"{total - len(failures)} of {total} polls identical")
        if failures:
            parser.exit(1, "Mismatching polls: " + ", ".join(failures[:10]) + "\n")


if __name__ == "__main__":
    main()
