#include "aerotrace_extract.h"

#include <string.h>

enum { CORE_GENERATOR, CORE_BUS, CORE_QUANTITY, CORE_PRESSURE };
enum { SUPPLY_NONE, SUPPLY_BACKED, SUPPLY_UNBACKED };

/* One effect as read from a single poll. */
typedef struct {
    uint8_t state;
    uint8_t usable;
    uint8_t soft; /* unknown only because the reference is still being established */
    double time_s;
} view_t;

static int stale(const at_reading_t *reading, double receipt_s)
{
    return reading->present && receipt_s - reading->received_s > AT_T_MAXIMUM_READING_AGE_LOCAL_S;
}

static void clear_window(at_extractor_t *x)
{
    x->window_open = 0;
    memset(x->fact, 0, sizeof x->fact);
    x->supply_previous_mode = SUPPLY_NONE;
    x->supply_contradicted = 0;
    x->supply_matched = 0;
    memset(x->drive, 0, sizeof x->drive);
}

void at_extract_init(at_extractor_t *extractor)
{
    memset(extractor, 0, sizeof *extractor);
}

/* A selected-system reading counts only when it is fresh and its own simulator time advanced. */
static const at_reading_t *select_core(at_extractor_t *x, const at_sample_t *sample, unsigned slot, unsigned channel)
{
    const at_reading_t *reading = &sample->reading[channel];
    uint8_t had;
    double old_s;

    if (!reading->present || !reading->valid || !reading->reachable || stale(reading, sample->received_s)
            || !reading->has_time) {
        return NULL;
    }
    had = x->core_has_time[slot];
    old_s = x->core_time_s[slot];
    x->core_has_time[slot] = 1;
    x->core_time_s[slot] = reading->sim_time_s;
    return had && reading->sim_time_s <= old_s ? NULL : reading;
}

static int context_usable(at_extractor_t *x, const at_sample_t *sample, unsigned channel, int poll_unusable)
{
    const at_reading_t *reading = &sample->reading[channel];
    int usable = !poll_unusable;

    if (!reading->present || !reading->valid) {
        return 0;
    }
    if (stale(reading, sample->received_s)) {
        usable = 0;
    }
    if (!reading->has_time) {
        return 0;
    }
    if (x->context_has_time[channel] && reading->sim_time_s <= x->context_time_s[channel]) {
        usable = 0;
    }
    x->context_has_time[channel] = 1;
    x->context_time_s[channel] = reading->sim_time_s;
    return usable;
}

static view_t unknown_view(void)
{
    view_t view = {AT_STATE_UNKNOWN, 0, 0, 0.0};
    return view;
}

static view_t known_view(uint8_t state, const at_reading_t *reading)
{
    view_t view = {state, 1, 0, 0.0};
    view.time_s = reading->sim_time_s;
    return view;
}

/* Source loss needs an energized reference and low output on consecutive usable readings. */
static view_t generator_view(at_extractor_t *x, const at_sample_t *sample)
{
    const at_reading_t *reading = select_core(x, sample, CORE_GENERATOR, AT_CHANNEL_GENERATOR_2_VOLTAGE);
    at_point_t now;
    uint8_t state = AT_STATE_UNKNOWN;

    if (reading == NULL) {
        x->generator_low_count = 0;
        return unknown_view();
    }
    now.has = 1;
    now.index = sample->sample_index;
    now.time_s = reading->sim_time_s;
    if (reading->value >= AT_T_ENERGIZED_REFERENCE_AT_LEAST_V) {
        x->generator_reference = 1;
        x->generator_active = 0;
        x->generator_low_count = 0;
        state = AT_STATE_NOT_OBSERVED;
    } else if (reading->value < AT_T_GENERATOR_UNAVAILABLE_BELOW_V) {
        if (!x->generator_reference) {
            x->generator_low_count = 0;
        } else if (x->generator_active) {
            state = AT_STATE_OBSERVED;
        } else {
            if (x->generator_low_count == 0) {
                x->generator_low_first = now;
                x->generator_normal_before = x->fact[AT_FACT_GENERATOR_SOURCE_ANOMALY].last_normal;
            }
            if (x->generator_low_count < UINT8_MAX) {
                x->generator_low_count++;
            }
            if (x->generator_low_count >= AT_T_GENERATOR_CONFIRMATION_READINGS) {
                x->generator_active = 1;
                x->generator_event.has = 1;
                x->generator_event.epoch = x->epoch;
                x->generator_event.confirmation_index = sample->sample_index;
                x->generator_event.onset = x->generator_low_first;
                x->generator_event.normal_before = x->generator_normal_before;
                state = AT_STATE_OBSERVED;
            }
        }
    } else {
        x->generator_low_count = 0;
        state = AT_STATE_OBSERVED; /* reduced output */
    }
    return known_view(state, reading);
}

