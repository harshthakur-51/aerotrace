/* Line-based text link to the AeroTrace embedded core.
 *
 * The PC harness and the firmware both feed received lines to at_text_link_line() and
 * print its replies, so a board is exercised with exactly the input the PC tests use.
 * Numbers are C99 hexadecimal floats (for example 0x1.9p+6), which convert exactly.
 *
 * Fit a ready-made evidence frame. `end` replies "<name> <fit>":
 *   case <name>
 *   b <root> <fact> <minimum_s> <maximum_s>
 *   f <fact> <state> <has_lower> <covered> <lower_s> <upper_s>
 *   r <relation> <status> <has_witness> <witness_s>
 *   end
 *
 * Extract the frame from telemetry polls. `go` replies "<sample_index> <status> <frame> <fit>",
 * or "<sample_index> <status> none" while no airborne poll has been kept:
 *   stream <name>
 *   b <root> <fact> <minimum_s> <maximum_s>
 *   s <sample_index> <received_s> <connected> <base_connected> <startup_capture>
 *   c <channel> <valid> <reachable> <has_time> <value> <sim_time_s> <received_s>
 *   go
 *
 * `screen` replies "screen <hex>": the 1024 bytes of the screen for the latest fit, page by page
 * (see embedded/display/at_screen.h). In a telemetry stream the screen holds the previous explanation
 * through a short gap in which nothing fits; the `go` reply always carries the fit itself.
 *
 * `hello` replies "aerotrace <model id> ready". With a clock the reply ends in " timed", and
 * each `go` and `end` reply is followed by "t <extract_us> <fit_us>", the microseconds spent
 * in the core. The caller reports a malformed line as "error malformed line".
 */
#ifndef AT_TEXT_LINK_H
#define AT_TEXT_LINK_H

#include <stdint.h>
#include <stdio.h>

#include "aerotrace_extract.h"
#include "at_screen.h"

#ifdef __cplusplus
extern "C" {
#endif

#define AT_TEXT_LINK_MAX_LINE 256

typedef uint64_t (*at_text_link_clock_t)(void);

typedef struct {
    at_text_link_clock_t now_us;
    uint8_t fitted; /* the frame and result hold a successful fit */
    char name[64];
    at_frame_t frame;
    at_bounds_t bounds;
    at_result_t result;
    at_extractor_t extractor;
    at_sample_t sample;
    at_screen_t screen;
    at_screen_hold_t hold;
    uint32_t held_sets; /* sets the screen holds through a gap in a telemetry stream, or 0 */
} at_text_link_t;

/* now_us may be NULL when no timing is wanted. */
void at_text_link_init(at_text_link_t *link, at_text_link_clock_t now_us);

/* Handle one received line and print any reply to `out`. Returns 0, or -1 for a malformed line. */
int at_text_link_line(at_text_link_t *link, const char *line, FILE *out);

#ifdef __cplusplus
}
#endif

#endif
