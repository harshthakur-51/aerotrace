"""Plant deliberate bugs in a copy of the embedded C core and report which ones the tests detect.

Run from the repository root. It needs a C compiler and takes about a quarter of an hour.
Name one or more source files to plant bugs only in those:

    python -B scripts/mutate_embedded_core.py
    python -B scripts/mutate_embedded_core.py at_screen.c

Each entry is (description, text to replace, replacement). A bug is detected when any
test frame or telemetry poll gives a result that differs from the Python implementation.
The entries named in EQUIVALENT cannot change the output, for the reason given there.
"""

from pathlib import Path
import shutil
import sys
import tempfile

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPOSITORY), str(REPOSITORY / "tests")]

from aircraft_debugger import c_port, screen  # noqa: E402
from aircraft_debugger.sequence_reasoning import _catalogue_orders, _fit_epoch, _response_bounds  # noqa: E402
import test_c_port  # noqa: E402
import test_screen  # noqa: E402
from test_sequence_reasoning import RESULTS  # noqa: E402

EQUIVALENT = {
    "floor on conditional paths": "Response bounds are accepted only for required paths.",
    "quantity confirms on first reading": "The first quantity reading is the reference, so its drop is zero.",
    "event ignores epoch": "An event of an earlier clock epoch is confirmed before the current window starts.",
    "epoch not advanced": "An event of an earlier clock epoch is confirmed before the current window starts.",
    "core ignores base connection": "An unreachable poll has no valid simulator clock, which already makes it unusable.",
    "context ignores connection": "An unreachable poll has no valid simulator clock, which already makes it unusable.",
    "wrap one character early": "No combination of the current labels fills a screen line exactly.",
    "unknown character left blank": "Every label and message uses characters inside the font range.",
}

FIT_MUTATIONS = [
    ("strict order ignored", "&& !strictly_after[root]);", ");"),
    ("deadline made exclusive", "infimum_s[root] < item->latest_s[root]\n                    || (infimum_s[root] == item->latest_s[root] && !strictly_after[root]);",
     "infimum_s[root] < item->latest_s[root];"),
    ("floor uses minimum delay", "fact->lower_s - bound->maximum_s", "fact->lower_s - bound->minimum_s"),
    ("deadline uses maximum delay", "fact->upper_s - (declared ? bound->minimum_s : 0.0)", "fact->upper_s - (declared ? bound->maximum_s : 0.0)"),
    ("coverage ignored", "covered = fact->covered && fact->has_lower && fact->lower_s < fact->upper_s;", "covered = 1;"),
    ("missing lower bound ignored", "fact->covered && fact->has_lower &&", "fact->covered &&"),
    ("floor on conditional paths", "covered && declared && (AT_ROOT_REQUIRED[root] & BIT(index))", "covered && declared"),
    ("excluded path kept", "excluded[rule->root] |= BIT(rule->fact);", "(void)excluded;"),
    ("missing witness ignored", "out->missing_witness = 1;", "out->missing_witness = 0;"),
    ("witness minimum ignored", "relation->witness_s - (bound && bound->declared ? bound->minimum_s : 0.0)", "relation->witness_s - 0.0 * (bound && bound->declared ? bound->minimum_s : 0.0)"),
    ("witness deadline dropped", "out->deadline[out->deadline_count++] = witness[index];", "(void)witness[index];"),
    ("unless_root not honoured", "(rule->unless_root >= 0 && (roots & BIT(rule->unless_root)))", "0"),
    ("relation counted twice", "checked |= BIT(rule->relation);", ""),
    ("unknown relation contradicts", "} else if (status == AT_CHECK_UNKNOWN) {\n            out->unconfirmed_checks++;", "} else if (status == 99) {\n            out->unconfirmed_checks++;"),
    ("conditional effect checked", "continue; /* conditional consequence: retained and degraded outputs both fit */", ""),
    ("unknown required effect fits", "unconfirmed_required = 1;", "unconfirmed_required = 0;"),
    ("rounding half up", "(2u * remainder == total && (quotient & 1u))", "(2u * remainder == total)"),
    ("minimal ignores possibility", "if (((possible >> other) & 1u) && smaller != roots", "if (smaller != roots"),
    ("unique ignores unconfirmed", "compatible_total == 1 && !unconfirmed_possible", "compatible_total == 1"),
    ("group floor takes first root", "constraints->floor_s[root] > floor_s", "floor_s == -INFINITY"),
    ("earliest not carried forward", "            earliest_s = floor_s;\n            strict = 0;", "            strict = 0;"),
]