/* Inventory loss is a drop from the first usable quantity reading of the clock epoch. */
static view_t quantity_view(at_extractor_t *x, const at_sample_t *sample)
{
    const at_reading_t *reading = select_core(x, sample, CORE_QUANTITY, AT_CHANNEL_BLUE_QUANTITY);
    at_point_t now;
    view_t view;
    double drop;

    if (reading == NULL) {
        return unknown_view();
    }
    now.has = 1;
    now.index = sample->sample_index;
    now.time_s = reading->sim_time_s;
    if (x->quantity_count < UINT8_MAX) {
        x->quantity_count++;
    }
    if (!x->quantity_reference) {
        x->quantity_reference = 1;
        x->quantity_reference_value = reading->value;
    }
    drop = x->quantity_reference_value - reading->value;
    if (drop >= AT_T_BLUE_QUANTITY_ONSET_DROP_RAW && !x->quantity_onset.has) {
        x->quantity_onset = now;
        x->quantity_normal_before = x->fact[AT_FACT_BLUE_INVENTORY_LOSS].last_normal;
    } else if (drop < AT_T_BLUE_QUANTITY_ONSET_DROP_RAW && !x->quantity_active) {
        x->quantity_onset.has = 0;
    }

    view = known_view(drop >= AT_T_BLUE_QUANTITY_ONSET_DROP_RAW ? AT_STATE_UNKNOWN : AT_STATE_NOT_OBSERVED, reading);
    if (drop >= AT_T_BLUE_QUANTITY_DROP_RAW && x->quantity_count >= AT_T_QUANTITY_MINIMUM_PROGRESSING_READINGS) {
        if (!x->quantity_active) {
            x->quantity_active = 1;
            x->quantity_event.has = 1;
            x->quantity_event.epoch = x->epoch;
            x->quantity_event.confirmation_index = sample->sample_index;
            x->quantity_event.onset = x->quantity_onset;
            x->quantity_event.normal_before = x->quantity_normal_before;
        }
        view.state = AT_STATE_OBSERVED;
    } else if (x->quantity_active && drop <= AT_T_BLUE_QUANTITY_RECOVERY_TOLERANCE_RAW) {
        x->quantity_active = 0;
        x->quantity_onset.has = 0;
    } else if (x->quantity_active) {
        view.state = AT_STATE_OBSERVED;
    } else if (x->quantity_count < AT_T_QUANTITY_MINIMUM_PROGRESSING_READINGS) {
        view.state = AT_STATE_UNKNOWN;
        view.soft = 1;
    }
    return view;
}

static view_t threshold_view(at_extractor_t *x, const at_sample_t *sample, unsigned slot, unsigned channel,
                             double retained_at_least)
{
    const at_reading_t *reading = select_core(x, sample, slot, channel);
    if (reading == NULL) {
        return unknown_view();
    }
    return known_view(reading->value >= retained_at_least ? AT_STATE_NOT_OBSERVED : AT_STATE_OBSERVED, reading);
}

