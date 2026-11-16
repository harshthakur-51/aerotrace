#define _CRT_SECURE_NO_WARNINGS

#include "at_screen.h"

#include <string.h>

/* Layout in pixels. aircraft_debugger/screen.py mirrors these values. */
#define COLUMNS 21
#define LEFT 1
#define PITCH 6
#define HEADER_HEIGHT 9
#define HEADER_TEXT_Y 1
#define BODY_Y 10
#define BODY_ROWS 3
#define LINE_HEIGHT 8
#define HISTORY_Y 34
#define EFFECTS_Y 45
#define EFFECTS_PER_ROW 4
#define EFFECT_PITCH_X 32
#define EFFECT_PITCH_Y 10
#define EFFECT_BOX_WIDTH 31
#define EFFECT_BOX_HEIGHT 9

static void set_pixel(at_screen_t *screen, unsigned x, unsigned y, int lit)
{
    if (x < AT_SCREEN_WIDTH && y < AT_SCREEN_HEIGHT) {
        uint8_t mask = (uint8_t)(1u << (y % 8u));
        if (lit) {
            screen->page[y / 8u][x] |= mask;
        } else {
            screen->page[y / 8u][x] &= (uint8_t)~mask;
        }
    }
}

static void fill(at_screen_t *screen, unsigned left, unsigned top, unsigned width, unsigned height)
{
    unsigned x, y;
    for (y = top; y < top + height; y++) {
        for (x = left; x < left + width; x++) {
            set_pixel(screen, x, y, 1);
        }
    }
}

/* Draw one character with its top-left pixel at (x, y). Dark on a filled area when `inverted`. */
static void put_character(at_screen_t *screen, unsigned x, unsigned y, char character, int inverted)
{
    unsigned glyph = (unsigned)(unsigned char)character - AT_FONT_FIRST, column, row;

    if (glyph >= AT_FONT_COUNT) {
        glyph = (unsigned)'?' - AT_FONT_FIRST;
    }
    for (column = 0; column < 5; column++) {
        for (row = 0; row < 7; row++) {
            if ((AT_FONT[glyph][column] >> row) & 1u) {
                set_pixel(screen, x + column, y + row, !inverted);
            }
        }
    }
}

/* Draw text from a character column of the line at `y` and return the column after it. */
static unsigned put_text(at_screen_t *screen, unsigned y, unsigned column, const char *text, int inverted)
{
    for (; *text != '\0' && column < COLUMNS; text++) {
        put_character(screen, LEFT + PITCH * column++, y, *text, inverted);
    }
    return column;
}

/* Write a number in decimal, followed by `suffix`, into `text` (at least 12 + strlen(suffix) bytes). */
static void format_number(char *text, unsigned value, const char *suffix)
{
    char digits[11];
    unsigned count = 0;

    do {
        digits[count++] = (char)('0' + value % 10u);
        value /= 10u;
    } while (value != 0u);
    while (count > 0) {
        *text++ = digits[--count];
    }
    strcpy(text, suffix);
}

static unsigned put_number(at_screen_t *screen, unsigned y, unsigned column, unsigned value)
{
    char text[12];
    format_number(text, value, "");
    return put_text(screen, y, column, text, 0);
}

static unsigned digits_in(unsigned value)
{
    unsigned count = 1;
    for (; value >= 10u; value /= 10u) {
        count++;
    }
    return count;
}

/* One mechanism set as "<number><mark>TAG+TAG", wrapped after a "+" with two-space indents.
 * Returns the lines it needs. Nothing is drawn when `draw` is 0. */
static unsigned explanation(at_screen_t *screen, unsigned line, unsigned number, char mark, uint8_t roots, int draw)
{
    char text[2] = {mark, '\0'};
    unsigned lines = 1, column, root, remaining = 0;

    for (root = 0; root < AT_ROOT_COUNT; root++) {
        remaining += (roots >> root) & 1u;
    }
    column = digits_in(number) + 1;
    if (draw) {
        put_text(screen, BODY_Y + LINE_HEIGHT * line, put_number(screen, BODY_Y + LINE_HEIGHT * line, 0, number),
                 text, 0);
    }
    for (root = 0; root < AT_ROOT_COUNT; root++) {
        unsigned length;
        if (!((roots >> root) & 1u)) {
            continue;
        }
        remaining--;
        length = (unsigned)strlen(AT_ROOT_TAG[root]) + (remaining ? 1u : 0u);
        if (column + length > COLUMNS) {
            lines++;
            line++;
            column = 2;
        }
        if (draw) {
            unsigned end = put_text(screen, BODY_Y + LINE_HEIGHT * line, column, AT_ROOT_TAG[root], 0);
            if (remaining) {
                put_text(screen, BODY_Y + LINE_HEIGHT * line, end, "+", 0);
            }
        }
        column += length;
    }
    return lines;
}

static unsigned count_sets(uint32_t sets)
{
    unsigned index, count = 0;
    for (index = 0; index < AT_SET_COUNT; index++) {
        count += (sets >> index) & 1u;
    }
    return count;
}

/* List the mechanism sets in `sets`. With `held` every set is marked "?", otherwise only the
 * sets without a compatible onset history. */