EXTRACT_MUTATIONS = [
    ("stale readings accepted", "    return reading->present && receipt_s - reading->received_s > AT_T_MAXIMUM_READING_AGE_LOCAL_S;", "    (void)reading; (void)receipt_s; return 0;"),
    ("core accepts repeated channel time", "return had && reading->sim_time_s <= old_s ? NULL : reading;", "return had && reading->sim_time_s < old_s ? NULL : reading;"),
    ("context ignores stale", "    if (stale(reading, sample->received_s)) {\n        usable = 0;\n    }\n    if (!reading->has_time) {\n        return 0;\n    }\n    if (x->context_has_time", "    if (!reading->has_time) {\n        return 0;\n    }\n    if (x->context_has_time"),
    ("context accepts repeated channel time", "reading->sim_time_s <= x->context_time_s[channel]", "reading->sim_time_s < x->context_time_s[channel]"),
    ("context accepts untimed reading", "    if (!reading->has_time) {\n        return 0;\n    }\n    if (x->context_has_time", "    if (x->context_has_time"),
    ("generator energized exclusive", "reading->value >= AT_T_ENERGIZED_REFERENCE_AT_LEAST_V", "reading->value > AT_T_ENERGIZED_REFERENCE_AT_LEAST_V"),
    ("generator low inclusive", "reading->value < AT_T_GENERATOR_UNAVAILABLE_BELOW_V", "reading->value <= AT_T_GENERATOR_UNAVAILABLE_BELOW_V"),
    ("generator needs no reference", "        if (!x->generator_reference) {", "        if (0) {"),
    ("generator restore keeps active", "        x->generator_reference = 1;\n        x->generator_active = 0;", "        x->generator_reference = 1;"),
    ("generator restore keeps low count", "        x->generator_active = 0;\n        x->generator_low_count = 0;", "        x->generator_active = 0;"),
    ("generator reduced keeps low count", "        x->generator_low_count = 0;\n        state = AT_STATE_OBSERVED; /* reduced output */", "        state = AT_STATE_OBSERVED; /* reduced output */"),
    ("generator unusable keeps low count", "    if (reading == NULL) {\n        x->generator_low_count = 0;\n        return unknown_view();", "    if (reading == NULL) {\n        return unknown_view();"),
    ("unusable poll keeps low count", "        x->generator_low_count = 0; /* an unusable poll must not complete a confirmation */", ""),
    ("generator needs one reading", "x->generator_low_count >= AT_T_GENERATOR_CONFIRMATION_READINGS", "x->generator_low_count >= 1"),
    ("generator onset at confirmation", "x->generator_event.onset = x->generator_low_first;", "x->generator_event.onset = now;"),
    ("generator lower bound dropped", "x->generator_event.normal_before = x->generator_normal_before;", "x->generator_event.normal_before.has = 0;"),
    ("generator no-reference low is observed", "        if (!x->generator_reference) {\n            x->generator_low_count = 0;", "        if (!x->generator_reference) {\n            x->generator_low_count = 0;\n            state = AT_STATE_OBSERVED;"),
    ("quantity onset exclusive", "drop >= AT_T_BLUE_QUANTITY_ONSET_DROP_RAW && !x->quantity_onset.has", "drop > AT_T_BLUE_QUANTITY_ONSET_DROP_RAW && !x->quantity_onset.has"),
    ("quantity onset never cleared", "    } else if (drop < AT_T_BLUE_QUANTITY_ONSET_DROP_RAW && !x->quantity_active) {\n        x->quantity_onset.has = 0;\n    }", "    }"),
    ("quantity confirms on first reading", "drop >= AT_T_BLUE_QUANTITY_DROP_RAW && x->quantity_count >= AT_T_QUANTITY_MINIMUM_PROGRESSING_READINGS", "drop >= AT_T_BLUE_QUANTITY_DROP_RAW"),
    ("quantity drop exclusive", "if (drop >= AT_T_BLUE_QUANTITY_DROP_RAW", "if (drop > AT_T_BLUE_QUANTITY_DROP_RAW"),
    ("quantity recovery exclusive", "drop <= AT_T_BLUE_QUANTITY_RECOVERY_TOLERANCE_RAW", "drop < AT_T_BLUE_QUANTITY_RECOVERY_TOLERANCE_RAW"),
    ("quantity recovery keeps active", "        x->quantity_active = 0;\n        x->quantity_onset.has = 0;\n    } else if (x->quantity_active) {", "        x->quantity_onset.has = 0;\n    } else if (x->quantity_active) {"),
    ("quantity recovery keeps onset", "        x->quantity_active = 0;\n        x->quantity_onset.has = 0;\n    } else if (x->quantity_active) {", "        x->quantity_active = 0;\n    } else if (x->quantity_active) {"),
    ("quantity pending reference not soft", "        view.soft = 1;", ""),
    ("quantity onset at confirmation", "x->quantity_event.onset = x->quantity_onset;", "x->quantity_event.onset = now;"),
    ("quantity lower bound dropped", "x->quantity_event.normal_before = x->quantity_normal_before;", "x->quantity_event.normal_before.has = 0;"),
    ("quantity developing drop is normal", "known_view(drop >= AT_T_BLUE_QUANTITY_ONSET_DROP_RAW ? AT_STATE_UNKNOWN : AT_STATE_NOT_OBSERVED, reading)", "known_view(AT_STATE_NOT_OBSERVED, reading)"),
    ("retained threshold exclusive", "reading->value >= retained_at_least", "reading->value > retained_at_least"),
    ("observed effect not latched", "    if (track->observed) {\n        return;", "    if (track->observed && index == 0xffffffffu) {\n        return;"),
    ("unavailable poll ignored", "        track->any_unavailable = 1;", ""),
    ("pending ignores soft flag", "view->state == AT_STATE_UNKNOWN && !view->soft", "view->state == AT_STATE_UNKNOWN"),
    ("pending ignored", "        track->any_pending = 1;", ""),
    ("skipped poll not a gap", "index != track->last_point.index + 1 || delta_s <= 0.0", "delta_s <= 0.0"),
    ("gap limit inclusive", "delta_s > AT_T_MAXIMUM_OBSERVATION_GAP_SIM_S", "delta_s >= AT_T_MAXIMUM_OBSERVATION_GAP_SIM_S"),
    ("gap ignored", "                track->any_gap = 1;", ""),
    ("absence from one reading", "track->point_count >= 2 && !track->any_unavailable", "track->point_count >= 1 && !track->any_unavailable"),
    ("coverage ignores gaps", "(uint8_t)(!track->any_unavailable && !track->any_gap)", "(uint8_t)(!track->any_unavailable)"),
    ("coverage ignores unavailable", "(uint8_t)(!track->any_unavailable && !track->any_gap)", "(uint8_t)(!track->any_gap)"),
    ("event ignores window start", "event->epoch == epoch && window_start <= event->confirmation_index\n                && event->confirmation_index <= index", "event->epoch == epoch && window_start <= index\n                && event->confirmation_index <= index"),
    ("event ignores epoch", "event->has && event->epoch == epoch && ", "event->has && event->epoch <= epoch && "),
    ("event onset ignored", "if (event != NULL && event->has &&", "if (event != NULL && event->has && index == 0xffffffffu &&"),
    ("last normal not recorded", "        track->last_normal.has = 1;", ""),
    ("supply skew ignored", "if (complete && latest_s - earliest_s <= AT_T_MAXIMUM_READING_SKEW_SIM_S\n            && ", "if (complete\n            && "),
    ("supply incomplete accepted", "        complete = complete && measured[AT_SUPPLY_CHANNEL[index]];", "        complete = complete && (measured[AT_SUPPLY_CHANNEL[index]] || index > 0);"),
    ("supply pump threshold inclusive", "reading[AT_CHANNEL_YELLOW_EDP_PRESSURE].value < AT_T_INSUFFICIENT_SOURCE_PSI", "reading[AT_CHANNEL_YELLOW_EDP_PRESSURE].value <= AT_T_INSUFFICIENT_SOURCE_PSI"),
    ("supply quantity exclusive", "reading[AT_CHANNEL_YELLOW_QUANTITY].value >= AT_T_MINIMUM_YELLOW_QUANTITY_RAW", "reading[AT_CHANNEL_YELLOW_QUANTITY].value > AT_T_MINIMUM_YELLOW_QUANTITY_RAW"),
    ("supply ignores transfer", "double alternate = electric > transfer ? electric : transfer;", "double alternate = electric; (void)transfer;"),
    ("supply backed exclusive", "if (alternate >= AT_T_USEFUL_SOURCE_PSI) {", "if (alternate > AT_T_USEFUL_SOURCE_PSI) {"),
    ("supply unbacked inclusive", "} else if (alternate < AT_T_INSUFFICIENT_SOURCE_PSI) {", "} else if (alternate <= AT_T_INSUFFICIENT_SOURCE_PSI) {"),
    ("supply continuity ignores mode", "mode != SUPPLY_NONE && mode == x->supply_previous_mode", "mode != SUPPLY_NONE && x->supply_previous_mode != SUPPLY_NONE"),
    ("supply continuity ignores index", "mode == x->supply_previous_mode\n        && sample->sample_index == x->supply_previous_index + 1;", "mode == x->supply_previous_mode;"),
    ("supply continuity ignores gaps", "        continuous = 0.0 < delta_s && delta_s <= AT_T_MAXIMUM_SUPPLY_GAP_SIM_S;\n    }\n    if (!continuous) {", "        (void)delta_s;\n    }\n    if (!continuous) {"),
    ("supply gap inclusive", "        continuous = 0.0 < delta_s && delta_s <= AT_T_MAXIMUM_SUPPLY_GAP_SIM_S;\n    }\n    if (!continuous) {", "        continuous = 0.0 < delta_s && delta_s < AT_T_MAXIMUM_SUPPLY_GAP_SIM_S;\n    }\n    if (!continuous) {"),
    ("supply settling exclusive", "settled_s >= AT_T_SUPPLY_SETTLING_SIM_S", "settled_s > AT_T_SUPPLY_SETTLING_SIM_S"),
    ("supply settling ignored", "    if (settled_s >= AT_T_SUPPLY_SETTLING_SIM_S) {", "    if (1) {"),
    ("supply settles on slowest channel", "if (index == 0 || elapsed_s < settled_s) {", "if (index == 0 || elapsed_s > settled_s) {"),
    ("supply line retained exclusive", "uint8_t expected = line >= AT_T_USEFUL_SOURCE_PSI", "uint8_t expected = line > AT_T_USEFUL_SOURCE_PSI"),
    ("supply line low inclusive", ": line < AT_T_LOW_YELLOW_PRESSURE_PSI ?", ": line <= AT_T_LOW_YELLOW_PRESSURE_PSI ?"),
    ("supply contradiction not raised", "        } else if (expected != SUPPLY_NONE) {\n            x->supply_contradicted = 1;", "        } else if (expected != SUPPLY_NONE) {"),
    ("drive speed exclusive", "reading[AT_CHANNEL_ENGINE_2_N2].value >= AT_T_RETAINED_ENGINE_2_N2", "reading[AT_CHANNEL_ENGINE_2_N2].value > AT_T_RETAINED_ENGINE_2_N2"),
    ("drive fuel exclusive", "reading[AT_CHANNEL_ENGINE_2_FUEL_FLOW].value >= AT_T_RETAINED_ENGINE_2_FUEL_FLOW", "reading[AT_CHANNEL_ENGINE_2_FUEL_FLOW].value > AT_T_RETAINED_ENGINE_2_FUEL_FLOW"),
    ("drive ignores fuel flow", "measured[AT_CHANNEL_ENGINE_2_N2] && measured[AT_CHANNEL_ENGINE_2_FUEL_FLOW]\n        && reading[AT_CHANNEL_ENGINE_2_N2].value >= AT_T_RETAINED_ENGINE_2_N2\n        && reading[AT_CHANNEL_ENGINE_2_FUEL_FLOW].value >= AT_T_RETAINED_ENGINE_2_FUEL_FLOW;", "measured[AT_CHANNEL_ENGINE_2_N2] && measured[AT_CHANNEL_ENGINE_2_FUEL_FLOW]\n        && reading[AT_CHANNEL_ENGINE_2_N2].value >= AT_T_RETAINED_ENGINE_2_N2;"),
    ("drive loss inclusive", "reading[channel].value < AT_DRIVE_LOSS[index].below", "reading[channel].value <= AT_DRIVE_LOSS[index].below"),
    ("drive skew ignored", "< AT_DRIVE_LOSS[index].below\n            && latest_s - earliest_s <= AT_T_MAXIMUM_READING_SKEW_SIM_S;", "< AT_DRIVE_LOSS[index].below;\n        (void)latest_s; (void)earliest_s;"),
    ("drive single poll suffices", "sustained = witness && track->has_previous && !track->contradicted", "sustained = witness && !track->contradicted"),
    ("drive ignores skipped poll", "&& !track->contradicted\n            && sample->sample_index == track->previous_index + 1;", "&& !track->contradicted;"),
    ("drive ignores gaps", "            sustained = 0.0 < delta_s && delta_s <= AT_T_MAXIMUM_SUPPLY_GAP_SIM_S;\n        }\n        if (sustained) {", "            (void)delta_s;\n        }\n        if (sustained) {"),
    ("drive witness time is later poll", "track->witness_s = track->previous_s[2];", "track->witness_s = time_s[2];"),
    ("drive witness not latched", "track->has_previous && !track->contradicted", "track->has_previous"),
    ("core ignores base connection", "core_unusable = !sample->base_connected\n        || ", "core_unusable = "),
    ("core ignores aircraft", "        || !(aircraft->present && aircraft->valid && aircraft->value >= AT_AIRCRAFT_SUPPORTED)\n", ""),
    ("core needs CFM aircraft", "aircraft->value >= AT_AIRCRAFT_SUPPORTED)", "aircraft->value >= AT_AIRCRAFT_A320_200_CFM)"),
    ("pause ignored", "!(pause->present && pause->valid) || pause->value != 0.0;", "!(pause->present && pause->valid);"),
    ("core ignores stale aircraft", " || stale(aircraft, sample->received_s);", ";"),
    ("context ignores connection", "context_unusable = !sample->connected || ", "context_unusable = "),
    ("context ignores negative clock", "|| clock->value < 0.0 ", ""),
    ("context ignores untimed clock", "        || !clock->has_time || (pause->present && pause->valid && !pause->has_time);", "        ;"),
    ("context ignores untimed pause", "|| (pause->present && pause->valid && !pause->has_time);", ";"),
    ("local clock reset ignored", "if ((x->has_receipt && sample->received_s < x->previous_receipt_s)\n            || (has_sim_time", "if ((has_sim_time"),
    ("simulator clock reset ignored", "\n            || (has_sim_time && x->has_sim_time && clock->value < x->previous_sim_time_s)) {", ") {"),
    ("reset keeps window", "        clear_window(x);\n        core_unusable", "        core_unusable"),
    ("reset keeps generator state", "        x->generator_reference = x->generator_active = x->generator_low_count = 0;\n", ""),
    ("reset keeps quantity state", "        x->quantity_reference = x->quantity_active = x->quantity_count = 0;\n        x->quantity_onset.has = 0;\n", ""),
    ("reset keeps core channel times", "        memset(x->core_has_time, 0, sizeof x->core_has_time);\n", ""),
    ("reset keeps context channel times", "        memset(x->context_has_time, 0, sizeof x->context_has_time);\n", ""),
    ("reset poll usable", "        clear_window(x);\n        core_unusable = context_unusable = 1;", "        clear_window(x);"),
    ("epoch not advanced", "        x->epoch++;\n", ""),
    ("frozen clock accepted", "    } else if (has_sim_time && x->has_sim_time && clock->value == x->previous_sim_time_s) {\n        core_unusable = context_unusable = 1;\n    }", "    }"),
    ("airborne ignores aircraft type", "usable[AT_CHANNEL_AIRCRAFT] && aircraft->value == AT_AIRCRAFT_A320_200_CFM", "usable[AT_CHANNEL_AIRCRAFT]"),
    ("airborne ignores gear 1", "        && usable[AT_CHANNEL_MAIN_GEAR_1_WOW] && reading[AT_CHANNEL_MAIN_GEAR_1_WOW].value == 0.0\n", ""),
    ("airborne ignores gear 2", "        && usable[AT_CHANNEL_MAIN_GEAR_2_WOW] && reading[AT_CHANNEL_MAIN_GEAR_2_WOW].value == 0.0\n", ""),
    ("airborne ignores height", "\n        && usable[AT_CHANNEL_HEIGHT_AGL] && reading[AT_CHANNEL_HEIGHT_AGL].value > 0.0;", ";"),
    ("airborne height inclusive", "reading[AT_CHANNEL_HEIGHT_AGL].value > 0.0;", "reading[AT_CHANNEL_HEIGHT_AGL].value >= 0.0;"),
    ("negative readings measured", "(uint8_t)(airborne && usable[index] && reading[index].value >= 0.0)", "(uint8_t)(airborne && usable[index])"),
    ("propulsion threshold inclusive", "reading[rule->channel].value < rule->below", "reading[rule->channel].value <= rule->below"),
    ("startup ground polls kept", "        if (sample->startup_capture\n", "        if (sample->startup_capture && sample->sample_index == 0xffffffffu\n"),
    ("ground rule applied to every capture", "        if (sample->startup_capture\n", "        if (1\n"),
    ("startup ignores gear 2", "                     && gear_2->present && gear_2->valid && gear_2->value == 0.0\n", "                     && gear_2->present\n"),
    ("startup height inclusive", "height->valid && height->value > 0.0)) {", "height->valid && height->value >= 0.0)) {"),
    ("window start not recorded", "        x->window_start_index = sample->sample_index;\n", ""),
    ("order needs no separate polls (quantity first)", " && quantity->upper_index < pressure->lower.index", ""),
    ("order needs no separate polls (pressure first)", " && pressure->upper_index < quantity->lower.index", ""),
    ("order ignores coverage", " || !quantity->covered || !pressure->covered", ""),
    ("order ignores missing lower bound", "!quantity->lower.has || !pressure->lower.has || ", ""),
    ("order directions swapped", "        relation->status = AT_CHECK_CONSISTENT;\n    } else if (pressure->upper_s", "        relation->status = AT_CHECK_CONTRADICTED;\n    } else if (pressure->upper_s"),
    ("supply relation not gated on pump loss", "!x->fact[AT_FACT_YELLOW_EDP_OUTPUT_LOSS].observed ? AT_CHECK_NOT_APPLICABLE\n        : ", ""),
    ("absence ignores pending", " && !track->any_pending\n", "\n"),
    ("absence ignores gaps", "                && !track->any_gap ? AT_STATE_NOT_OBSERVED", "                ? AT_STATE_NOT_OBSERVED"),
    ("covered flag dropped", "            fact->covered = track->covered;", "            fact->covered = 1;"),
]

