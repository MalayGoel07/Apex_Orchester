import random

TASKS = [
    "Break problem into sub tasks",
    "Assign agents to parallel research",
    "Validate each result before merge",
    "Aggregate outputs into one final plan",
    "Monitor execution health in real time",
    "Retry failed steps with fallback logic",
]


def get_random_task():
    return random.choice(TASKS)
