#define _CRT_SECURE_NO_WARNINGS

#include "at_text_link.h"

#include <math.h>
#include <string.h>

#define MAX_FIELDS 8

static int hex_digit(char character)
{
    if (character >= '0' && character <= '9') {
        return character - '0';
    }
    if (character >= 'a' && character <= 'f') {
        return character - 'a' + 10;
    }
    return character >= 'A' && character <= 'F' ? character - 'A' + 10 : -1;
}

/* Parse [-]0x<hex>[.<hex>]p<exponent> exactly. The C library's strtod is avoided so that
 * every platform converts the same text to the same double. */
static int parse_double(const char *text, double *value)
{
    uint64_t mantissa = 0;
    int negative = 0, digits = 0, fraction_digits = 0, exponent = 0, exponent_sign = 1, seen_point = 0;

    if (*text == '-') {
        negative = 1;
        text++;
    }
    if (text[0] != '0' || (text[1] != 'x' && text[1] != 'X')) {
        return 0;
    }
    for (text += 2; *text == '.' || hex_digit(*text) >= 0; text++) {
        if (*text == '.') {
            if (seen_point) {
                return 0;
            }
            seen_point = 1;
            continue;
        }
        if (++digits > 15) {
            return 0; /* more digits than a double's 53-bit mantissa needs */
        }
        mantissa = mantissa * 16u + (uint64_t)hex_digit(*text);
        fraction_digits += seen_point;
    }
    if (digits == 0 || (*text != 'p' && *text != 'P')) {
        return 0;
    }
    text++;
    if (*text == '+' || *text == '-') {
        exponent_sign = *text == '-' ? -1 : 1;
        text++;
    }
    if (*text < '0' || *text > '9') {
        return 0;
    }
    for (; *text >= '0' && *text <= '9'; text++) {
        exponent = exponent * 10 + (*text - '0');
        if (exponent > 2000) {
            return 0;
        }
    }
    if (*text != '\0') {
        return 0;
    }
    *value = ldexp((double)mantissa, exponent_sign * exponent - 4 * fraction_digits);
    if (negative) {
        *value = -*value;
    }
    return 1;
}

static int parse_unsigned(const char *text, uint32_t *value)
{
    uint64_t number = 0;
    if (*text == '\0') {
        return 0;
    }
    for (; *text != '\0'; text++) {
        if (*text < '0' || *text > '9') {
            return 0;
        }
        number = number * 10u + (uint64_t)(*text - '0');
        if (number > UINT32_MAX) {
            return 0;
        }
    }
    *value = (uint32_t)number;
    return 1;
}

/* Split a line into whitespace-separated fields in place. */
static unsigned split(char *line, char **field)
{
    unsigned count = 0;
    char *cursor = line;
    while (count < MAX_FIELDS) {
        while (*cursor == ' ' || *cursor == '\t' || *cursor == '\r' || *cursor == '\n') {
            cursor++;
        }
        if (*cursor == '\0') {
            break;
        }
        field[count++] = cursor;
        while (*cursor != '\0' && *cursor != ' ' && *cursor != '\t' && *cursor != '\r' && *cursor != '\n') {
            cursor++;
        }
        if (*cursor != '\0') {
            *cursor++ = '\0';
        }
    }
    return count;
}

static void reset_case(at_text_link_t *link)
{
    unsigned index;
    memset(&link->frame, 0, sizeof link->frame);
    memset(&link->bounds, 0, sizeof link->bounds);
    for (index = 0; index < AT_FACT_COUNT; index++) {
        link->frame.fact[index].state = AT_STATE_UNKNOWN;
    }
    for (index = 0; index < AT_RELATION_COUNT; index++) {
        link->frame.relation[index].status = AT_CHECK_UNKNOWN;
    }
}

void at_text_link_init(at_text_link_t *link, at_text_link_clock_t now_us)
{
    memset(link, 0, sizeof *link);
    link->now_us = now_us;
    reset_case(link);
    at_extract_init(&link->extractor);
}

static void print_bits(FILE *out, double value)
{
    uint64_t bits = 0;
    memcpy(&bits, &value, sizeof value);
    fprintf(out, "%08lx%08lx", (unsigned long)(bits >> 32), (unsigned long)(bits & 0xffffffffu));
}