SCREEN_MUTATIONS = [
    ("wrap one character early", "        if (column + length > COLUMNS) {", "        if (column + length >= COLUMNS) {"),
    ("continuation not indented", "            column = 2;", "            column = 0;"),
    ("wrong joining sign", 'put_text(screen, BODY_Y + LINE_HEIGHT * line, end, "+", 0);', 'put_text(screen, BODY_Y + LINE_HEIGHT * line, end, "-", 0);'),
    ("no line kept for MORE", "if (line + lines + (count - shown - 1 ? 1u : 0u) > BODY_ROWS) {", "if (line + lines > BODY_ROWS) {"),
    ("MORE count off by one", 'count - shown), " MORE", 0);', 'count - shown - 1), " MORE", 0);'),
    ("unconfirmed mark dropped", "history_count[AT_COMPATIBLE] ? ' ' : '?';", "history_count[AT_COMPATIBLE] ? ' ' : ' ';"),
    ("set numbers start at two", "explanation(screen, line, shown + 1, mark, AT_SET_ROOTS[set], 1);", "explanation(screen, line, shown + 2, mark, AT_SET_ROOTS[set], 1);"),
    ("no-fault test on wrong set", "} else if (result->minimal_sets == 1u) {", "} else if (result->minimal_sets == 2u) {"),
    ("unread counts observed effects", "unread += frame->fact[index].state == AT_STATE_UNKNOWN;", "unread += frame->fact[index].state == AT_STATE_OBSERVED;"),
    ("history counts swapped", "column, result->history_count[AT_COMPATIBLE])", "column, result->history_count[AT_UNCONFIRMED])"),
    ("UNIQUE always shown", "if (result->unique_history >= 0) {", "if (result->unique_history >= -1) {"),
    ("plural for one cause", 'count > 1u ? " CAUSES" : " CAUSE"', 'count > 0u ? " CAUSES" : " CAUSE"'),
    ("unread effect boxed", "int observed = fact_state == AT_STATE_OBSERVED;", "int observed = fact_state != AT_STATE_NOT_OBSERVED;"),
    ("unread mark wrong", "put_character(screen, x, top + 1, '?', 0);", "put_character(screen, x, top + 1, '!', 0);"),
    ("second effect row misplaced", "EFFECT_PITCH_Y * (index / EFFECTS_PER_ROW)", "EFFECT_PITCH_Y * (index % 2u)"),
    ("state not right-aligned", "put_text(screen, HEADER_TEXT_Y, COLUMNS - (unsigned)strlen(state), state, 1);", "put_text(screen, HEADER_TEXT_Y, 10, state, 1);"),
    ("glyph mirrored", "(AT_FONT[glyph][column] >> row) & 1u", "(AT_FONT[glyph][4u - column] >> row) & 1u"),
    ("inverted text not cut out", "set_pixel(screen, x + column, y + row, !inverted);", "set_pixel(screen, x + column, y + row, inverted + 1);"),
    ("effect box one row short", "fill(screen, left, top, EFFECT_BOX_WIDTH, EFFECT_BOX_HEIGHT);", "fill(screen, left, top, EFFECT_BOX_WIDTH, EFFECT_BOX_HEIGHT - 1u);"),
    ("header bar one row short", "fill(screen, 0, 0, AT_SCREEN_WIDTH, HEADER_HEIGHT);", "fill(screen, 0, 0, AT_SCREEN_WIDTH, HEADER_HEIGHT - 1u);"),
    ("pixel written to wrong page", "screen->page[y / 8u][x] |= mask;", "screen->page[(y + 1u) / 8u % AT_SCREEN_PAGES][x] |= mask;"),
    ("unknown character left blank", "        glyph = (unsigned)'?' - AT_FONT_FIRST;", "        glyph = 0;"),
]