static void draw_causes(at_screen_t *screen, const at_result_t *result, uint32_t sets, int held)
{
    unsigned set, shown = 0, line = 0, count = count_sets(sets);

    for (set = 0; set < AT_SET_COUNT; set++) {
        char mark;
        unsigned lines;
        if (!((sets >> set) & 1u)) {
            continue;
        }
        mark = !held && result->set[set].history_count[AT_COMPATIBLE] ? ' ' : '?';
        lines = explanation(screen, line, shown + 1, mark, AT_SET_ROOTS[set], 0);
        /* Keep one line free for "+N MORE" unless this is the last set. */
        if (line + lines + (count - shown - 1 ? 1u : 0u) > BODY_ROWS) {
            unsigned y = BODY_Y + LINE_HEIGHT * line;
            put_text(screen, y, put_number(screen, y, put_text(screen, y, 0, "+", 0), count - shown), " MORE", 0);
            return;
        }
        explanation(screen, line, shown + 1, mark, AT_SET_ROOTS[set], 1);
        line += lines;
        shown++;
    }
}

void at_screen_hold_reset(at_screen_hold_t *hold)
{
    memset(hold, 0, sizeof *hold);
}

uint32_t at_screen_hold_update(at_screen_hold_t *hold, const at_result_t *result, int has_time, double sim_time_s)
{
    if (result->minimal_sets != 0u) {
        /* Set 0 alone means no fault; there is then nothing to hold. */
        hold->sets = result->minimal_sets > 1u ? result->minimal_sets : 0u;
        hold->waiting = 0;
        return 0u;
    }
    if (hold->sets != 0u && has_time) {
        if (!hold->waiting) {
            hold->waiting = 1;
            hold->since_s = sim_time_s;
        }
        if (sim_time_s >= hold->since_s && sim_time_s - hold->since_s <= AT_SCREEN_HOLD_SIM_S) {
            return hold->sets;
        }
    }
    at_screen_hold_reset(hold);
    return 0u;
}

void at_screen_draw(at_screen_t *screen, const at_frame_t *frame, const at_result_t *result)
{
    at_screen_draw_held(screen, frame, result, 0u);
}

void at_screen_draw_held(at_screen_t *screen, const at_frame_t *frame, const at_result_t *result,
                         uint32_t held_sets)
{
    const char *state = "NO DATA";
    char causes[24];
    unsigned index, column, count = 0, unread = 0;

    memset(screen, 0, sizeof *screen);
    if (frame == NULL || result == NULL) {
        put_text(screen, BODY_Y, 0, "WAITING FOR AIRBORNE", 0);
        put_text(screen, BODY_Y + LINE_HEIGHT, 0, "TELEMETRY", 0);
    } else {
        count = count_sets(result->minimal_sets);
        for (index = 0; index < AT_FACT_COUNT; index++) {
            unread += frame->fact[index].state == AT_STATE_UNKNOWN;
        }
        if (count == 0 && held_sets != 0u) {
            state = "CHECKING";
            draw_causes(screen, result, held_sets, 1);
        } else if (count == 0) {
            state = "NO FIT";
            put_text(screen, BODY_Y, 0, "NO MODELLED CAUSE", 0);
            put_text(screen, BODY_Y + LINE_HEIGHT, 0, "FITS THE READINGS", 0);
        } else if (result->minimal_sets == 1u) {
            /* Set 0 has no mechanism. It is a subset of every other set, so it is minimal alone. */
            state = "NO FAULT";
            put_text(screen, BODY_Y, 0, "NO SELECTED FAULT", 0);
            if (unread) {
                column = put_text(screen, BODY_Y + LINE_HEIGHT, put_number(screen, BODY_Y + LINE_HEIGHT, 0, unread),
                                  " OF ", 0);
                put_text(screen, BODY_Y + LINE_HEIGHT, put_number(screen, BODY_Y + LINE_HEIGHT, column, AT_FACT_COUNT),
                         " UNREAD", 0);
            } else {
                put_text(screen, BODY_Y + LINE_HEIGHT, 0, "ALL CHANNELS READ", 0);
            }
        } else {
            format_number(causes, count, count > 1u ? " CAUSES" : " CAUSE");
            state = causes;
            draw_causes(screen, result, result->minimal_sets, 0);
        }
        column = put_text(screen, HISTORY_Y, 0, "HIST C:", 0);
        column = put_text(screen, HISTORY_Y, put_number(screen, HISTORY_Y, column, result->history_count[AT_COMPATIBLE]),
                          " U:", 0);
        column = put_number(screen, HISTORY_Y, column, result->history_count[AT_UNCONFIRMED]);
        if (result->unique_history >= 0) {
            put_text(screen, HISTORY_Y, column, " UNIQUE", 0);
        }
    }

    fill(screen, 0, 0, AT_SCREEN_WIDTH, HEADER_HEIGHT);
    put_text(screen, HEADER_TEXT_Y, 0, "AEROTRACE", 1);
    put_text(screen, HEADER_TEXT_Y, COLUMNS - (unsigned)strlen(state), state, 1);

    for (index = 0; index < AT_FACT_COUNT; index++) {
        unsigned left = EFFECT_PITCH_X * (index % EFFECTS_PER_ROW);
        unsigned top = EFFECTS_Y + EFFECT_PITCH_Y * (index / EFFECTS_PER_ROW);
        unsigned fact_state = frame == NULL || result == NULL ? (unsigned)AT_STATE_UNKNOWN : frame->fact[index].state;
        int observed = fact_state == AT_STATE_OBSERVED;
        const char *tag = AT_FACT_TAG[index];
        unsigned x = left + 2;

        if (observed) {
            fill(screen, left, top, EFFECT_BOX_WIDTH, EFFECT_BOX_HEIGHT);
        }
        for (; *tag != '\0'; tag++, x += PITCH) {
            put_character(screen, x, top + 1, *tag, observed);
        }
        if (fact_state == AT_STATE_UNKNOWN) {
            put_character(screen, x, top + 1, '?', 0);
        }
    }
}
