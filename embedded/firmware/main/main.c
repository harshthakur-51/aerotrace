/* AeroTrace firmware: serve the text link of embedded/link/at_text_link.h on the console.
 *
 * The console is the UART by default, or the chip's USB Serial/JTAG port when the build adds
 * sdkconfig.defaults.usbjtag. The PC sends one line at a time and reads the reply to `go` or
 * `end` before it sends the next poll, so the receive buffer only ever holds one poll.
 */
#include <stdio.h>

#include "esp_err.h"
#include "esp_timer.h"
#include "sdkconfig.h"

#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#else
#include "driver/uart.h"
#include "driver/uart_vfs.h"
#endif

#include "at_text_link.h"

#define RECEIVE_BUFFER_BYTES 4096

static at_text_link_t text_link;

static uint64_t now_us(void)
{
    return (uint64_t)esp_timer_get_time();
}

/* Install the interrupt-driven driver, which makes reads from stdin block until a line arrives. */
static void use_blocking_console(void)
{
    setvbuf(stdin, NULL, _IONBF, 0);
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
    usb_serial_jtag_driver_config_t config = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
    config.rx_buffer_size = RECEIVE_BUFFER_BYTES;
    config.tx_buffer_size = RECEIVE_BUFFER_BYTES;
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&config));
    usb_serial_jtag_vfs_use_driver();
#else
    ESP_ERROR_CHECK(uart_driver_install(CONFIG_ESP_CONSOLE_UART_NUM, RECEIVE_BUFFER_BYTES, 0, 0, NULL, 0));
    uart_vfs_dev_use_driver(CONFIG_ESP_CONSOLE_UART_NUM);
#endif
}

void app_main(void)
{
    char line[AT_TEXT_LINK_MAX_LINE];

    use_blocking_console();
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
