/* AeroTrace firmware: serve the text link of embedded/link/at_text_link.h on the console UART.
 *
 * The PC sends one line at a time and reads the reply to `go` or `end` before it sends the
 * next poll, so the receive buffer only ever holds one poll.
 */
#include <stdio.h>

#include "driver/uart.h"
#include "driver/uart_vfs.h"
#include "esp_timer.h"
#include "sdkconfig.h"

#include "at_text_link.h"

#define RECEIVE_BUFFER_BYTES 4096

static at_text_link_t text_link;

static uint64_t now_us(void)
{
    return (uint64_t)esp_timer_get_time();
}

void app_main(void)
{
    char line[AT_TEXT_LINK_MAX_LINE];

    /* The interrupt-driven driver makes reads from stdin block until a line arrives. */
    setvbuf(stdin, NULL, _IONBF, 0);
    ESP_ERROR_CHECK(uart_driver_install(CONFIG_ESP_CONSOLE_UART_NUM, RECEIVE_BUFFER_BYTES, 0, 0, NULL, 0));
    uart_vfs_dev_use_driver(CONFIG_ESP_CONSOLE_UART_NUM);

    at_text_link_init(&text_link, now_us);
    at_text_link_line(&text_link, "hello", stdout);
    fflush(stdout);
    while (fgets(line, sizeof line, stdin) != NULL) {
        if (at_text_link_line(&text_link, line, stdout) != 0) {
            printf("error malformed line\n");
        }
        fflush(stdout);
    }
}
