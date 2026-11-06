"""Enumerate one onset per selected mechanism, with ties allowed."""

from itertools import combinations


def ordered_onsets(mechanisms):
    """Yield ordered partitions of every nonempty subset of the mechanisms."""
    for size in range(1, len(mechanisms) + 1):
        for group in combinations(mechanisms, size):
            yield (group,)
            remaining = tuple(mechanism for mechanism in mechanisms if mechanism not in group)
            for tail in ordered_onsets(remaining):
                yield (group, *tail)
