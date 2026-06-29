TRACK_MIN = 0
TRACK_MAX = 10
BOX_WIDTH = 3
BOX_LEFT_MIN = TRACK_MIN - BOX_WIDTH + 1
BOX_LEFT_MAX = TRACK_MAX
MOTOR_FORWARD = 1
MOTOR_REVERSE = 2
MOTOR_COAST = 0

SENSOR_TO_TRACK = {
    0: 0, 1: 1, 2: 2,
    3: 4, 4: 5, 5: 6,
    6: 8, 7: 9, 8: 10,
}
TRACK_TO_SENSOR = {track: sensor for sensor, track in SENSOR_TO_TRACK.items()}
BAY_STARTS = [0, 4, 8]
BAY_TRACK_POSITIONS = [
    {bay_start, bay_start + 1, bay_start + 2}
    for bay_start in BAY_STARTS
]


def box_coverage(box_left: int) -> set[int]:
    return set(range(box_left, box_left + BOX_WIDTH))


def boxes_overlap(left_a: int, left_b: int) -> bool:
    return not (
        left_a + BOX_WIDTH - 1 < left_b or
        left_b + BOX_WIDTH - 1 < left_a
    )


def boxes_are_valid(boxes: list[int]) -> bool:
    if any(box < BOX_LEFT_MIN or box > BOX_LEFT_MAX for box in boxes):
        return False

    for index, box in enumerate(boxes):
        if any(boxes_overlap(box, other) for other in boxes[index + 1:]):
            return False
    return True


def boxes_to_sensors(box_left_positions: list[int]) -> list[bool]:
    covered_track_positions: set[int] = set()
    for box_left in box_left_positions:
        covered_track_positions.update(box_coverage(box_left))

    return [
        SENSOR_TO_TRACK[sensor_index] in covered_track_positions
        for sensor_index in range(9)
    ]


def sensors_to_boxes(sensor_states: list[bool]) -> list[int]:
    active_sensors = [bool(state) for state in sensor_states]
    best_boxes: list[int] = []
    best_score: tuple[int, int, int, int] | None = None

    def score(candidate: list[int]) -> tuple[int, int, int, int]:
        rendered = boxes_to_sensors(candidate)
        missing = sum(
            1 for expected, actual in zip(active_sensors, rendered)
            if expected and not actual
        )
        extra = sum(
            1 for expected, actual in zip(active_sensors, rendered)
            if actual and not expected
        )
        return (missing * 10 + extra, missing, len(candidate), extra)

    possible_lefts = list(range(BOX_LEFT_MIN, BOX_LEFT_MAX + 1))

    def visit(start: int, candidate: list[int]):
        nonlocal best_boxes, best_score

        current_score = score(candidate)
        if best_score is None or current_score < best_score:
            best_score = current_score
            best_boxes = candidate[:]
            if best_score == (0, 0, len(candidate), 0):
                return

        if len(candidate) >= 3:
            return

        for index in range(start, len(possible_lefts)):
            box_left = possible_lefts[index]
            next_candidate = candidate + [box_left]
            if not boxes_are_valid(next_candidate):
                continue
            visit(index + 1, next_candidate)

    visit(0, [])
    return sorted(best_boxes)


def motor_can_move_box(box_left: int, bay_index: int, direction: int) -> bool:
    bay_start = BAY_STARTS[bay_index]
    bay_positions = BAY_TRACK_POSITIONS[bay_index]

    if not box_coverage(box_left) & bay_positions:
        return False

    if direction > 0:
        return box_left < bay_start + 2
    return box_left > bay_start - 2


def box_touching_bays(box_left: int) -> list[int]:
    coverage = box_coverage(box_left)
    return [
        bay_index
        for bay_index, bay_positions in enumerate(BAY_TRACK_POSITIONS)
        if coverage & bay_positions
    ]


def motor_direction_for_box(box_left: int, motors: list[int]) -> int:
    directions: set[int] = set()

    for bay_index in box_touching_bays(box_left):
        motor = motors[bay_index]
        if motor == MOTOR_FORWARD and motor_can_move_box(box_left, bay_index, 1):
            directions.add(1)
        elif motor == MOTOR_REVERSE and motor_can_move_box(box_left, bay_index, -1):
            directions.add(-1)

    return directions.pop() if len(directions) == 1 else 0


def step_boxes(boxes: list[int], motors: list[int]) -> list[int]:
    proposals = [
        box_left + motor_direction_for_box(box_left, motors)
        for box_left in boxes
    ]

    blocked_indexes: set[int] = set()
    for index, proposal in enumerate(proposals):
        if proposal < BOX_LEFT_MIN or proposal > BOX_LEFT_MAX:
            blocked_indexes.add(index)

    for index, proposal in enumerate(proposals):
        for other_index, other_proposal in enumerate(proposals[index + 1:], start=index + 1):
            if boxes_overlap(proposal, other_proposal):
                blocked_indexes.add(index)
                blocked_indexes.add(other_index)

    next_boxes = [
        boxes[index] if index in blocked_indexes else proposal
        for index, proposal in enumerate(proposals)
    ]
    return sorted(next_boxes)


def move_box_frames(boxes: list[int], box_index: int, target: int) -> list[list[int]]:
    frames: list[list[int]] = []
    current = boxes[:]
    direction = 1 if target > current[box_index] else -1

    while current[box_index] != target:
        current = current[:]
        current[box_index] += direction
        frames.append(sorted(current))

    return frames


def move_many_frames(boxes: list[int], moves: dict[int, int]) -> list[list[int]]:
    frames: list[list[int]] = []
    current = boxes[:]

    while any(current[index] != target for index, target in moves.items()):
        current = current[:]
        for index, target in moves.items():
            if current[index] < target:
                current[index] += 1
            elif current[index] > target:
                current[index] -= 1
        frames.append(sorted(current))

    return frames


def move_is_clear(boxes: list[int], box_index: int, target: int) -> bool:
    next_boxes = boxes[:]
    next_boxes[box_index] = target
    return boxes_are_valid(next_boxes)