def prepare():
    """Serialize every test frame and telemetry stream once, with the results Python expects."""
    tables = c_port.model_tables()
    model = tables["model"]
    catalogue = _catalogue_orders(model)
    frames, expected = [], []
    cases = [*test_c_port.fixture_cases(), *test_c_port.unknown_cases(), *test_c_port.retained_drive_cases(),
             *test_c_port.boundary_cases()]
    for index, (_, frame, raw) in enumerate(cases):
        bounds = _response_bounds(raw, model)
        frames.append(c_port.frame_case(str(index), frame, bounds, tables))
        expected.append(c_port.expected_line(str(index), _fit_epoch(frame, model, bounds, catalogue), tables))
    recorded = [(folder, c_port.recording_rows(RESULTS / folder / "observations.jsonl"), bounds)
                for folder, bounds in test_c_port.RECORDED_FLIGHTS]
    generated = [(f"seed-{seed}", test_c_port.telemetry_stream(seed), None)
                 for seed in range(test_c_port.FUZZ_STREAMS)] + test_c_port.scripted_streams()
    streams = [(c_port.stream_expectations(recorded, tables, fit=True), True),
               (c_port.stream_expectations(generated, tables, fit=False), False)]

    # Screens: the frame buffer after each fixture frame and after each poll of some streams.
    screen_text, screen_pages = [], []
    for index, (_, frame, raw) in enumerate([*test_c_port.fixture_cases(), *test_c_port.unknown_cases(),
                                             *test_screen.unread_mix_cases()]):
        bounds = _response_bounds(raw, model)
        screen_text.append(c_port.frame_case(str(index), frame, bounds, tables) + "screen\n")
        screen_pages.append(screen.render(screen.screen_content(_fit_epoch(frame, model, bounds, catalogue), model)))
    shown = recorded[:5] + test_c_port.scripted_streams()
    for _, lines, _ in c_port.stream_exchanges(shown, tables, fit=False):
        screen_text.append("\n".join([*lines, "screen"]) + "\n")
    for _, rows, raw in shown:
        bounds = _response_bounds(raw, model)
        for prefix in c_port.build_feature_frames(rows, generated=True, sequence_prefixes=True)["frames"]:
            frame = prefix["sequence_epoch"]
            epoch = None if frame is None else _fit_epoch(frame, model, bounds, catalogue)
            screen_pages.append(screen.render(screen.screen_content(epoch, model)))
    return "".join(frames), expected, streams, "".join(screen_text), screen_pages


