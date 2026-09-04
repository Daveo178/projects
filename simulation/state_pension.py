FULL_STATE_PENSION = 11000  # base amount per year at state_pension_age, CPI-uprated

def state_pension_income(
    person,
    year_offset,
    growth_rate_override=None,
    growth_path=None,
    base_factor=1.0,
):
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
    `tests/test_tax.py`) still use.    `growth_path` (optional, Monte Carlo): a per-year list of growth
    rates (one per simulation year, already mapped through the
    today's-value transform). When non-empty, the payout is a cumulative
    product of the actual year-by-year rates — `FULL_STATE_PENSION *
    prod(1 + growth_path[y])` over the active years — instead of the
    scalar `(1 + rate) ** years_active` formula. This is how the
 Monte
    Carlo sampler implements "the State Pension tracks sampled
    inflation": each element equals that year's sampled inflation, so
    the nominal payout rises with inflation year by year, while in
    today's-value mode every element is 0.0 and the payout stays flat.
    When `growth_path` is absent (deterministic runs, legacy plans) the
    scalar behaviour is unchanged.

    `base_factor` (optional, Monte Carlo): inflation factor accumulated
    before the pension first becomes payable. Nominal MC paths use this to
    express the today-money State Pension amount at its future start date;
    deterministic callers leave it at 1.0.
    """
    current_age = person.age + year_offset
    if current_age >= person.state_pension_age:
        years_active = max(0, current_age - person.state_pension_age)
        try:
            start_factor = float(base_factor)
        except (TypeError, ValueError):
            start_factor = 1.0
        if growth_path is not None and len(growth_path):
            first_active_year = max(0, int(round(person.state_pension_age - person.age)))
            factor = 1.0
            for rate in growth_path[
                first_active_year : first_active_year + int(years_active)
            ]:
                factor *= (1 + float(rate))
            return FULL_STATE_PENSION * start_factor * factor
        rate = (
            growth_rate_override
            if growth_rate_override is not None
            else person.state_pension_growth_rate
        )
        return FULL_STATE_PENSION * start_factor * (1 + rate) ** years_active
    return 0
