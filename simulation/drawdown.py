def drawdown_from_assets(assets, required_amount):
    """
    Withdraw from household assets in the standard retirement drawdown
    priority order:

        1. Cash   (cheapest, no tax / no need to crystallise gains)
        2. ISA    (tax-free, but only ~£20k/yr can be contributed)
        3. GIA    (capital gains tax is modelled separately / out of scope)
        4. DC     (UFPLS — handled by the engine, NOT by this function)

    Property is intentionally excluded — model users don't "draw down"
    from their home. DC is also excluded because UF PLS has its own
    PCLS-tax-free-and-taxable split that the engine runs first; this
    helper only funds the residual shortfall after UFPLS.

    Returns
    -------
    (withdrawn, breakdown) : tuple[float, dict[str, float]]
        `withdrawn`   — total £ taken (sum of per-asset amounts). Always
                        a float (0.0 when no draw was needed).
        `breakdown`   — maps asset_type ('Cash' / 'ISA' / 'GIA') → £
                        withdrawn from that asset. Empty dict when
                        nothing was needed (`required_amount <= 0`) or
                        no drawable asset existed. Property / DC entries
                        never appear here — they are filtered out before
                        the priority sort runs.

    Mutates the passed-in `assets` list in-place — each asset's `value`
    field is reduced by the amount drawn from it. The engine calls this
    once per simulated year; the cumulative asset values are reflected
    in the next year's `dc_pot` / `isa_value` / etc. summary fields.
    """

    remaining = required_amount
    withdrawn = 0.0
    breakdown = {}

    # Whitelist approach: only Cash / ISA / GIA are drawable here.
    # Property and DC are handled by other paths (or not at all —
    # Property is excluded by design; DC is unwound via UFPLS upstream
    # in the engine). Using a whitelist avoids accidentally drawing
    # from a property when an "unused" asset_type string slips in,
    # which would have produced silent `breakdown["Property"] = n`
    # entries historically and is why the old priority-dict-with-
    # fallback-99 code was retired.
    DRAWDOWN_TYPES = {"Cash", "ISA", "GIA"}
    priority = {"Cash": 1, "ISA": 2, "GIA": 3}
    drawable = [
        a for a in assets
        if a.asset_type in DRAWDOWN_TYPES
    ]
    assets_sorted = sorted(
        drawable, key=lambda a: priority[a.asset_type]
    )

    for asset in assets_sorted:
        if remaining <= 0:
            break
        available = asset.value
        take = min(available, remaining)
        asset.value -= take
        withdrawn += take
        remaining -= take
        breakdown[asset.asset_type] = (
            breakdown.get(asset.asset_type, 0.0) + take
        )

    return withdrawn, breakdown
