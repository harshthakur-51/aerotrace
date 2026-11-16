idf_component_register(
    SRCS
        "main.c"
        "../../link/at_text_link.c"
        "../../display/at_screen.c"
        "../../core/aerotrace_core.c"
        "../../core/aerotrace_extract.c"
        "../../core/aerotrace_model.c"
    INCLUDE_DIRS "../../core" "../../link" "../../display"
    PRIV_REQUIRES esp_driver_uart esp_driver_usb_serial_jtag esp_timer
)
