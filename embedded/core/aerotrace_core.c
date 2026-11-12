#include "aerotrace_core.h"

#include <math.h>
#include <string.h>

#define BIT(index) ((uint8_t)(1u << (index)))
#define MAX_DEADLINES (AT_FACT_COUNT + AT_CONSTRAINT_COUNT)

typedef struct {
    uint8_t roots;
    double latest_s[AT_ROOT_COUNT];
} deadline_t;

typedef struct {
    double floor_s[AT_ROOT_COUNT];
    deadline_t deadline[MAX_DEADLINES];
    uint8_t deadline_count;
    uint8_t missing_witness;
} constraints_t;

static int valid_inputs(const at_frame_t *frame, const at_bounds_t *bounds)
{
    unsigned index, root, fact;
    for (index = 0; index < AT_FACT_COUNT; index++) {
        if (frame->fact[index].state > AT_STATE_UNKNOWN) {
            return AT_ERROR_FRAME;
        }
    }
    for (index = 0; index < AT_RELATION_COUNT; index++) {
        if (frame->relation[index].status > AT_CHECK_CONTRADICTED) {
            return AT_ERROR_FRAME;
        }
    }
    for (index = 0; index < AT_CONSTRAINT_COUNT; index++) {
        const at_constraint_t *rule = &AT_CONSTRAINT[index];
        const at_relation_t *relation = &frame->relation[rule->relation];
        if (rule->rule == AT_RULE_LOCAL_WITNESS && relation->status == AT_CHECK_CONTRADICTED
                && !relation->has_witness) {
            return AT_ERROR_FRAME;
        }
    }
    if (bounds == NULL) {
        return AT_OK;
    }
    for (root = 0; root < AT_ROOT_COUNT; root++) {
        for (fact = 0; fact < AT_FACT_COUNT; fact++) {
            const at_bound_t *bound = &bounds->bound[root][fact];
            if (!bound->declared) {
                continue;
            }
            if (!(AT_ROOT_REQUIRED[root] & BIT(fact))
                    || !(0.0 <= bound->minimum_s && bound->minimum_s <= bound->maximum_s
                         && bound->maximum_s <= 120.0)) {
                return AT_ERROR_BOUNDS;
            }
        }
    }
    return AT_OK;
}

/* Dependency fit of one mechanism set. An unknown required effect leaves it unconfirmed. */
static void evaluate_set(const at_frame_t *frame, uint8_t roots, at_set_result_t *out)
{
    uint8_t required = 0, reached = 0, checked = 0, unconfirmed_required = 0;
    unsigned index, total;

    for (index = 0; index < AT_ROOT_COUNT; index++) {
        if (roots & BIT(index)) {
            required |= AT_ROOT_REQUIRED[index];
            reached |= AT_ROOT_REACHED[index];
        }
    }
    for (index = 0; index < AT_FACT_COUNT; index++) {
        uint8_t state = frame->fact[index].state;
        if (!(required & BIT(index)) && (reached & BIT(index))) {
            continue; /* conditional consequence: retained and degraded outputs both fit */
        }
        out->total_checks++;
        if (state == AT_STATE_UNKNOWN) {
            out->unconfirmed_checks++;
            unconfirmed_required = 1;
        } else if ((state == AT_STATE_OBSERVED) == ((required & BIT(index)) != 0)) {
            out->supported_checks++;
        } else {
            out->contradicted_checks++;
        }
    }
    for (index = 0; index < AT_CONSTRAINT_COUNT; index++) {
        const at_constraint_t *rule = &AT_CONSTRAINT[index];
        uint8_t status;
        if (!(roots & BIT(rule->root)) || (rule->unless_root >= 0 && (roots & BIT(rule->unless_root)))
                || (checked & BIT(rule->relation))) {
            continue;
        }
        checked |= BIT(rule->relation);
        status = frame->relation[rule->relation].status;
        if (status == AT_CHECK_NOT_APPLICABLE) {
            continue;
        }
        out->total_checks++;
        if (status == AT_CHECK_CONSISTENT) {
            out->supported_checks++;
        } else if (status == AT_CHECK_UNKNOWN) {
            out->unconfirmed_checks++;
        } else {
            out->contradicted_checks++;
        }
    }

    out->dependency_status = out->contradicted_checks ? AT_EXCLUDED_BY_DEPENDENCY
        : unconfirmed_required ? AT_UNCONFIRMED : AT_COMPATIBLE;
    out->support_percent = -1;
    total = out->total_checks;
    if (total && !out->contradicted_checks) {
        /* Round half to even, as Python's round() does. */
        unsigned scaled = 100u * out->supported_checks;
        unsigned quotient = scaled / total, remainder = scaled % total;
        if (2u * remainder > total || (2u * remainder == total && (quotient & 1u))) {
            quotient++;
        }
        out->support_percent = (int8_t)quotient;
    }
}