static void track_fact(at_fact_track_t *track, const view_t *view, uint32_t index, const at_event_t *event,
                       uint32_t epoch, uint32_t window_start)
{
    if (track->observed) {
        return; /* later recovery or missing data does not erase an observed effect */
    }
    if (!view->usable) {
        track->any_unavailable = 1;
    }
    if (view->state == AT_STATE_UNKNOWN && !view->soft) {
        track->any_pending = 1;
    }
    if (view->usable) {
        if (track->last_point.has) {
            double delta_s = view->time_s - track->last_point.time_s;
            if (index != track->last_point.index + 1 || delta_s <= 0.0 || delta_s > AT_T_MAXIMUM_OBSERVATION_GAP_SIM_S) {
                track->any_gap = 1;
            }
        }
        track->last_point.has = 1;
        track->last_point.index = index;
        track->last_point.time_s = view->time_s;
        if (track->point_count < 2) {
            track->point_count++;
        }
    }
    if (view->state == AT_STATE_OBSERVED) {
        track->observed = 1;
        track->covered = (uint8_t)(!track->any_unavailable && !track->any_gap);
        track->lower = track->last_normal;
        track->upper_index = index;
        track->upper_s = view->time_s;
        if (event != NULL && event->has && event->epoch == epoch && window_start <= event->confirmation_index
                && event->confirmation_index <= index) {
            /* The detector confirmed later than the first qualifying change. Use that first change. */
            track->lower = event->normal_before;
            track->upper_index = event->onset.index;
            track->upper_s = event->onset.time_s;
        }
    } else if (view->state == AT_STATE_NOT_OBSERVED && view->usable) {
        track->last_normal.has = 1;
        track->last_normal.index = index;
        track->last_normal.time_s = view->time_s;
    }
}

/* Settled Yellow line pressure should follow whether a backup source is delivering pressure. */
static void track_supply(at_extractor_t *x, const at_sample_t *sample, const uint8_t *measured)
{
    const at_reading_t *reading = sample->reading;
    double time_s[AT_SUPPLY_CHANNEL_COUNT], earliest_s = 0.0, latest_s = 0.0, settled_s = 0.0;
    uint8_t mode = SUPPLY_NONE;
    unsigned index;
    int complete = 1, continuous;

    for (index = 0; index < AT_SUPPLY_CHANNEL_COUNT; index++) {
        complete = complete && measured[AT_SUPPLY_CHANNEL[index]];
        time_s[index] = reading[AT_SUPPLY_CHANNEL[index]].sim_time_s;
        if (index == 0 || time_s[index] < earliest_s) {
            earliest_s = time_s[index];
        }
        if (index == 0 || time_s[index] > latest_s) {
            latest_s = time_s[index];
        }
    }
    if (complete && latest_s - earliest_s <= AT_T_MAXIMUM_READING_SKEW_SIM_S
            && reading[AT_CHANNEL_YELLOW_EDP_PRESSURE].value < AT_T_INSUFFICIENT_SOURCE_PSI
            && reading[AT_CHANNEL_YELLOW_QUANTITY].value >= AT_T_MINIMUM_YELLOW_QUANTITY_RAW) {
        double electric = reading[AT_CHANNEL_YELLOW_ELECTRIC_PRESSURE].value;
        double transfer = reading[AT_CHANNEL_YELLOW_TRANSFER_PRESSURE].value;
        double alternate = electric > transfer ? electric : transfer;
        if (alternate >= AT_T_USEFUL_SOURCE_PSI) {
            mode = SUPPLY_BACKED;
        } else if (alternate < AT_T_INSUFFICIENT_SOURCE_PSI) {
            mode = SUPPLY_UNBACKED;
        }
    }
    continuous = mode != SUPPLY_NONE && mode == x->supply_previous_mode
        && sample->sample_index == x->supply_previous_index + 1;
    for (index = 0; index < AT_SUPPLY_CHANNEL_COUNT && continuous; index++) {
        double delta_s = time_s[index] - x->supply_previous_s[index];
        continuous = 0.0 < delta_s && delta_s <= AT_T_MAXIMUM_SUPPLY_GAP_SIM_S;
    }
    if (!continuous) {
        memcpy(x->supply_first_s, time_s, sizeof time_s);
    }
    x->supply_previous_mode = mode;
    x->supply_previous_index = sample->sample_index;
    memcpy(x->supply_previous_s, time_s, sizeof time_s);
    if (mode == SUPPLY_NONE || x->supply_contradicted) {
        return;
    }
    for (index = 0; index < AT_SUPPLY_CHANNEL_COUNT; index++) {
        double elapsed_s = time_s[index] - x->supply_first_s[index];
        if (index == 0 || elapsed_s < settled_s) {
            settled_s = elapsed_s;
        }
    }
    if (settled_s >= AT_T_SUPPLY_SETTLING_SIM_S) {
        double line = reading[AT_CHANNEL_YELLOW_PRESSURE].value;
        uint8_t expected = line >= AT_T_USEFUL_SOURCE_PSI ? SUPPLY_BACKED
            : line < AT_T_LOW_YELLOW_PRESSURE_PSI ? SUPPLY_UNBACKED : SUPPLY_NONE;
        if (expected == mode) {
            x->supply_matched = 1;
        } else if (expected != SUPPLY_NONE) {
            x->supply_contradicted = 1;
        }
    }
}

