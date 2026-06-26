FULL_STATE_PENSION = 11000  # approx per year, CPI-uprated

def state_pension_income(person, year_offset):
    """
    Returns state pension income for a given person in a given simulation year.
    """
    current_age = person.age + year_offset
    if current_age >= person.state_pension_age:
        return FULL_STATE_PENSION
    return 0
