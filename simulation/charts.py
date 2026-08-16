import pandas as pd

from .years_and_months import format_age_label


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


def failure_age_histogram(failure_years, current_age):
    """Build a chronologically ordered, month-labelled failure histogram.

    Monte Carlo stores failures as integer year offsets, while the UI's
    current age may be fractional (for example, ``55 + 10 / 12`` from the
    years-and-months input). Adding those values directly to a chart axis
    produces labels such as ``75.833333333333336``. Keep the precise age
    calculation, but render each bucket with the shared ``Xy Ym`` formatter
    and treat the labels as categorical values.

    Returns a DataFrame with ``Failure Age`` labels and ``Failed Runs``
    counts. The labels are ordered by their underlying numeric age rather
    than alphabetically (so ``100y`` cannot appear before ``76y``).
    """
    ages = sorted(
        float(failure_year) + float(current_age)
        for failure_year in failure_years
        if failure_year is not None
    )
    labels = [format_age_label(age) for age in ages]
    counts = pd.Series(labels, dtype="string").value_counts()
    ordered_labels = list(dict.fromkeys(labels))
    return pd.DataFrame({
        "Failure Age": ordered_labels,
        "Failed Runs": [int(counts[label]) for label in ordered_labels],
    })


def income_vs_spending_chart(simulation_results, include_mortgage_in_spending=False):
    """Render the Income/Spending chart frame.

    When ``include_mortgage_in_spending=True`` (matches the toggle on
    ``pages/3_Assets.py``) the returned DataFrame has TWO columns —
    ``Income`` and a single ``Spending`` line. The engine's
    ``total_need`` treats the user's spending figure as ALREADY
    covering the mortgage (``total_need = spending`` — see
    ``simulation/engine.py`` step 7), so the Spending series shown
    here is exactly that figure: total household outgoings as one
    line, matching how a budget feels in the wallet ("how much am I
    actually spending?").

    When ``include_mortgage_in_spending=False`` (the default / today's
    behaviour) the DataFrame has THREE columns — ``Income``,
    ``Spending`` (lifestyle only), and ``Mortgage Payment`` as a
    separate line. The viewer can see the split between mortgage and
    lifestyle outgoings. The engine funds ``total_need = spending +
    mortgage_paid`` on top.

    The flag is sourced from ``st.session_state.household_data`` at
    each page render and now drives BOTH the engine's ``total_need``
    AND this chart's Spending line — the two stay consistent (flip
    the toggle and the income bars move to match the new target).

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
        # Spending already includes the mortgage (engine `total_need =
        # spending` under this flag) — show it as-is, do NOT add
        # mortgage_payment again (that would double-count and push the
        # line above the income bars).
        return pd.DataFrame({
            "Year": years,
            "Income": to_int_pounds(simulation_results["income"]),
            "Spending": to_int_pounds(simulation_results["spending"]),
        })
    return pd.DataFrame({
        "Year": years,
        "Income": to_int_pounds(simulation_results["income"]),
        "Spending": spending,
        "Mortgage Payment": mortgage_payment,
    })


