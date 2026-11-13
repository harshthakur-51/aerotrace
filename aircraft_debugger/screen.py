"""Layout of the embedded core's 128 x 64 monochrome screen, and tools to inspect it on a PC.

The drawing code that a board runs is embedded/display/at_screen.c. This module holds its
font and labels (generated into the C tables), a Python reference of the same layout for
the tests, a decoder that turns the C frame buffer back into text, and a PNG writer.

Text is 21 characters wide in a 5 x 7 font on a 6-pixel pitch:

    y  0- 8  inverted bar: AEROTRACE and the overall state
    y 10-32  three lines: the smallest mechanism sets that fit, numbered, "?" when unconfirmed
    y 34-40  how many onset histories are compatible (C) and unconfirmed (U)
    y 45-63  the eight effects in fixed cells: boxed when observed, "?" when unread
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import zlib


WIDTH, HEIGHT, PAGES = 128, 64, 8
FONT_FIRST, FONT_COUNT = 32, 64  # the characters " " to "_"
# Layout in pixels. embedded/display/at_screen.c mirrors these values.
COLUMNS, LEFT, PITCH = 21, 1, 6
HEADER_TEXT_Y, BODY_Y, BODY_ROWS, LINE_HEIGHT, HISTORY_Y = 1, 10, 3, 8, 34
EFFECTS_Y, EFFECTS_PER_ROW, EFFECT_PITCH_X, EFFECT_PITCH_Y = 45, 4, 32, 10
HEADER_HEIGHT, EFFECT_BOX_WIDTH, EFFECT_BOX_HEIGHT = 9, 31, 9
ROOT_TAGS = {
    "generator_2_source_path_fault": "GEN2",
    "blue_fluid_loss_mechanism": "BLEAK",
    "blue_pressure_supply_loss": "BPUMP",
    "engine_2_power_loss": "ENG2",
    "yellow_engine_driven_pump_supply_loss": "YEDP",
}
FACT_TAGS = {
    "generator_source_anomaly": "GEN2",
    "blue_inventory_loss": "BQTY",
    "bus_supply_loss": "BUS2",
    "blue_pressure_loss": "BPRS",
    "engine_2_fuel_flow_loss": "FF2",
    "engine_2_core_speed_loss": "N2",
    "yellow_edp_output_loss": "YEDP",
    "yellow_line_pressure_loss": "YPRS",
}
# Original 5 x 7 glyphs, top row first. A character without a glyph is drawn as "?".
_GLYPHS = {
    " ": "..... ..... ..... ..... ..... ..... .....",
    "!": "..#.. ..#.. ..#.. ..#.. ..#.. ..... ..#..",
    "#": ".#.#. .#.#. ##### .#.#. ##### .#.#. .#.#.",
    "%": "##..# ##..# ...#. ..#.. .#... #..## #..##",
    "(": "...#. ..#.. .#... .#... .#... ..#.. ...#.",
    ")": ".#... ..#.. ...#. ...#. ...#. ..#.. .#...",
    "*": "..... #.#.# .###. ##### .###. #.#.# .....",
    "+": "..... ..#.. ..#.. ##### ..#.. ..#.. .....",
    ",": "..... ..... ..... ..... .##.. ..#.. .#...",
    "-": "..... ..... ..... ##### ..... ..... .....",
    ".": "..... ..... ..... ..... ..... .##.. .##..",
    "/": "....# ....# ...#. ..#.. .#... #.... #....",
    "0": ".###. #...# #..## #.#.# ##..# #...# .###.",
    "1": "..#.. .##.. ..#.. ..#.. ..#.. ..#.. .###.",
    "2": ".###. #...# ....# ...#. ..#.. .#... #####",
    "3": "####. ....# ....# .###. ....# ....# ####.",
    "4": "...#. ..##. .#.#. #..#. ##### ...#. ...#.",
    "5": "##### #.... ####. ....# ....# #...# .###.",
    "6": "..##. .#... #.... ####. #...# #...# .###.",
    "7": "##### ....# ...#. ..#.. .#... .#... .#...",
    "8": ".###. #...# #...# .###. #...# #...# .###.",
    "9": ".###. #...# #...# .#### ....# ...#. .##..",
    ":": "..... ..#.. ..... ..... ..... ..#.. .....",
    "<": "...#. ..#.. .#... #.... .#... ..#.. ...#.",
    "=": "..... ..... ##### ..... ##### ..... .....",
    ">": ".#... ..#.. ...#. ....# ...#. ..#.. .#...",
    "?": ".###. #...# ....# ...#. ..#.. ..... ..#..",
    "A": ".###. #...# #...# ##### #...# #...# #...#",
    "B": "####. #...# #...# ####. #...# #...# ####.",
    "C": ".###. #...# #.... #.... #.... #...# .###.",
    "D": "####. #...# #...# #...# #...# #...# ####.",
    "E": "##### #.... #.... ####. #.... #.... #####",
    "F": "##### #.... #.... ####. #.... #.... #....",
    "G": ".###. #...# #.... #.### #...# #...# .###.",
    "H": "#...# #...# #...# ##### #...# #...# #...#",
    "I": ".###. ..#.. ..#.. ..#.. ..#.. ..#.. .###.",
    "J": "..### ...#. ...#. ...#. ...#. #..#. .##..",
    "K": "#...# #..#. #.#.. ##... #.#.. #..#. #...#",
    "L": "#.... #.... #.... #.... #.... #.... #####",
    "M": "#...# ##.## #.#.# #.#.# #...# #...# #...#",
    "N": "#...# ##..# #.#.# #..## #...# #...# #...#",
    "O": ".###. #...# #...# #...# #...# #...# .###.",
    "P": "####. #...# #...# ####. #.... #.... #....",
    "Q": ".###. #...# #...# #...# #.#.# #..#. .##.#",
    "R": "####. #...# #...# ####. #.#.. #..#. #...#",
    "S": ".#### #.... #.... .###. ....# ....# ####.",
    "T": "##### ..#.. ..#.. ..#.. ..#.. ..#.. ..#..",
    "U": "#...# #...# #...# #...# #...# #...# .###.",
    "V": "#...# #...# #...# #...# #...# .#.#. ..#..",
    "W": "#...# #...# #...# #.#.# #.#.# ##.## #...#",
    "X": "#...# #...# .#.#. ..#.. .#.#. #...# #...#",
    "Y": "#...# #...# .#.#. ..#.. ..#.. ..#.. ..#..",
    "Z": "##### ....# ...#. ..#.. .#... #.... #####",
    "_": "..... ..... ..... ..... ..... ..... #####",
}


def glyph_columns(character):
    """The five column bytes of a glyph. Bit 0 is the top pixel."""
    rows = _GLYPHS.get(character, _GLYPHS["?"]).split()
    return [sum(1 << y for y in range(7) if rows[y][x] == "#") for x in range(5)]


def font_table():
    return [glyph_columns(chr(FONT_FIRST + index)) for index in range(FONT_COUNT)]


def _explanation_lines(number, mark, tags):
    """Join tags with "+" and wrap after a "+". Continuation lines are indented by two spaces."""
    lines, line = [], f"{number}{mark}"
    for index, tag in enumerate(tags):
        piece = tag + ("+" if index + 1 < len(tags) else "")
        if len(line) + len(piece) > COLUMNS:
            lines.append(line)
            line = "  "
        line += piece
    return lines + [line]


def screen_content(epoch, model):
    """Reference layout: what the screen shows for a fitted epoch, or for None before any airborne poll.

    Returns the header, the body lines, the history line and, for each effect in model order,
    its cell text and whether the cell is boxed. `epoch` comes from sequence_reasoning._fit_epoch.
    """
    facts, roots = list(model["facts"]), list(model["roots"])
    body, history, state = [], "", "NO DATA"
    if epoch is None:
        body = ["WAITING FOR AIRBORNE", "TELEMETRY"]
    else:
        fits = {fit["id"]: fit for fit in epoch["mechanism_sets"]}
        minimal = epoch["minimal_possible_mechanism_sets"]
        unread = sum(epoch["facts"][name]["state"] == "unknown" for name in facts)
        if not minimal:
            state, body = "NO FIT", ["NO MODELLED CAUSE", "FITS THE READINGS"]
        elif minimal == ["selected_reference"]:
            state = "NO FAULT"
            body = ["NO SELECTED FAULT", f"{unread} OF {len(facts)} UNREAD" if unread else "ALL CHANNELS READ"]
        else:
            state = f"{len(minimal)} CAUSE" + ("S" if len(minimal) > 1 else "")
            for index, identifier in enumerate(minimal):
                fit = fits[identifier]
                mark = " " if fit["history_counts"]["compatible"] else "?"
                lines = _explanation_lines(index + 1, mark, [ROOT_TAGS[root] for root in roots if root in fit["roots"]])
                # Keep one line free for "+N MORE" unless this is the last set.
                if len(body) + len(lines) + (1 if index + 1 < len(minimal) else 0) > BODY_ROWS:
                    body.append(f"+{len(minimal) - index} MORE")
                    break
                body += lines
        counts = epoch["history_counts"]
        history = f"HIST C:{counts['compatible']} U:{counts['unconfirmed']}"
        if epoch["unique_history_within_model"] is not None:
            history += " UNIQUE"
    effects = []
    for name in facts:
        fact_state = "unknown" if epoch is None else epoch["facts"][name]["state"]
        effects.append(((FACT_TAGS[name] + ("?" if fact_state == "unknown" else "")).ljust(5), fact_state == "observed"))
    return {
        "header": "AEROTRACE" + state.rjust(COLUMNS - len("AEROTRACE")),
        "body": [line.ljust(COLUMNS) for line in body + [""] * (BODY_ROWS - len(body))],
        "history": history.ljust(COLUMNS),
        "effects": effects,
    }


def render(content):
    """Draw screen content into a frame buffer, pixel for pixel as embedded/display/at_screen.c does."""
    pages = [bytearray(WIDTH) for _ in range(PAGES)]

    def plot(x, y, lit):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            if lit:
                pages[y // 8][x] |= 1 << (y % 8)
            else:
                pages[y // 8][x] &= ~(1 << (y % 8))

    def fill(left, top, width, height):
        for y in range(top, top + height):
            for x in range(left, left + width):
                plot(x, y, True)

    def draw(text, x, y, inverted=False):
        for index, character in enumerate(text):
            for column, bits in enumerate(glyph_columns(character)):
                for row in range(7):
                    if bits >> row & 1:
                        plot(x + PITCH * index + column, y + row, not inverted)

    for line, text in enumerate(content["body"]):
        draw(text, LEFT, BODY_Y + LINE_HEIGHT * line)
    draw(content["history"], LEFT, HISTORY_Y)
    fill(0, 0, WIDTH, HEADER_HEIGHT)
    draw(content["header"], LEFT, HEADER_TEXT_Y, inverted=True)
    for index, (label, boxed) in enumerate(content["effects"]):
        left = EFFECT_PITCH_X * (index % EFFECTS_PER_ROW)
        top = EFFECTS_Y + EFFECT_PITCH_Y * (index // EFFECTS_PER_ROW)
        if boxed:
            fill(left, top, EFFECT_BOX_WIDTH, EFFECT_BOX_HEIGHT)
        draw(label, left + 2, top + 1, inverted=boxed)
    return [bytes(page) for page in pages]


def decode(pages):
    """Read a frame buffer (8 pages of 128 column bytes) back into the structure of screen_content."""
    glyphs = {tuple(glyph_columns(character)): character for character in _GLYPHS}

    def lit(x, y):
        return bool(pages[y // 8][x] >> (y % 8) & 1)

    def text(x, y, count, inverted):
        result = ""
        for index in range(count):
            left = x + PITCH * index
            columns = tuple(sum((lit(left + column, y + row) != inverted) << row for row in range(7))
                            for column in range(5))
            result += glyphs.get(columns, "�")
        return result

    effects = []
    for index in range(len(FACT_TAGS)):
        left = EFFECT_PITCH_X * (index % EFFECTS_PER_ROW)
        top = EFFECTS_Y + EFFECT_PITCH_Y * (index // EFFECTS_PER_ROW)
        boxed = lit(left, top)
        effects.append((text(left + 2, top + 1, 5, boxed), boxed))
    return {
        "header": text(LEFT, HEADER_TEXT_Y, COLUMNS, True),
        "body": [text(LEFT, BODY_Y + LINE_HEIGHT * line, COLUMNS, False) for line in range(BODY_ROWS)],
        "history": text(LEFT, HISTORY_Y, COLUMNS, False),
        "effects": effects,
    }


def as_text(content):
    """A plain-text view of a screen. A boxed effect is shown in square brackets."""
    cells = [f"[{label.strip()}]" if boxed else label.replace(" ", "") for label, boxed in content["effects"]]
    return "\n".join([content["header"], *content["body"], content["history"],
                      " ".join(cells[:EFFECTS_PER_ROW]), " ".join(cells[EFFECTS_PER_ROW:])])


def pages_from_hex(text):
    data = bytes.fromhex(text)
    if len(data) != PAGES * WIDTH:
        raise ValueError(f"A screen is {PAGES * WIDTH} bytes, not {len(data)}")
    return [data[page * WIDTH:(page + 1) * WIDTH] for page in range(PAGES)]


def png(pages, *, scale=4, lit=(120, 220, 255), dark=(8, 12, 20)):
    """Encode the frame buffer as a PNG image, each pixel enlarged `scale` times."""
    rows = []
    for y in range(HEIGHT):
        pixels = b"".join(bytes(lit if pages[y // 8][x] >> (y % 8) & 1 else dark) * scale for x in range(WIDTH))
        rows += [b"\x00" + pixels] * scale

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", WIDTH * scale, HEIGHT * scale, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")


def main():
    import tempfile

    from . import c_port

    parser = argparse.ArgumentParser(description="Render the embedded screen for one poll of a recording.")
    parser.add_argument("--observations", required=True, type=Path, help="Airborne recording")
    parser.add_argument("--response-bounds", type=Path, help="Optional mechanism-to-effect delay bounds JSON")
    parser.add_argument("--poll", type=int, default=-1, help="Position of the poll in the recording; the last by default")
    parser.add_argument("--output", required=True, type=Path, help="PNG file to write")
    args = parser.parse_args()
    bounds = json.loads(args.response_bounds.read_text(encoding="utf-8")) if args.response_bounds else None
    with tempfile.TemporaryDirectory() as directory:
        try:
            rows = c_port.recording_rows(args.observations)
            rows = rows[:len(rows) + args.poll + 1] if args.poll < 0 else rows[:args.poll + 1]
            pages = c_port.screens([("recording", rows, bounds)], c_port.build_host(directory), directory)[-1]
        except (OSError, ValueError, IndexError, c_port.CompilerUnavailable) as error:
            parser.exit(1, f"Screen rendering failed: {error}\n")
    args.output.write_bytes(png(pages))
    print(as_text(decode(pages)))


if __name__ == "__main__":
    main()
