from .state_pension import state_pension_income
from .drawdown import drawdown_from_assets

def run_simulation(household, years=45):
    """
    Runs a year-by-year simulation of the household finances.
    Returns a dictionary of results for charts and AI analysis.
    """

    results = {
        "tax": [],
        "net_income": [],
        "gross_income": [],
        "effective_tax_rate": [],
        "years": [],
        "net_worth": [],
        "income": [],
        "spending": [],
        "dc_pot": [],
        "isa_value": [],
        "gia_value": [],
        "cash_value": [],
        "property_value": [],
        "mortgage_balance": [],
        "tax_free_income": [],
        "events_triggered": []
    }

    for year in range(years):
        results["years"].append(year)

        # -------------------------
        # 1. Income (earned, DB, state pension)
        # -------------------------
        income = 0
        gross_income = 0

        # Person 1
        if not household.person1.is_retired(year):
            gross_income += household.person1.income_until_retirement
        gross_income += state_pension_income(household.person1, year)
        gross_income += household.person1.db_income

        # Person 2
        if not household.person2.is_retired(year):
            gross_income += household.person2.income_until_retirement
        gross_income += state_pension_income(household.person2, year)
        gross_income += household.person2.db_income

        from .tax import uk_income_tax
        tax_result = uk_income_tax(gross_income)
        income = tax_result["net"]

        # ---------------------------------------------------------
        # 1b. Calculate total PCLS allowance at retirement (once)
        # ---------------------------------------------------------
        if household.person1.is_retired(year) and household.person1.pcls_available == 0:
            household.person1.pcls_available = (
                household.person1.dc_pot * (household.person1.pcls_percent / 100)
            )

        if household.person2.is_retired(year) and household.person2.pcls_available == 0:
            household.person2.pcls_available = (
                household.person2.dc_pot * (household.person2.pcls_percent / 100)
            )

        # -------------------------
        # 2. DC Contributions
        # -------------------------
        if not household.person1.is_retired(year):
            household.person1.dc_pot += household.person1.monthly_contrib * 12
        if not household.person2.is_retired(year):
            household.person2.dc_pot += household.person2.monthly_contrib * 12

        # -------------------------
        # 3. Asset Growth
        # -------------------------
        for asset in household.assets:
            asset.grow()

        # -------------------------
        # 4. Mortgage
        # -------------------------
        if household.mortgage and household.mortgage.is_active(year):
            household.mortgage.apply_interest()

        # -------------------------
        # 5. Life Events (including downsizing)
        # -------------------------
        triggered = []

        if household.events:
            for event in household.events:
                if event.year == year:

                    # Standard life event
                    if hasattr(event, "amount"):
                        triggered.append(event.description)
                        for asset in household.assets:
                            if asset.asset_type == "Cash":
                                asset.value += event.amount
                                break

                    # Downsizing event
                    if hasattr(event, "sell_property_value"):
                        triggered.append("Downsizing")

                        # 1. Sell current property
                        for asset in household.assets:
                            if asset.asset_type == "Property":
                                sale_proceeds = event.sell_property_value
                                asset.value = event.new_property_value
                                break

                        # 2. Add sale proceeds to cash
                        for asset in household.assets:
                            if asset.asset_type == "Cash":
                                asset.value += sale_proceeds
                                break

                        # 3. Clear mortgage if present
                        if household.mortgage:
                            household.mortgage.outstanding = 0

        results["events_triggered"].append(triggered)
        results["tax"].append(tax_result["tax"])
        results["net_income"].append(tax_result["net"])
        results["gross_income"].append(gross_income)
        results["effective_tax_rate"].append(tax_result["effective_rate"])

        # -------------------------
        # 6. Spending (with strategy)
        # -------------------------
        strategy = getattr(household, "drawdown_strategy", "Fixed")

        if strategy == "Fixed":
            spending = household.spending_target

        elif strategy == "Inflation-adjusted":
            spending = household.spending_target * ((1 + 0.025) ** year)

        elif strategy == "Safe Withdrawal (4%)":
            total_assets = (
                sum(a.value for a in household.assets)
                + household.person1.dc_pot
                + household.person2.dc_pot
            )
            spending = total_assets * 0.04

        else:
            spending = household.spending_target

        # -------------------------
        # 7. Drawdown if needed (with flexible PCLS / UFPLS)
        # -------------------------
        if income < spending:
            required = spending - income

            # Remaining tax-free allowance
            p1_remaining = household.person1.pcls_available - household.person1.pcls_taken
            p2_remaining = household.person2.pcls_available - household.person2.pcls_taken

            # Max tax-free allowed this year (25% of withdrawal)
            max_tax_free_this_year = required * 0.25

            # Actual tax-free draw (limited by remaining allowance)
            tax_free_draw = min(max_tax_free_this_year, max(0, p1_remaining + p2_remaining))

            # Taxable portion
            taxable_draw = required - tax_free_draw

            # Update PCLS tracking
            if tax_free_draw > 0:
                if p1_remaining >= tax_free_draw:
                    household.person1.pcls_taken += tax_free_draw
                else:
                    household.person1.pcls_taken += max(0, p1_remaining)
                    household.person2.pcls_taken += max(0, tax_free_draw - p1_remaining)

            # Reduce DC pots proportionally
            total_dc = household.person1.dc_pot + household.person2.dc_pot
            dc_draw = tax_free_draw + taxable_draw

            if total_dc > 0 and dc_draw > 0:
                p1_share = household.person1.dc_pot / total_dc
                p2_share = household.person2.dc_pot / total_dc

                household.person1.dc_pot -= dc_draw * p1_share
                household.person2.dc_pot -= dc_draw * p2_share

            # TAX CALC INCLUDING TAXABLE DRAWDOWN
            from .tax import uk_income_tax
            tax_result = uk_income_tax(
                earned_income=gross_income,
                taxable_drawdown=taxable_draw
            )

            income = tax_result["net"] + tax_free_draw

            # If still short after DC, draw from other assets
            if income < spending:
                remaining_needed = spending - income
                withdrawn, _ = drawdown_from_assets(household.assets, remaining_needed)
                income += withdrawn

            results["tax_free_income"].append(tax_free_draw)
        else:
            results["tax_free_income"].append(0)


        # -------------------------
        # 8. Net Worth
        # -------------------------
        net_worth = (
            sum(a.value for a in household.assets)
            + household.person1.dc_pot
            + household.person2.dc_pot
        )

        if household.mortgage:
            net_worth -= household.mortgage.outstanding

        # -------------------------
        # 9. Save results
        # -------------------------
        results["net_worth"].append(net_worth)
        results["income"].append(income)
        results["spending"].append(spending)

        # Asset breakdown
        isa = sum(a.value for a in household.assets if a.asset_type == "ISA")
        gia = sum(a.value for a in household.assets if a.asset_type == "GIA")
        cash = sum(a.value for a in household.assets if a.asset_type == "Cash")
        prop = sum(a.value for a in household.assets if a.asset_type == "Property")

        results["isa_value"].append(isa)
        results["gia_value"].append(gia)
        results["cash_value"].append(cash)
        results["property_value"].append(prop)

        if household.mortgage:
            results["mortgage_balance"].append(household.mortgage.outstanding)
        else:
            results["mortgage_balance"].append(0)

        results["dc_pot"].append(
            household.person1.dc_pot + household.person2.dc_pot
        )

    return results
