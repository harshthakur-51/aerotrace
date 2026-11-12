/* AeroTrace embedded core: fit every mechanism set and onset history to one evidence frame.
 *
 * Portable C99. No heap, no I/O, no global state. Times are simulator seconds on one clock epoch.
 * The behaviour mirrors aircraft_debugger/sequence_reasoning.py::_fit_epoch.
 */
#ifndef AEROTRACE_CORE_H
#define AEROTRACE_CORE_H

#include <stdint.h>

#include "aerotrace_model.h"

#ifdef __cplusplus
extern "C" {
#endif

enum { AT_STATE_NOT_OBSERVED = 0, AT_STATE_OBSERVED = 1, AT_STATE_UNKNOWN = 2 };
enum { AT_CHECK_NOT_APPLICABLE = 0, AT_CHECK_UNKNOWN = 1, AT_CHECK_CONSISTENT = 2, AT_CHECK_CONTRADICTED = 3 };
enum { AT_COMPATIBLE = 0, AT_UNCONFIRMED = 1, AT_EXCLUDED_BY_DEPENDENCY = 2, AT_EXCLUDED_BY_TIMING = 3, AT_STATUS_COUNT = 4 };
enum { AT_OK = 0, AT_ERROR_FRAME = -1, AT_ERROR_BOUNDS = -2 };

/* One observable effect over the clock epoch. The onset bracket runs from the last
 * usable normal reading (lower) to the first qualifying abnormal reading (upper). */
typedef struct {
    uint8_t state;
    uint8_t has_lower;
    uint8_t covered;
    double lower_s;
    double upper_s;
} at_fact_t;

/* witness_s is the earliest source-loss reading taken with engine drive retained. */
typedef struct {
    uint8_t status;
    uint8_t has_witness;
    double witness_s;
} at_relation_t;

typedef struct {
    at_fact_t fact[AT_FACT_COUNT];
    at_relation_t relation[AT_RELATION_COUNT];
} at_frame_t;

/* Declared response delay from a mechanism onset to one required effect. */
typedef struct {
    uint8_t declared;
    double minimum_s;
    double maximum_s;
} at_bound_t;

typedef struct {
    at_bound_t bound[AT_ROOT_COUNT][AT_FACT_COUNT];
} at_bounds_t;

typedef struct {
    uint8_t dependency_status;
    int8_t support_percent; /* -1 when a check is contradicted or none applies */
    uint8_t supported_checks;
    uint8_t total_checks;
    uint8_t unconfirmed_checks;
    uint8_t contradicted_checks;
    uint16_t history_count[AT_STATUS_COUNT];
} at_set_result_t;

typedef struct {
    at_set_result_t set[AT_SET_COUNT];
    uint8_t history_status[AT_HISTORY_COUNT];
    uint16_t history_count[AT_STATUS_COUNT];
    uint32_t minimal_sets;  /* bit i is set when mechanism set i is a minimal possible explanation */
    int16_t unique_history; /* index of the only compatible history, or -1 */
} at_result_t;

/* bounds may be NULL. Returns AT_OK or a negative AT_ERROR_* code; *result is valid only on AT_OK. */
int at_fit(const at_frame_t *frame, const at_bounds_t *bounds, at_result_t *result);

#ifdef __cplusplus
}
#endif

#endif
