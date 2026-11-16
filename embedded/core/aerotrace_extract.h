/* AeroTrace embedded core: turn a stream of telemetry polls into one evidence frame.
 *
 * Portable C99. No heap and no I/O. Memory use is fixed: nothing grows with the length of the flight.
 * The behaviour mirrors the whole-epoch frame of aircraft_debugger/diagnostic_features.py,
 * including the detectors in evidence.py, airborne_evidence.py and propulsion_features.py.
 */
#ifndef AEROTRACE_EXTRACT_H
#define AEROTRACE_EXTRACT_H

#include <stdint.h>

#include "aerotrace_core.h"

#ifdef __cplusplus
extern "C" {
#endif

enum { AT_ERROR_SAMPLE = -3 };
enum { AT_AIRCRAFT_OTHER = 0, AT_AIRCRAFT_SUPPORTED = 1, AT_AIRCRAFT_A320_200_CFM = 2 };

/* One channel of one poll. Simulator time and local receipt time are separate clocks. */
typedef struct {
    uint8_t present;   /* the poll holds a record for this channel */
    uint8_t valid;     /* the transport returned a usable value */
    uint8_t reachable;
    uint8_t has_time;  /* the reading carries its own simulator time */
    double value;      /* a number, 0 or 1 for a switch, AT_AIRCRAFT_* for the aircraft channel */
    double sim_time_s;
    double received_s;
} at_reading_t;

typedef struct {
    uint32_t sample_index;
    double received_s;
    uint8_t connected;       /* any reading of the poll was reachable */
    uint8_t base_connected;  /* any of the twelve base-profile readings was reachable */
    uint8_t startup_capture; /* the poll includes the external-power channel */
    at_reading_t reading[AT_CHANNEL_COUNT];
} at_sample_t;

typedef struct {
    uint8_t has;
    uint32_t index;
    double time_s;
} at_point_t;

/* Running evidence for one effect. The onset bracket is frozen at the first qualifying reading. */
typedef struct {
    uint8_t observed;
    uint8_t covered;
    uint8_t any_unavailable;
    uint8_t any_pending;
    uint8_t any_gap;
    uint8_t point_count;
    at_point_t last_point;
    at_point_t last_normal;
    at_point_t lower;
    uint32_t upper_index;
    double upper_s;
} at_fact_track_t;

/* A confirmed detector event: where its onset began and the last normal reading before that. */
typedef struct {
    uint8_t has;
    uint32_t epoch;
    uint32_t confirmation_index;
    at_point_t onset;
    at_point_t normal_before;
} at_event_t;

typedef struct {
    uint8_t has_previous;
    uint8_t contradicted;
    uint32_t previous_index;
    double previous_s[3];
    double witness_s;
} at_drive_track_t;

typedef struct {
    uint8_t started;
    uint8_t has_receipt;
    uint8_t has_sim_time;
    uint32_t previous_index;
    uint32_t epoch;
    double previous_receipt_s;
    double previous_sim_time_s;
    uint8_t core_has_time[4];
    double core_time_s[4];
    uint8_t context_has_time[AT_CHANNEL_COUNT];
    double context_time_s[AT_CHANNEL_COUNT];

    uint8_t generator_reference;
    uint8_t generator_active;
    uint8_t generator_low_count;
    at_point_t generator_low_first;
    at_point_t generator_normal_before;

    uint8_t quantity_reference;
    uint8_t quantity_active;
    uint8_t quantity_count;
    double quantity_reference_value;
    at_point_t quantity_onset;
    at_point_t quantity_normal_before;

    at_event_t generator_event;
    at_event_t quantity_event;

    uint8_t window_open;
    uint32_t window_start_index;
    at_fact_track_t fact[AT_FACT_COUNT];

    uint8_t supply_previous_mode;
    uint8_t supply_contradicted;
    uint8_t supply_matched;
    uint32_t supply_previous_index;
    double supply_previous_s[AT_SUPPLY_CHANNEL_COUNT];
    double supply_first_s[AT_SUPPLY_CHANNEL_COUNT];

    at_drive_track_t drive[AT_DRIVE_LOSS_COUNT];
} at_extractor_t;

void at_extract_init(at_extractor_t *extractor);

/* Add the next poll. Returns AT_OK, or AT_ERROR_SAMPLE when sample_index does not increase. */
int at_extract_push(at_extractor_t *extractor, const at_sample_t *sample);

/* Write the evidence frame of the current clock epoch. Returns 0 while no airborne poll has been kept. */
int at_extract_frame(const at_extractor_t *extractor, at_frame_t *frame);

#ifdef __cplusplus
}
#endif

#endif