/* A source that stays lost on consecutive polls while engine drive is measured needs its own cause. */
static void track_drive(at_extractor_t *x, const at_sample_t *sample, const uint8_t *measured)
{
    const at_reading_t *reading = sample->reading;
    int drive_retained = measured[AT_CHANNEL_ENGINE_2_N2] && measured[AT_CHANNEL_ENGINE_2_FUEL_FLOW]
        && reading[AT_CHANNEL_ENGINE_2_N2].value >= AT_T_RETAINED_ENGINE_2_N2
        && reading[AT_CHANNEL_ENGINE_2_FUEL_FLOW].value >= AT_T_RETAINED_ENGINE_2_FUEL_FLOW;
    unsigned index, part;

    for (index = 0; index < AT_DRIVE_LOSS_COUNT; index++) {
        at_drive_track_t *track = &x->drive[index];
        unsigned channel = AT_DRIVE_LOSS[index].channel;
        double time_s[3], earliest_s, latest_s;
        int witness, sustained;

        time_s[0] = reading[AT_CHANNEL_ENGINE_2_N2].sim_time_s;
        time_s[1] = reading[AT_CHANNEL_ENGINE_2_FUEL_FLOW].sim_time_s;
        time_s[2] = reading[channel].sim_time_s;
        earliest_s = latest_s = time_s[0];
        for (part = 1; part < 3; part++) {
            earliest_s = time_s[part] < earliest_s ? time_s[part] : earliest_s;
            latest_s = time_s[part] > latest_s ? time_s[part] : latest_s;
        }
        witness = drive_retained && measured[channel] && reading[channel].value < AT_DRIVE_LOSS[index].below
            && latest_s - earliest_s <= AT_T_MAXIMUM_READING_SKEW_SIM_S;
        sustained = witness && track->has_previous && !track->contradicted
            && sample->sample_index == track->previous_index + 1;
        for (part = 0; part < 3 && sustained; part++) {
            double delta_s = time_s[part] - track->previous_s[part];
            sustained = 0.0 < delta_s && delta_s <= AT_T_MAXIMUM_SUPPLY_GAP_SIM_S;
        }
        if (sustained) {
            track->contradicted = 1;
            track->witness_s = track->previous_s[2];
        }
        track->has_previous = (uint8_t)witness;
        track->previous_index = sample->sample_index;
        memcpy(track->previous_s, time_s, sizeof time_s);
    }
}

