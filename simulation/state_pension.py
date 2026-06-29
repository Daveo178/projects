FULL_STATE_PENSION = 11000  # base amount per year at state_pension_age, CPI-uprated

def state_pension_income(person, year_offset):
    """
    Returns state pension income for a given person in a given simulation year.

    Once the person has reached `state_pension_age`, the income starts at
    `FULL_STATE_PENSION` and grows each year by the person's
    `state_pension_growth_rate` (default 2.5%). The growth is cumulative —
    the value at year N is `FULL_STATE_PENSION * (1+r) ** (N - state_pension_age)`.
    """
    current_age = person.age + year_offset
    if current_age >= person.state_pension_age:
        years_active = max(0, current_age - person.state_pension_age)
        return FULL_STATE_PENSION * (1 + person.state_pension_growth_rate) ** years_active
    return 0
