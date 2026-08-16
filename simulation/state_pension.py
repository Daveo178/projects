FULL_STATE_PENSION = 11000  # base amount per year at state_pension_age, CPI-uprated

def state_pension_income(person, year_offset, growth_rate_override=None):
    """
    Returns state pension income for a given person in a given simulation year.

    Once the person has reached `state_pension_age`, the income starts at
    `FULL_STATE_PENSION` and grows each year by the person's
    `state_pension_growth_rate` (default 2.5%). The growth is cumulative —
    the value at year N is `FULL_STATE_PENSION * (1+r) ** (N - state_pension_age)`.

    `growth_rate_override` (optional): pass a non-None float to bypass
    the person's stored `state_pension_growth_rate`. Used by the
    "Show in today's value" engine mode
    (`simulation/engine.py::run_simulation`) so State Pension payouts
    stay flat at `FULL_STATE_PENSION` from `state_pension_age` onwards
    in today's view (no inflation uplift). Defaults to None to preserve
    the legacy single-argument call shape that the existing tests
    (`tests/test_pre_retirement_deficit.py`,
    `tests/test_tax.py`) still use.
    """
    current_age = person.age + year_offset
    if current_age >= person.state_pension_age:
        years_active = max(0, current_age - person.state_pension_age)
        rate = (
            growth_rate_override
            if growth_rate_override is not None
            else person.state_pension_growth_rate
        )
        return FULL_STATE_PENSION * (1 + rate) ** years_active
    return 0