int at_extract_push(at_extractor_t *x, const at_sample_t *sample)
{
    const at_reading_t *reading = sample->reading;
    const at_reading_t *clock = &reading[AT_CHANNEL_SIM_TIME];
    const at_reading_t *pause = &reading[AT_CHANNEL_PAUSED];
    const at_reading_t *aircraft = &reading[AT_CHANNEL_AIRCRAFT];
    int has_sim_time = clock->present && clock->valid;
    int paused_or_unknown = !(pause->present && pause->valid) || pause->value != 0.0;
    int core_unusable, context_unusable, airborne;
    uint8_t usable[AT_CHANNEL_COUNT], measured[AT_CHANNEL_COUNT];
    view_t view[AT_FACT_COUNT];
    unsigned index;

    if (x->started && sample->sample_index <= x->previous_index) {
        return AT_ERROR_SAMPLE;
    }
    x->started = 1;
    x->previous_index = sample->sample_index;

    core_unusable = !sample->base_connected
        || !(aircraft->present && aircraft->valid && aircraft->value >= AT_AIRCRAFT_SUPPORTED)
        || !has_sim_time || paused_or_unknown
        || stale(clock, sample->received_s) || stale(pause, sample->received_s) || stale(aircraft, sample->received_s);
    context_unusable = !sample->connected || !has_sim_time || clock->value < 0.0 || paused_or_unknown
        || stale(clock, sample->received_s) || stale(pause, sample->received_s)
        || !clock->has_time || (pause->present && pause->valid && !pause->has_time);
    if ((x->has_receipt && sample->received_s < x->previous_receipt_s)
            || (has_sim_time && x->has_sim_time && clock->value < x->previous_sim_time_s)) {
        /* A clock reset starts a new epoch. Earlier references and onsets do not carry over. */
        x->epoch++;
        memset(x->core_has_time, 0, sizeof x->core_has_time);
        memset(x->context_has_time, 0, sizeof x->context_has_time);
        x->generator_reference = x->generator_active = x->generator_low_count = 0;
        x->quantity_reference = x->quantity_active = x->quantity_count = 0;
        x->quantity_onset.has = 0;
        clear_window(x);
        core_unusable = context_unusable = 1;
    } else if (has_sim_time && x->has_sim_time && clock->value == x->previous_sim_time_s) {
        core_unusable = context_unusable = 1;
    }
    x->has_receipt = 1;
    x->previous_receipt_s = sample->received_s;
    if (has_sim_time) {
        x->has_sim_time = 1;
        x->previous_sim_time_s = clock->value;
    }

    if (core_unusable) {
        x->generator_low_count = 0; /* an unusable poll must not complete a confirmation */
        view[AT_FACT_GENERATOR_SOURCE_ANOMALY] = view[AT_FACT_BUS_SUPPLY_LOSS] = unknown_view();
        view[AT_FACT_BLUE_INVENTORY_LOSS] = view[AT_FACT_BLUE_PRESSURE_LOSS] = unknown_view();
    } else {
        view[AT_FACT_GENERATOR_SOURCE_ANOMALY] = generator_view(x, sample);
        view[AT_FACT_BUS_SUPPLY_LOSS] = threshold_view(x, sample, CORE_BUS, AT_CHANNEL_AC_BUS_2,
                                                       AT_T_BUS_RETAINED_AT_LEAST_V);
        view[AT_FACT_BLUE_INVENTORY_LOSS] = quantity_view(x, sample);
        view[AT_FACT_BLUE_PRESSURE_LOSS] = threshold_view(x, sample, CORE_PRESSURE, AT_CHANNEL_BLUE_PRESSURE,
                                                          AT_T_BLUE_PRESSURE_RETAINED_AT_LEAST_PSI);
    }

    for (index = 0; index < AT_CHANNEL_COUNT; index++) {
        usable[index] = (uint8_t)context_usable(x, sample, index, context_unusable);
    }
    airborne = usable[AT_CHANNEL_AIRCRAFT] && aircraft->value == AT_AIRCRAFT_A320_200_CFM
        && usable[AT_CHANNEL_MAIN_GEAR_1_WOW] && reading[AT_CHANNEL_MAIN_GEAR_1_WOW].value == 0.0
        && usable[AT_CHANNEL_MAIN_GEAR_2_WOW] && reading[AT_CHANNEL_MAIN_GEAR_2_WOW].value == 0.0
        && usable[AT_CHANNEL_HEIGHT_AGL] && reading[AT_CHANNEL_HEIGHT_AGL].value > 0.0;
    for (index = 0; index < AT_CHANNEL_COUNT; index++) {
        measured[index] = (uint8_t)(airborne && usable[index] && reading[index].value >= 0.0);
    }
    for (index = 0; index < AT_PROPULSION_FACT_COUNT; index++) {
        const at_propulsion_fact_t *rule = &AT_PROPULSION_FACT[index];
        view[rule->fact] = unknown_view();
        if (measured[rule->channel]) {
            view[rule->fact] = known_view(reading[rule->channel].value < rule->below
                                          ? AT_STATE_OBSERVED : AT_STATE_NOT_OBSERVED, &reading[rule->channel]);
        }
    }

    if (!x->window_open) {
        const at_reading_t *gear_1 = &reading[AT_CHANNEL_MAIN_GEAR_1_WOW];
        const at_reading_t *gear_2 = &reading[AT_CHANNEL_MAIN_GEAR_2_WOW];
        const at_reading_t *height = &reading[AT_CHANNEL_HEIGHT_AGL];
        /* A capture that starts on the ground is fitted only from its first airborne poll. */
        if (sample->startup_capture
                && !(gear_1->present && gear_1->valid && gear_1->value == 0.0
                     && gear_2->present && gear_2->valid && gear_2->value == 0.0
                     && height->present && height->valid && height->value > 0.0)) {
            return AT_OK;
        }
        x->window_open = 1;
        x->window_start_index = sample->sample_index;
    }
    for (index = 0; index < AT_FACT_COUNT; index++) {
        const at_event_t *event = index == AT_FACT_GENERATOR_SOURCE_ANOMALY ? &x->generator_event
            : index == AT_FACT_BLUE_INVENTORY_LOSS ? &x->quantity_event : NULL;
        track_fact(&x->fact[index], &view[index], sample->sample_index, event, x->epoch, x->window_start_index);
    }
    track_supply(x, sample, measured);
    track_drive(x, sample, measured);
    return AT_OK;
}

