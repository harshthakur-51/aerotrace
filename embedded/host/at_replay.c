/* PC harness: feed a file of text-link lines to the embedded core and print its replies.
 * The line format is described in embedded/link/at_text_link.h. */
#define _CRT_SECURE_NO_WARNINGS

#include <stdio.h>

#include "at_text_link.h"

static at_text_link_t text_link;

int main(int argc, char **argv)
{
    char line[AT_TEXT_LINK_MAX_LINE];
    int failed = 0;
    FILE *input;

    if (argc != 2) {
        fprintf(stderr, "usage: at_replay <file>\n");
        return 2;
    }
    input = fopen(argv[1], "r");
    if (input == NULL) {
        fprintf(stderr, "cannot open %s\n", argv[1]);
        return 2;
    }
    at_text_link_init(&text_link, NULL);
    while (fgets(line, sizeof line, input)) {
        if (at_text_link_line(&text_link, line, stdout) != 0) {
            failed = 1;
        }
    }
    fclose(input);
    if (failed) {
        fprintf(stderr, "malformed input file\n");
        return 2;
    }
    return 0;
}