static void print_frame(const at_frame_t *frame, FILE *out)
{
    unsigned index;
    for (index = 0; index < AT_FACT_COUNT; index++) {
        const at_fact_t *fact = &frame->fact[index];
        fprintf(out, "%s%u:%u:%u:", index ? "," : "", (unsigned)fact->state, (unsigned)fact->has_lower,
                (unsigned)fact->covered);
        print_bits(out, fact->lower_s);
        fputc(':', out);
        print_bits(out, fact->upper_s);
    }
    fputc(' ', out);
    for (index = 0; index < AT_RELATION_COUNT; index++) {
        const at_relation_t *relation = &frame->relation[index];
        fprintf(out, "%s%u:%u:", index ? "," : "", (unsigned)relation->status, (unsigned)relation->has_witness);
        print_bits(out, relation->witness_s);
    }
}

static void print_fit(const at_result_t *result, int status, FILE *out)
{
    static const char codes[] = "CUDT";
    unsigned index;

    fprintf(out, "%d ", status);
    if (status != AT_OK) {
        fputc('\n', out);
        return;
    }
    for (index = 0; index < AT_SET_COUNT; index++) {
        fputc(codes[result->set[index].dependency_status], out);
    }
    fputc(' ', out);
    for (index = 0; index < AT_HISTORY_COUNT; index++) {
        fputc(codes[result->history_status[index]], out);
    }
    fprintf(out, " %08lx %d", (unsigned long)result->minimal_sets, (int)result->unique_history);
    for (index = 0; index < AT_STATUS_COUNT; index++) {
        fprintf(out, " %u", (unsigned)result->history_count[index]);
    }
    fputc(' ', out);
    for (index = 0; index < AT_SET_COUNT; index++) {
        const at_set_result_t *fit = &result->set[index];
        fprintf(out, "%s%d:%u:%u:%u:%u", index ? "," : "", (int)fit->support_percent, (unsigned)fit->supported_checks,
                (unsigned)fit->total_checks, (unsigned)fit->unconfirmed_checks, (unsigned)fit->contradicted_checks);
    }
    fputc('\n', out);
}

static uint64_t now(const at_text_link_t *link)
{
    return link->now_us ? link->now_us() : 0;
}

static void print_timing(const at_text_link_t *link, uint64_t extract_us, uint64_t fit_us, FILE *out)
{
    if (link->now_us) {
        fprintf(out, "t %lu %lu\n", (unsigned long)extract_us, (unsigned long)fit_us);
    }
}

static void fit_and_print(at_text_link_t *link, uint64_t extract_us, FILE *out)
{
    uint64_t started = now(link);
    int status = at_fit(&link->frame, &link->bounds, &link->result);
    uint64_t fit_us = now(link) - started;
    print_fit(&link->result, status, out);
    print_timing(link, extract_us, fit_us, out);
}