/* Onset floors per mechanism and, for each observed effect, the latest onset of any path that explains it. */
static void timing_constraints(const at_frame_t *frame, const at_bounds_t *bounds, uint8_t roots, constraints_t *out)
{
    uint8_t excluded[AT_ROOT_COUNT] = {0};
    deadline_t witness[AT_CONSTRAINT_COUNT];
    unsigned witness_count = 0, index, root;

    memset(out, 0, sizeof *out);
    for (root = 0; root < AT_ROOT_COUNT; root++) {
        out->floor_s[root] = -INFINITY;
    }
    for (index = 0; index < AT_CONSTRAINT_COUNT; index++) {
        const at_constraint_t *rule = &AT_CONSTRAINT[index];
        const at_relation_t *relation = &frame->relation[rule->relation];
        if (rule->unless_root < 0 || relation->status != AT_CHECK_CONTRADICTED) {
            continue;
        }
        if (rule->rule == AT_RULE_LOCAL_WITNESS) {
            unsigned local = (unsigned)rule->unless_root;
            const at_bound_t *bound = bounds ? &bounds->bound[local][rule->fact] : NULL;
            deadline_t *item;
            if (!(roots & BIT(local))) {
                out->missing_witness = 1;
                continue;
            }
            item = &witness[witness_count++];
            memset(item, 0, sizeof *item);
            item->roots = BIT(local);
            item->latest_s[local] = relation->witness_s - (bound && bound->declared ? bound->minimum_s : 0.0);
        } else if (rule->rule == AT_RULE_EXCLUDED_PATH) {
            /* This path cannot produce the first response here. Another path still can. */
            excluded[rule->root] |= BIT(rule->fact);
        }
    }
    for (index = 0; index < AT_FACT_COUNT; index++) {
        const at_fact_t *fact = &frame->fact[index];
        deadline_t *item;
        int covered;
        if (fact->state != AT_STATE_OBSERVED) {
            continue;
        }
        covered = fact->covered && fact->has_lower && fact->lower_s < fact->upper_s;
        item = &out->deadline[out->deadline_count++];
        for (root = 0; root < AT_ROOT_COUNT; root++) {
            const at_bound_t *bound = bounds ? &bounds->bound[root][index] : NULL;
            int declared = bound && bound->declared;
            if (!(roots & BIT(root)) || !(AT_ROOT_REACHED[root] & BIT(index)) || (excluded[root] & BIT(index))) {
                continue;
            }
            if (covered && declared && (AT_ROOT_REQUIRED[root] & BIT(index))) {
                double floor_s = fact->lower_s - bound->maximum_s;
                if (floor_s > out->floor_s[root]) {
                    out->floor_s[root] = floor_s;
                }
            }
            item->roots |= BIT(root);
            item->latest_s[root] = fact->upper_s - (declared ? bound->minimum_s : 0.0);
        }
    }
    for (index = 0; index < witness_count; index++) {
        out->deadline[out->deadline_count++] = witness[index];
    }
}

/* Return 1 when no onset times can satisfy the order and every deadline.
 *
 * Measurement bounds are inclusive. A group that starts at the same infimum as an
 * earlier group has an open lower endpoint. Every remaining constraint is an upper
 * deadline, so moving a group later cannot help it.
 */
