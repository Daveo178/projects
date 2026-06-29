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

def income_vs_spending_chart(simulation_results):
    # `mortgage_payment` is a newer results field. Older saved sessions may
    # still carry results from before the field existed — fall back to all
    # zeros so the third line simply renders flat at £0 rather than crashing.
    mortgage_payment = simulation_results.get(
        "mortgage_payment",
        [0.0] * len(simulation_results["years"]),
    )
    df = pd.DataFrame({
        "Year": simulation_results["years"],
        "Income": to_int_pounds(simulation_results["income"]),
        "Spending": to_int_pounds(simulation_results["spending"]),
        "Mortgage Payment": to_int_pounds(mortgage_payment),
    })
    return df


