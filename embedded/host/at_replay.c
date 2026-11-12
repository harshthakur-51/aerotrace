/* PC harness: read evidence frames as text, fit them with the embedded core, print one result line per case.
 *
 * Input records (numbers are C99 hexadecimal floats so they round-trip exactly):
 *   case <name>
 *   b <root> <fact> <minimum_s> <maximum_s>
 *   f <fact> <state> <has_lower> <covered> <lower_s> <upper_s>
 *   r <relation> <status> <has_witness> <witness_s>
 *   end
 */
#define _CRT_SECURE_NO_WARNINGS

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "aerotrace_core.h"

static at_frame_t frame;
static at_bounds_t bounds;
static at_result_t result;

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

static void print_result(const char *name, int status)
{
    static const char codes[] = "CUDT";
    unsigned index;

    printf("%s %d ", name, status);
    if (status != AT_OK) {
        printf("\n");
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

int main(int argc, char **argv)
{
    char line[256], name[128] = "";
    FILE *input;
    int failed = 0;

    if (argc != 2) {
        fprintf(stderr, "usage: at_replay <cases.txt>\n");
        return 2;
    }
    input = fopen(argv[1], "r");
    if (input == NULL) {
        fprintf(stderr, "cannot open %s\n", argv[1]);
        return 2;
    }
    reset_case();
    while (fgets(line, sizeof line, input)) {
        char kind[8] = "", text[4][64] = {"", "", "", ""};
        unsigned a = 0, b = 0, c = 0;
        if (sscanf(line, "%7s", kind) != 1) {
            continue;
        }
        if (strcmp(kind, "case") == 0) {
            reset_case();
            if (sscanf(line, "%*s %127s", name) != 1) {
                failed = 1;
            }
        } else if (strcmp(kind, "b") == 0) {
            if (sscanf(line, "%*s %u %u %63s %63s", &a, &b, text[0], text[1]) != 4
                    || a >= AT_ROOT_COUNT || b >= AT_FACT_COUNT) {
                failed = 1;
                continue;
            }
            bounds.bound[a][b].declared = 1;
            bounds.bound[a][b].minimum_s = strtod(text[0], NULL);
            bounds.bound[a][b].maximum_s = strtod(text[1], NULL);
        } else if (strcmp(kind, "f") == 0) {
            unsigned state = 0;
            if (sscanf(line, "%*s %u %u %u %u %63s %63s", &a, &state, &b, &c, text[0], text[1]) != 6
                    || a >= AT_FACT_COUNT) {
                failed = 1;
                continue;
            }
            frame.fact[a].state = (uint8_t)state;
            frame.fact[a].has_lower = (uint8_t)b;
            frame.fact[a].covered = (uint8_t)c;
            frame.fact[a].lower_s = strtod(text[0], NULL);
            frame.fact[a].upper_s = strtod(text[1], NULL);
        } else if (strcmp(kind, "r") == 0) {
            unsigned relation_status = 0;
            if (sscanf(line, "%*s %u %u %u %63s", &a, &relation_status, &b, text[0]) != 4
                    || a >= AT_RELATION_COUNT) {
                failed = 1;
                continue;
            }
            frame.relation[a].status = (uint8_t)relation_status;
            frame.relation[a].has_witness = (uint8_t)b;
            frame.relation[a].witness_s = strtod(text[0], NULL);
        } else if (strcmp(kind, "end") == 0) {
            print_result(name, at_fit(&frame, &bounds, &result));
        } else {
            failed = 1;
        }
    }
    fclose(input);
    if (failed) {
        fprintf(stderr, "malformed case file\n");
        return 2;
    }
    return 0;
}