static int timing_conflict(const at_history_t *history, const constraints_t *constraints)
{
    double infimum_s[AT_ROOT_COUNT];
    uint8_t strictly_after[AT_ROOT_COUNT];
    double earliest_s = -INFINITY;
    unsigned group, root, index;

    if (constraints->missing_witness) {
        return 1;
    }
    for (root = 0; root < AT_ROOT_COUNT; root++) {
        infimum_s[root] = INFINITY; /* a mechanism outside the history can meet no deadline */
        strictly_after[root] = 1;
    }
    for (group = 0; group < AT_MAX_GROUPS && history->group[group]; group++) {
        double floor_s = -INFINITY;
        uint8_t strict = 1;
        for (root = 0; root < AT_ROOT_COUNT; root++) {
            if ((history->group[group] & BIT(root)) && constraints->floor_s[root] > floor_s) {
                floor_s = constraints->floor_s[root];
            }
        }
        if (floor_s > earliest_s) {
            earliest_s = floor_s;
            strict = 0;
        }
        for (root = 0; root < AT_ROOT_COUNT; root++) {
            if (history->group[group] & BIT(root)) {
                infimum_s[root] = earliest_s;
                strictly_after[root] = strict;
            }
        }
    }
    for (index = 0; index < constraints->deadline_count; index++) {
        const deadline_t *item = &constraints->deadline[index];
        int met = 0;
        for (root = 0; root < AT_ROOT_COUNT && !met; root++) {
            if (item->roots & BIT(root)) {
                met = infimum_s[root] < item->latest_s[root]
                    || (infimum_s[root] == item->latest_s[root] && !strictly_after[root]);
            }
        }
        if (!met) {
            return 1;
        }
    }
    return 0;
}

int at_fit(const at_frame_t *frame, const at_bounds_t *bounds, at_result_t *result)
{
    unsigned set, other, index, compatible_total = 0, unconfirmed_possible = 0;
    uint32_t possible = 0;
    int status = valid_inputs(frame, bounds);

    if (status != AT_OK) {
        return status;
    }
    memset(result, 0, sizeof *result);
    result->unique_history = -1;
    for (set = 0; set < AT_SET_COUNT; set++) {
        at_set_result_t *fit = &result->set[set];
        constraints_t constraints;
        int rejected;

        evaluate_set(frame, AT_SET_ROOTS[set], fit);
        rejected = fit->dependency_status == AT_EXCLUDED_BY_DEPENDENCY;
        if (!rejected) {
            timing_constraints(frame, bounds, AT_SET_ROOTS[set], &constraints);
        }
        for (index = AT_SET_FIRST_HISTORY[set]; index < AT_SET_FIRST_HISTORY[set + 1]; index++) {
            uint8_t history_status = rejected ? AT_EXCLUDED_BY_DEPENDENCY
                : timing_conflict(&AT_HISTORY[index], &constraints) ? AT_EXCLUDED_BY_TIMING
                : fit->dependency_status;
            result->history_status[index] = history_status;
            fit->history_count[history_status]++;
            result->history_count[history_status]++;
        }
        if (fit->history_count[AT_COMPATIBLE] || fit->history_count[AT_UNCONFIRMED]) {
            possible |= (uint32_t)1 << set;
            compatible_total += fit->history_count[AT_COMPATIBLE];
            unconfirmed_possible += fit->history_count[AT_UNCONFIRMED];
        }
    }
    for (set = 0; set < AT_SET_COUNT; set++) {
        int minimal = (possible >> set) & 1u;
        for (other = 0; other < AT_SET_COUNT && minimal; other++) {
            uint8_t smaller = AT_SET_ROOTS[other], roots = AT_SET_ROOTS[set];
            if (((possible >> other) & 1u) && smaller != roots && (smaller & roots) == smaller) {
                minimal = 0;
            }
        }
        if (minimal) {
            result->minimal_sets |= (uint32_t)1 << set;
        }
    }
    if (compatible_total == 1 && !unconfirmed_possible) {
        for (index = 0; index < AT_HISTORY_COUNT; index++) {
            if (result->history_status[index] == AT_COMPATIBLE) {
                result->unique_history = (int16_t)index;
                break;
            }
        }
    }
    return AT_OK;
}
