import pandas as pd


def to_int_pounds(values):
    """Round a list/Series of floats to whole-pound integers for display.

    Charts and tables should never show fractional pence — engine values
    are full-precision floats so internal math (compound growth, indexation,
    PA-tapering) stays accurate, but at the UI layer a `120000.00000003`
    tooltip is noise. Convert at the DataFrame boundary so the simulation
    core is untouched.

    ``pd.isna(v)`` is True for ``None``, Python ``float('nan')``, ``np.nan``,
    ``pd.NA`` and ``pd.NaT`` — so a single guard covers them all and lets
    those values pass through unchanged, while finite numbers map to
    ``int(round(float(v)))``. Idempotent on ints (an int in -> the same
    int out, no spurious type change).
    """
    out = []
    for v in values:
        if pd.isna(v):
            out.append(v)
            continue
        out.append(int(round(float(v))))
    return out


def net_worth_chart(simulation_results):
    df = pd.DataFrame({
        "Year": simulation_results["years"],
        "Net Worth": to_int_pounds(simulation_results["net_worth"]),
    })
    return df


def net_worth_composition_chart(simulation_results):
    """Stacked-area composition of household WEALTH by asset class.

    Returns a DataFrame with columns ``Year`` plus five asset-class
    columns — ``ISA``, ``GIA``, ``Cash``, ``Property``, ``DC Pension`` — each
    holding that class's £-value at the end of every simulated year.

    Mortgage balance is deliberately NOT included: it's debt, not an asset,
    so it doesn't belong in a positive-stacked area chart. The home page
    renders it as a dashed-red overlay line so the viewer can subtract it
    visually. Sum of these five columns equals
    ``Net Worth + outstanding mortgage`` (i.e. gross household wealth).

    Cached fallbacks for older saved payloads that predate any field:
    missing columns default to all-zero lists so the stacked chart still
    renders cleanly (with the missing slice shown as a zero-thickness
    band) rather than crashing on ``KeyError``.
    """
    years = simulation_results["years"]
    return pd.DataFrame({
        "Year": years,
        "ISA": to_int_pounds(simulation_results.get("isa_value", [0.0] * len(years))),
        "GIA": to_int_pounds(simulation_results.get("gia_value", [0.0] * len(years))),
        "Cash": to_int_pounds(simulation_results.get("cash_value", [0.0] * len(years))),
        "Property": to_int_pounds(simulation_results.get("property_value", [0.0] * len(years))),
        "DC Pension": to_int_pounds(simulation_results.get("dc_pot", [0.0] * len(years))),
    })

def pension_breakdown_chart(simulation_results):
    """Per-pension-source income breakdown — DB Pension vs State Pension.

    Returns a DataFrame with columns ``Year``, ``DB Pension``, ``State Pension``,
    each holding the household's pre-tax pension income from that source
    for the given year. Both columns are pre-tax and pre-NI (DB and State
    Pension earnings do not attract NI). The sum of the two columns equals
    the existing ``simulation_results["pension_income"]`` series.

    Cached fallbacks for older saved payloads that predate the per-source
    ``db_payout`` / ``state_payout`` fields: missing columns default to all-zero
    lists so the chart still renders (with the missing series flat at £0)
    rather than crashing on ``KeyError``.
    """
    years = simulation_results["years"]
    return pd.DataFrame({
        "Year": years,
        "DB Pension": to_int_pounds(simulation_results.get("db_payout", [0.0] * len(years))),
        "State Pension": to_int_pounds(simulation_results.get("state_payout", [0.0] * len(years))),
    })


def income_vs_spending_chart(simulation_results, include_mortgage_in_spending=False):
    """Render the Income/Spending chart frame.

    When ``include_mortgage_in_spending=True`` (matches the toggle on
    ``pages/3_Assets.py``) the returned DataFrame has TWO columns —
    ``Income`` and a single combined ``Spending`` line that is
    ``lifestyle_spending + mortgage_payment`` per year. The viewer
    sees total household outgoings as one line, which matches how a
    budget feels in the wallet ("how much am I actually spending?").

    When ``include_mortgage_in_spending=False`` (the default / today's
    behaviour) the DataFrame has THREE columns — ``Income``,
    ``Spending`` (lifestyle only), and ``Mortgage Payment`` as a
    separate line. The viewer can see the split between mortgage and
    lifestyle outgoings.

    Engine drawdown math is unchanged either way — both lifestyle and
    mortgage are already covered by ``total_need`` in the simulator
    (``total_need = spending + mortgage_paid`` in
    ``simulation/engine.py``). The flag is purely a chart-display
    preference, sourced from ``st.session_state.household_data`` at
    each page render.

    ``mortgage_payment`` is a newer results field. Older saved sessions
    may still carry results from before the field existed — fall back
    to all zeros so the chart still renders (with the mortgage-included
    line simply equalling lifestyle, or the separate mortgage line flat
    at £0) rather than crashing on KeyError.
    """
    years = simulation_results["years"]
    spending = to_int_pounds(simulation_results["spending"])
    mortgage_payment = to_int_pounds(
        simulation_results.get("mortgage_payment", [0.0] * len(years))
    )
    if include_mortgage_in_spending:
        return pd.DataFrame({
            "Year": years,
            "Income": to_int_pounds(simulation_results["income"]),
            # Element-wise sum per year. `zip` is the simplest tool here;
            # pandas is overkill for two short integer series.
            "Spending": [s + m for s, m in zip(spending, mortgage_payment)],
        })
    return pd.DataFrame({
        "Year": years,
        "Income": to_int_pounds(simulation_results["income"]),
        "Spending": spending,
        "Mortgage Payment": mortgage_payment,
    })


