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


def drain_single_asset_class(assets, required_amount, asset_type):
    """Drain up to `required_amount` from a single asset class
    (Cash / ISA / GIA). Used by the engine's user-configurable
    drawdown-priority walk in `simulation/engine.py` step 7,
    which iterates over the user's preferred wrapper order and
    calls this helper once per asset-class wrapper.

    The legacy `drawdown_from_assets(assets, required_amount)`
    function drains ALL three drawable classes in the fixed
    Cash → ISA → GIA order — suitable for the prior engine
    path where Pension was always pulled first and the residual
    shortfall fell through to the asset waterfall. The new
    priority walk needs to drain classes INDIVIDUALLY (e.g.
    "drain ISA first; if still short, then drain GIA; if still
    short, then drain Cash") so the user's preference for
    ISA-first (to manage the basic-rate band) is honoured.

    Property / DC are filtered out by the asset_type check, so
    no Property drawdown is possible via this helper either.
    Mirrors the no-tax assumption from `drawdown_from_assets`
    (Cash / ISA are tax-free at draw; GIA's CGT is out of scope
    and tracked as a placeholder in the engine's per-source
    series).

    Returns
    -------
    (withdrawn, breakdown) : tuple[float, dict[str, float]]
        `withdrawn`   — total £ taken from this class. Always
                        a float (0.0 when no draw was needed
                        or no asset of this class existed).
        `breakdown`   — `{asset_type: withdrawn}` when `withdrawn
                        > 0`, or `{asset_type: 0.0}` when the
                        class existed but was empty. Mirrors
                        `drawdown_from_assets`'s shape so the
                        engine's per-source series can be
                        populated by `breakdown.get(...)`.
    """
    if required_amount <= 0:
        return 0.0, {asset_type: 0.0}
    withdrawn = 0.0
    breakdown = {asset_type: 0.0}
    remaining = required_amount
    for asset in assets:
        if remaining <= 0:
            break
        if asset.asset_type != asset_type:
            continue
        take = min(asset.value, remaining)
        asset.value -= take
        withdrawn += take
        remaining -= take
        breakdown[asset_type] = (
            breakdown.get(asset_type, 0.0) + take
        )
    return withdrawn, breakdown