def mismatches(executable, directory, prepared):
    frames, expected, streams, screen_text, screen_pages = prepared
    wrong = sum(want != got for want, got in zip(expected, c_port.run_harness(executable, frames, directory)))
    for (text, lines, _, _), fit in streams:
        actual = c_port.run_harness(executable, text, directory)
        wrong += sum(not c_port.same_poll(want, got, fit=fit) for want, got in zip(lines, actual))
    drawn = [screen.pages_from_hex(line.split()[1])
             for line in c_port.run_harness(executable, screen_text, directory) if line.startswith("screen ")]
    wrong += abs(len(drawn) - len(screen_pages)) + sum(want != got for want, got in zip(screen_pages, drawn))
    return wrong


def main():
    prepared = prepare()
    original = c_port.EMBEDDED
    problems, detected, total = [], 0, 0
    targets = [("core", "aerotrace_core.c", [("unmodified", "", "")] + FIT_MUTATIONS),
               ("core", "aerotrace_extract.c", EXTRACT_MUTATIONS), ("display", "at_screen.c", SCREEN_MUTATIONS)]
    chosen = set(sys.argv[1:])
    unknown = chosen - {filename for _, filename, _ in targets}
    if unknown:
        sys.exit(f"Unknown source file: {sorted(unknown)}")
    for folder, filename, mutations in targets:
        if chosen and filename not in chosen:
            continue
        source = (original / folder / filename).read_text(encoding="utf-8")
        for name, old, new in mutations:
            if old and source.count(old) != 1:
                problems.append(f"{name}: the text to replace occurs {source.count(old)} times")
                continue
            with tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "embedded"
                shutil.copytree(original, copy, ignore=shutil.ignore_patterns("firmware"))
                (copy / folder / filename).write_text(source.replace(old, new) if old else source,
                                                      encoding="utf-8", newline="\n")
                c_port.EMBEDDED = copy
                try:
                    executable = c_port.build_host(directory)
                except RuntimeError:
                    problems.append(f"{name}: the modified core did not compile")
                    continue
                finally:
                    c_port.EMBEDDED = original
                wrong = mismatches(executable, directory, prepared)
            if not old:
                if wrong:
                    problems.append(f"the unmodified core differs from Python on {wrong} cases")
                continue
            total += 1
            detected += bool(wrong)
            print(f"{'detected' if wrong else 'not detected'}  {filename}: {name} ({wrong} differing results)")
            if bool(wrong) == (name in EQUIVALENT):
                problems.append(f"{name}: " + ("expected to be equivalent but was detected" if wrong else "not detected"))
    print(f"{detected} of {total} deliberate bugs detected; {len(EQUIVALENT)} are listed as unable to change the output")
    for name, reason in EQUIVALENT.items():
        print(f"  {name}: {reason}")
    if problems:
        sys.exit("\n".join(problems))


if __name__ == "__main__":
    main()
