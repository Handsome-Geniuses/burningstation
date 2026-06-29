from typing import Optional
from itertools import product


BayGuess = list[Optional[str]]

BAY_GUESS_BAY_STARTS = [2, 6, 10]
VIRTUAL_SENSOR_COUNT = 15
METER_WIDTH = 3
MDS_TO_BAY_GUESS_INDEX = [
    index
    for start in BAY_GUESS_BAY_STARTS
    for index in (start, start + 1, start + 2)
]
DETECTOR_INDEXES = set(MDS_TO_BAY_GUESS_INDEX)


def empty_bay_guess() -> BayGuess:
    return [None] * VIRTUAL_SENSOR_COUNT


def virtual_mds(mds: list[bool]) -> list[bool]:
    virtual = [False] * VIRTUAL_SENSOR_COUNT
    for mds_index, bay_guess_index in enumerate(MDS_TO_BAY_GUESS_INDEX):
        virtual[bay_guess_index] = bool(mds[mds_index])
    return virtual


def known_guess_footprints(bay_guess: BayGuess) -> dict[str, list[int]]:
    positions: dict[str, list[int]] = {}
    for index, ip in enumerate(bay_guess):
        if not ip:
            continue
        positions.setdefault(ip, []).append(index)
    return positions


def place_meter(bay_guess: BayGuess, ip: str, left: int) -> BayGuess:
    next_guess = clear_meter(bay_guess, ip)
    for index in range(left, left + METER_WIDTH):
        if 0 <= index < VIRTUAL_SENSOR_COUNT:
            next_guess[index] = ip
    return next_guess


def clear_meter(bay_guess: BayGuess, ip: str) -> BayGuess:
    return [None if value == ip else value for value in bay_guess]


def infer_bay_guess_from_mds(bay_guess: BayGuess, mds: list[bool], motors: list[int] | None = None) -> BayGuess:
    active = virtual_mds(mds)
    known = known_guess_footprints(bay_guess)
    next_guess = empty_bay_guess()
    moving_backward = bool(motors) and any(motor == 2 for motor in motors) and not any(motor == 1 for motor in motors)
    moving_forward = bool(motors) and any(motor == 1 for motor in motors) and not any(motor == 2 for motor in motors)

    ordered = sorted(
        ((ip, min(positions)) for ip, positions in known.items()),
        key=lambda item: item[1],
    )
    if not ordered:
        return next_guess

    active_indexes = {index for index, value in enumerate(active) if value}

    def expected_active_for_left(left: int) -> set[int]:
        return {
            index
            for index in range(left, left + METER_WIDTH)
            if index in DETECTOR_INDEXES
        }

    def candidate_lefts(previous_left: int) -> list[int]:
        return [
            left
            for left in (previous_left - 1, previous_left, previous_left + 1)
            if 0 <= left <= VIRTUAL_SENSOR_COUNT - METER_WIDTH
        ]

    candidate_sets = [candidate_lefts(previous_left) for _, previous_left in ordered]
    best_combo: tuple[int, ...] | None = None
    best_score: tuple[int, int, int, int] | None = None

    for combo in product(*candidate_sets):
        if any(combo[index] < combo[index - 1] + METER_WIDTH for index in range(1, len(combo))):
            continue

        expected = set()
        for left in combo:
            expected.update(expected_active_for_left(left))

        mismatch = len(active_indexes.symmetric_difference(expected))
        movement = sum(abs(left - previous_left) for left, (_, previous_left) in zip(combo, ordered))

        if moving_forward:
            direction_penalty = sum(max(0, previous_left - left) for left, (_, previous_left) in zip(combo, ordered))
            direction_progress = sum(max(0, left - previous_left) for left, (_, previous_left) in zip(combo, ordered))
        elif moving_backward:
            direction_penalty = sum(max(0, left - previous_left) for left, (_, previous_left) in zip(combo, ordered))
            direction_progress = sum(max(0, previous_left - left) for left, (_, previous_left) in zip(combo, ordered))
        else:
            direction_penalty = 0
            direction_progress = 0

        score = (mismatch, direction_penalty, -direction_progress, movement)
        if best_score is None or score < best_score:
            best_score = score
            best_combo = combo

    if best_combo is None:
        return bay_guess[:]

    for (ip, _), best_left in zip(ordered, best_combo):
        for index in range(best_left, best_left + METER_WIDTH):
            next_guess[index] = ip

    return next_guess
