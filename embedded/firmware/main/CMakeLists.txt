idf_component_register(
    SRCS
        "main.c"
        "../../link/at_text_link.c"
        "../../core/aerotrace_core.c"
        "../../core/aerotrace_extract.c"
        "../../core/aerotrace_model.c"
    INCLUDE_DIRS "../../core" "../../link"
    PRIV_REQUIRES esp_driver_uart esp_timer
)
