/* PC harness for the embedded core. Numbers are read as C99 hexadecimal floats so they round-trip exactly.
 *
 * at_replay <cases.txt> fits ready-made evidence frames, one result line per case:
 *   case <name>
 *   b <root> <fact> <minimum_s> <maximum_s>
 *   f <fact> <state> <has_lower> <covered> <lower_s> <upper_s>
 *   r <relation> <status> <has_witness> <witness_s>
 *   end
 *
 * at_replay --stream <polls.txt> extracts the frame from telemetry polls and fits it after every poll:
 *   stream <name>
 *   b <root> <fact> <minimum_s> <maximum_s>
 *   s <sample_index> <received_s> <connected> <base_connected> <startup_capture>
 *   c <channel> <valid> <reachable> <has_time> <value> <sim_time_s> <received_s>
 *   go
 */
#define _CRT_SECURE_NO_WARNINGS

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "aerotrace_extract.h"

static at_frame_t frame;
static at_bounds_t bounds;
static at_result_t result;
static at_extractor_t extractor;
static at_sample_t sample;

static void reset_case(void)
{
    unsigned index;
    memset(&frame, 0, sizeof frame);
    memset(&bounds, 0, sizeof bounds);
    for (index = 0; index < AT_FACT_COUNT; index++) {
        frame.fact[index].state = AT_STATE_UNKNOWN;
    }
    for (index = 0; index < AT_RELATION_COUNT; index++) {
        frame.relation[index].status = AT_CHECK_UNKNOWN;
    }
}

static void print_bits(double value)
{
    unsigned long long bits = 0;
    memcpy(&bits, &value, sizeof value);
    printf("%016llx", bits);
}

static void print_frame(void)
{
    unsigned index;
    for (index = 0; index < AT_FACT_COUNT; index++) {
        const at_fact_t *fact = &frame.fact[index];
        printf("%s%u:%u:%u:", index ? "," : "", (unsigned)fact->state, (unsigned)fact->has_lower,
               (unsigned)fact->covered);
        print_bits(fact->lower_s);
        putchar(':');
        print_bits(fact->upper_s);
    }
    putchar(' ');
    for (index = 0; index < AT_RELATION_COUNT; index++) {
        const at_relation_t *relation = &frame.relation[index];
        printf("%s%u:%u:", index ? "," : "", (unsigned)relation->status, (unsigned)relation->has_witness);
        print_bits(relation->witness_s);
    }
}

static void print_fit(int status)
{
    static const char codes[] = "CUDT";
    unsigned index;

    printf("%d ", status);
    if (status != AT_OK) {
        putchar('\n');
        return;
    }
    for (index = 0; index < AT_SET_COUNT; index++) {
        putchar(codes[result.set[index].dependency_status]);
    }
    putchar(' ');
    for (index = 0; index < AT_HISTORY_COUNT; index++) {
        putchar(codes[result.history_status[index]]);
    }
    printf(" %08lx %d", (unsigned long)result.minimal_sets, (int)result.unique_history);
    for (index = 0; index < AT_STATUS_COUNT; index++) {
        printf(" %u", (unsigned)result.history_count[index]);
    }
    putchar(' ');
    for (index = 0; index < AT_SET_COUNT; index++) {
        const at_set_result_t *fit = &result.set[index];
        printf("%s%d:%u:%u:%u:%u", index ? "," : "", (int)fit->support_percent, (unsigned)fit->supported_checks,
               (unsigned)fit->total_checks, (unsigned)fit->unconfirmed_checks, (unsigned)fit->contradicted_checks);
    }
    putchar('\n');
}

static int read_bound(const char *line)
{
    char text[2][64];
    unsigned root = 0, fact = 0;
    if (sscanf(line, "%*s %u %u %63s %63s", &root, &fact, text[0], text[1]) != 4
            || root >= AT_ROOT_COUNT || fact >= AT_FACT_COUNT) {
        return 0;
    }
    bounds.bound[root][fact].declared = 1;
    bounds.bound[root][fact].minimum_s = strtod(text[0], NULL);
    bounds.bound[root][fact].maximum_s = strtod(text[1], NULL);
    return 1;
}

