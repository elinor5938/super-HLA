import math

def get_probability_function(x: float) -> float:
    # Semi-strict probability calculation that is more strict
    try:
        return 0.02 + (1.0 / (1.11 + math.exp(2.0 + 0.2 * x)))
    except OverflowError:
        return 0.00001
