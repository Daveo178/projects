import numpy as np

def sample_longevity(base_years=45, std_years=5):
    """
    Returns a random number of years for the plan to run.
    Simple longevity model: normal around base_years.
    """
    years = int(np.round(np.random.normal(base_years, std_years)))
    return max(20, min(70, years))  # clamp to sensible bounds