static int read_case_line(const char *kind, const char *line, char *name)
{
    char text[2][64];
    unsigned a = 0, b = 0, c = 0, d = 0;
    if (strcmp(kind, "case") == 0) {
        reset_case();
        return sscanf(line, "%*s %127s", name) == 1;
    }
    if (strcmp(kind, "f") == 0) {
        if (sscanf(line, "%*s %u %u %u %u %63s %63s", &a, &b, &c, &d, text[0], text[1]) != 6 || a >= AT_FACT_COUNT) {
            return 0;
        }
        frame.fact[a].state = (uint8_t)b;
        frame.fact[a].has_lower = (uint8_t)c;
        frame.fact[a].covered = (uint8_t)d;
        frame.fact[a].lower_s = strtod(text[0], NULL);
        frame.fact[a].upper_s = strtod(text[1], NULL);
        return 1;
    }
    if (strcmp(kind, "r") == 0) {
        if (sscanf(line, "%*s %u %u %u %63s", &a, &b, &c, text[0]) != 4 || a >= AT_RELATION_COUNT) {
            return 0;
        }
        frame.relation[a].status = (uint8_t)b;
        frame.relation[a].has_witness = (uint8_t)c;
        frame.relation[a].witness_s = strtod(text[0], NULL);
        return 1;
    }
    if (strcmp(kind, "end") == 0) {
        printf("%s ", name);
        print_fit(at_fit(&frame, &bounds, &result));
        return 1;
    }
    return 0;
}

static int read_stream_line(const char *kind, const char *line)
{
    char text[3][64];
    unsigned a = 0, b = 0, c = 0, d = 0;
    if (strcmp(kind, "stream") == 0) {
        at_extract_init(&extractor);
        memset(&bounds, 0, sizeof bounds);
        memset(&sample, 0, sizeof sample);
        return 1;
    }
    if (strcmp(kind, "s") == 0) {
        memset(&sample, 0, sizeof sample);
        if (sscanf(line, "%*s %u %63s %u %u %u", &a, text[0], &b, &c, &d) != 5) {
            return 0;
        }
        sample.sample_index = a;
        sample.received_s = strtod(text[0], NULL);
        sample.connected = (uint8_t)b;
        sample.base_connected = (uint8_t)c;
        sample.startup_capture = (uint8_t)d;
        return 1;
    }
    if (strcmp(kind, "c") == 0) {
        at_reading_t *reading;
        if (sscanf(line, "%*s %u %u %u %u %63s %63s %63s", &a, &b, &c, &d, text[0], text[1], text[2]) != 7
                || a >= AT_CHANNEL_COUNT) {
            return 0;
        }
        reading = &sample.reading[a];
        reading->present = 1;
        reading->valid = (uint8_t)b;
        reading->reachable = (uint8_t)c;
        reading->has_time = (uint8_t)d;
        reading->value = strtod(text[0], NULL);
        reading->sim_time_s = strtod(text[1], NULL);
        reading->received_s = strtod(text[2], NULL);
        return 1;
    }
    if (strcmp(kind, "go") == 0) {
        int status = at_extract_push(&extractor, &sample);
        printf("%lu %d ", (unsigned long)sample.sample_index, status);
        if (status != AT_OK || !at_extract_frame(&extractor, &frame)) {
            printf("none\n");
            return 1;
        }
        print_frame();
        putchar(' ');
        print_fit(at_fit(&frame, &bounds, &result));
        return 1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    char line[256], name[128] = "";
    int stream = argc == 3 && strcmp(argv[1], "--stream") == 0;
    int failed = 0;
    FILE *input;

    if (argc != 2 && !stream) {
        fprintf(stderr, "usage: at_replay [--stream] <file>\n");
        return 2;
    }
    input = fopen(argv[argc - 1], "r");
    if (input == NULL) {
        fprintf(stderr, "cannot open %s\n", argv[argc - 1]);
        return 2;
    }
    reset_case();
    at_extract_init(&extractor);
    while (fgets(line, sizeof line, input)) {
        char kind[8] = "";
        if (sscanf(line, "%7s", kind) != 1) {
            continue;
        }
        if (strcmp(kind, "b") == 0) {
            failed |= !read_bound(line);
        } else if (stream) {
            failed |= !read_stream_line(kind, line);
        } else {
            failed |= !read_case_line(kind, line, name);
        }
    }
    fclose(input);
    if (failed) {
        fprintf(stderr, "malformed input file\n");
        return 2;
    }
    return 0;
}