static int handle(at_text_link_t *link, char **field, unsigned count, FILE *out)
{
    const char *kind = field[0];
    uint32_t number[4] = {0, 0, 0, 0};
    double real[3] = {0.0, 0.0, 0.0};
    unsigned index;

    if (strcmp(kind, "hello") == 0 && count == 1) {
        fprintf(out, "aerotrace %s ready%s\n", AT_MODEL_ID, link->now_us ? " timed" : "");
        return 0;
    }
    if (strcmp(kind, "case") == 0 && count == 2 && strlen(field[1]) < sizeof link->name) {
        reset_case(link);
        strcpy(link->name, field[1]);
        return 0;
    }
    if (strcmp(kind, "stream") == 0 && count == 2) {
        at_extract_init(&link->extractor);
        memset(&link->bounds, 0, sizeof link->bounds);
        memset(&link->sample, 0, sizeof link->sample);
        return 0;
    }
    if (strcmp(kind, "end") == 0 && count == 1) {
        fprintf(out, "%s ", link->name);
        fit_and_print(link, 0, out);
        return 0;
    }
    if (strcmp(kind, "go") == 0 && count == 1) {
        uint64_t started = now(link), extract_us;
        int status = at_extract_push(&link->extractor, &link->sample);
        int framed = status == AT_OK && at_extract_frame(&link->extractor, &link->frame);
        extract_us = now(link) - started;
        fprintf(out, "%lu %d ", (unsigned long)link->sample.sample_index, status);
        if (!framed) {
            fprintf(out, "none\n");
            print_timing(link, extract_us, 0, out);
            return 0;
        }
        print_frame(&link->frame, out);
        fputc(' ', out);
        fit_and_print(link, extract_us, out);
        return 0;
    }
    if (strcmp(kind, "b") == 0 && count == 5) {
        at_bound_t *bound;
        if (!parse_unsigned(field[1], &number[0]) || !parse_unsigned(field[2], &number[1])
                || !parse_double(field[3], &real[0]) || !parse_double(field[4], &real[1])
                || number[0] >= AT_ROOT_COUNT || number[1] >= AT_FACT_COUNT) {
            return -1;
        }
        bound = &link->bounds.bound[number[0]][number[1]];
        bound->declared = 1;
        bound->minimum_s = real[0];
        bound->maximum_s = real[1];
        return 0;
    }
    if (strcmp(kind, "f") == 0 && count == 7) {
        at_fact_t *fact;
        for (index = 0; index < 4; index++) {
            if (!parse_unsigned(field[1 + index], &number[index])) {
                return -1;
            }
        }
        if (!parse_double(field[5], &real[0]) || !parse_double(field[6], &real[1]) || number[0] >= AT_FACT_COUNT
                || number[1] > UINT8_MAX) {
            return -1;
        }
        fact = &link->frame.fact[number[0]];
        fact->state = (uint8_t)number[1];
        fact->has_lower = number[2] != 0;
        fact->covered = number[3] != 0;
        fact->lower_s = real[0];
        fact->upper_s = real[1];
        return 0;
    }
    if (strcmp(kind, "r") == 0 && count == 5) {
        at_relation_t *relation;
        for (index = 0; index < 3; index++) {
            if (!parse_unsigned(field[1 + index], &number[index])) {
                return -1;
            }
        }
        if (!parse_double(field[4], &real[0]) || number[0] >= AT_RELATION_COUNT || number[1] > UINT8_MAX) {
            return -1;
        }
        relation = &link->frame.relation[number[0]];
        relation->status = (uint8_t)number[1];
        relation->has_witness = number[2] != 0;
        relation->witness_s = real[0];
        return 0;
    }
    if (strcmp(kind, "s") == 0 && count == 6) {
        if (!parse_unsigned(field[1], &number[0]) || !parse_double(field[2], &real[0])) {
            return -1;
        }
        for (index = 0; index < 3; index++) {
            if (!parse_unsigned(field[3 + index], &number[1 + index])) {
                return -1;
            }
        }
        memset(&link->sample, 0, sizeof link->sample);
        link->sample.sample_index = number[0];
        link->sample.received_s = real[0];
        link->sample.connected = number[1] != 0;
        link->sample.base_connected = number[2] != 0;
        link->sample.startup_capture = number[3] != 0;
        return 0;
    }
    if (strcmp(kind, "c") == 0 && count == 8) {
        at_reading_t *reading;
        for (index = 0; index < 4; index++) {
            if (!parse_unsigned(field[1 + index], &number[index])) {
                return -1;
            }
        }
        for (index = 0; index < 3; index++) {
            if (!parse_double(field[5 + index], &real[index])) {
                return -1;
            }
        }
        if (number[0] >= AT_CHANNEL_COUNT) {
            return -1;
        }
        reading = &link->sample.reading[number[0]];
        reading->present = 1;
        reading->valid = number[1] != 0;
        reading->reachable = number[2] != 0;
        reading->has_time = number[3] != 0;
        reading->value = real[0];
        reading->sim_time_s = real[1];
        reading->received_s = real[2];
        return 0;
    }
    return -1;
}

int at_text_link_line(at_text_link_t *link, const char *line, FILE *out)
{
    char copy[AT_TEXT_LINK_MAX_LINE];
    char *field[MAX_FIELDS];
    size_t length = strlen(line);
    unsigned count;

    if (length >= sizeof copy) {
        return -1;
    }
    memcpy(copy, line, length + 1);
    count = split(copy, field);
    return count == 0 ? 0 : handle(link, field, count, out);
}
