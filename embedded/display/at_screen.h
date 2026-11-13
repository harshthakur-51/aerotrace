/* AeroTrace screen: draw the diagnosis into a 128 x 64 monochrome frame buffer.
 *
 * Portable C99, no heap and no I/O. The buffer uses the SSD1306 page layout, so a board can
 * send it to the display unchanged: page[p][x] holds pixels y = 8p to 8p + 7 of column x,
 * bit 0 at the top. Text is 21 characters wide in a 5 x 7 font on a 6-pixel pitch.
 *
 *   y  0- 8  inverted bar: AEROTRACE and the overall state
 *   y 10-32  three lines: the smallest mechanism sets that fit, numbered, "?" when unconfirmed
 *   y 34-40  how many onset histories are compatible (C) and unconfirmed (U)
 *   y 45-63  the eight effects in fixed cells: boxed when observed, "?" when unread
 *
 * aircraft_debugger/screen.py holds the font, the labels and a Python reference of this layout.
 */
#ifndef AT_SCREEN_H
#define AT_SCREEN_H

#include <stdint.h>

#include "aerotrace_core.h"

#ifdef __cplusplus
extern "C" {
#endif

#define AT_SCREEN_WIDTH 128
#define AT_SCREEN_HEIGHT 64
#define AT_SCREEN_PAGES (AT_SCREEN_HEIGHT / 8)

typedef struct {
    uint8_t page[AT_SCREEN_PAGES][AT_SCREEN_WIDTH];
} at_screen_t;

/* Pass NULL for frame and result while there is no fitted evidence frame. */
void at_screen_draw(at_screen_t *screen, const at_frame_t *frame, const at_result_t *result);

#ifdef __cplusplus
}
#endif

#endif
