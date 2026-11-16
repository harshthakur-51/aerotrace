/* PC harness: feed text-link lines to the embedded core and print its replies.
 * The line format is described in embedded/link/at_text_link.h.
 *
 *   at_replay [--timed] <file>   read a file of lines
 *   at_replay [--timed] -        read standard input and reply after every line, as a board does
 *
 * --timed adds the "t" timing lines that the firmware sends.
 */
#define _CRT_SECURE_NO_WARNINGS

#include <stdio.h>
#include <string.h>
#include <time.h>

#include "at_text_link.h"

static at_text_link_t text_link;

static uint64_t processor_time_us(void)
{
    return (uint64_t)clock() * 1000000u / (uint64_t)CLOCKS_PER_SEC;
}

int main(int argc, char **argv)
{
    char line[AT_TEXT_LINK_MAX_LINE];
    int timed = argc == 3 && strcmp(argv[1], "--timed") == 0;
    int interactive, failed = 0;
    FILE *input = stdin;

    if (argc != 2 && !timed) {
        fprintf(stderr, "usage: at_replay [--timed] <file or ->\n");
        return 2;
    }
    interactive = strcmp(argv[argc - 1], "-") == 0;
    if (!interactive) {
        input = fopen(argv[argc - 1], "r");
        if (input == NULL) {
            fprintf(stderr, "cannot open %s\n", argv[argc - 1]);
            return 2;
        }
    }
    at_text_link_init(&text_link, timed ? processor_time_us : NULL);
    while (fgets(line, sizeof line, input)) {
        if (at_text_link_line(&text_link, line, stdout) != 0) {
            printf("error malformed line\n");
            failed = 1;
        }
        if (interactive) {
            fflush(stdout);
        }
    }
    if (!interactive) {
        fclose(input);
    }
    if (failed) {
        fprintf(stderr, "malformed input\n");
        return 2;
    }
    return 0;
}
