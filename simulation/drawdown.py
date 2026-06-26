def drawdown_from_assets(assets, required_amount):
    """
    Draw down from assets in order:
    1. Cash
    2. ISA
    3. GIA
    4. DC (last)
    """

    remaining = required_amount
    withdrawn = 0

    # Priority order
    priority = {"Cash": 1, "ISA": 2, "GIA": 3, "DC": 4}
    assets_sorted = sorted(assets, key=lambda a: priority.get(a.asset_type, 99))

    for asset in assets_sorted:
        if remaining <= 0:
            break

        available = asset.value
        take = min(available, remaining)
        asset.value -= take
        withdrawn += take
        remaining -= take

    return withdrawn, remaining