int at_extract_frame(const at_extractor_t *x, at_frame_t *frame)
{
    const at_fact_track_t *quantity = &x->fact[AT_FACT_BLUE_INVENTORY_LOSS];
    const at_fact_track_t *pressure = &x->fact[AT_FACT_BLUE_PRESSURE_LOSS];
    at_relation_t *relation;
    unsigned index;

    if (!x->window_open) {
        return 0;
    }
    memset(frame, 0, sizeof *frame);
    for (index = 0; index < AT_FACT_COUNT; index++) {
        const at_fact_track_t *track = &x->fact[index];
        at_fact_t *fact = &frame->fact[index];
        if (track->observed) {
            fact->state = AT_STATE_OBSERVED;
            fact->has_lower = track->lower.has;
            fact->lower_s = track->lower.has ? track->lower.time_s : 0.0;
            fact->upper_s = track->upper_s;
            fact->covered = track->covered;
        } else {
            /* Absence needs two usable readings and unbroken coverage. Missing data is never healthy. */
            fact->state = track->point_count >= 2 && !track->any_unavailable && !track->any_pending
                && !track->any_gap ? AT_STATE_NOT_OBSERVED : AT_STATE_UNKNOWN;
        }
    }

    relation = &frame->relation[AT_RELATION_INVENTORY_BEFORE_PRESSURE];
    if (!quantity->observed || !pressure->observed) {
        relation->status = AT_CHECK_NOT_APPLICABLE;
    } else if (!quantity->lower.has || !pressure->lower.has || !quantity->covered || !pressure->covered) {
        relation->status = AT_CHECK_UNKNOWN;
    } else if (quantity->upper_s < pressure->lower.time_s && quantity->upper_index < pressure->lower.index) {
        /* Separate polls are required, so read offsets inside one poll cannot fake an order. */
        relation->status = AT_CHECK_CONSISTENT;
    } else if (pressure->upper_s < quantity->lower.time_s && pressure->upper_index < quantity->lower.index) {
        relation->status = AT_CHECK_CONTRADICTED;
    } else {
        relation->status = AT_CHECK_UNKNOWN;
    }

    relation = &frame->relation[AT_RELATION_YELLOW_PRESSURE_FOLLOWS_MEASURED_SUPPLY];
    relation->status = !x->fact[AT_FACT_YELLOW_EDP_OUTPUT_LOSS].observed ? AT_CHECK_NOT_APPLICABLE
        : x->supply_contradicted ? AT_CHECK_CONTRADICTED
        : x->supply_matched ? AT_CHECK_CONSISTENT : AT_CHECK_UNKNOWN;

    for (index = 0; index < AT_DRIVE_LOSS_COUNT; index++) {
        relation = &frame->relation[AT_DRIVE_LOSS[index].relation];
        relation->status = x->drive[index].contradicted ? AT_CHECK_CONTRADICTED : AT_CHECK_NOT_APPLICABLE;
        relation->has_witness = x->drive[index].contradicted;
        relation->witness_s = x->drive[index].contradicted ? x->drive[index].witness_s : 0.0;
    }
    return 1;
}
