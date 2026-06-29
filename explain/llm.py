from ollama_client import ask_llm

def explain_results(sim_results, household):
    """
    Generates a natural-language explanation of the simulation results.
    """

    # Extract final values safely
    final_net_worth = sim_results["net_worth"][-1]
    peak_net_worth = max(sim_results["net_worth"])
    final_dc = sim_results["dc_pot"][-1]
    final_isa = sim_results["isa_value"][-1]
    final_gia = sim_results["gia_value"][-1]
    final_cash = sim_results["cash_value"][-1]
    final_property = sim_results["property_value"][-1]
    final_mortgage = sim_results["mortgage_balance"][-1]

    # Indexed pension income (annual sum of DB + State Pension for both
    # partners, each indexed annually by their respective growth rate). The
    # `pension_income` series was added in a recent engine revision, so
    # older `simulation_results` payloads may not have it — fall back to a
    # list of zeros so the prompt degrades gracefully instead of crashing.
    pension_series = sim_results.get(
        "pension_income",
        [0.0] * len(sim_results["years"]),
    )
    final_pension_income = pension_series[-1] if pension_series else 0.0
    peak_pension_income = max(pension_series) if pension_series else 0.0
    pension_active_from_year = next(
        (y for y, p in enumerate(pension_series) if p > 0),
        None,
    )

    # Per-partner indexation rules. These fields are also newer; legacy
    # savings fall back to the dataclass defaults (DB / SP @ 2.5%/yr).
    p1 = household.get("person1", {})
    p2 = household.get("person2", {})
    p1_db_growth = p1.get("db_growth_rate", 0.025)
    p1_sp_growth = p1.get("state_pension_growth_rate", 0.025)
    p2_db_growth = p2.get("db_growth_rate", 0.025)
    p2_sp_growth = p2.get("state_pension_growth_rate", 0.025)

    # Pre-compute conditional strings used inside the f-string template.
    # The "age at kick-in" anchor uses Person 1's age to match the Home /
    # Timeline pages' Person-1-as-anchor convention — so the LLM will quote
    # the same age value a user sees in those charts, even if only Person
    # 2's pension actual fires first.
    if pension_active_from_year is not None:
        pension_kickin_str = f"year {pension_active_from_year}"
        pension_age_at_kickin_str = (
            f" (age {p1.get('age', 55) + pension_active_from_year})"
        )
    else:
        pension_kickin_str = "never (no DB or State Pension modelled)"
        pension_age_at_kickin_str = ""

    # Build prompt
    prompt = f"""
You are an AI retirement planning assistant for a UK household.

The app is called "Shaz and Dave's Road to Retirement".

Your job is to explain the household's retirement outlook clearly, using the simulation results below.

Do NOT give regulated financial advice. You may:
- explain risks
- highlight sustainability issues
- summarise the trajectory
- describe what inputs matter most
- compare income vs spending
- explain how long assets last
- comment on state pension timing AND DB pension indexation drift
- comment on mortgage impact
- comment on drawdown sustainability

Simulation summary:
- Years simulated: {len(sim_results["years"])}
- Final net worth: £{final_net_worth:,.2f}
- Peak net worth: £{peak_net_worth:,.2f}
- Final DC pot: £{final_dc:,.2f}
- Final ISA value: £{final_isa:,.2f}
- Final GIA value: £{final_gia:,.2f}
- Final cash: £{final_cash:,.2f}
- Final property value: £{final_property:,.2f}
- Final mortgage balance: £{final_mortgage:,.2f}

Indexed pension income (DB + State Pension, each indexed annually by per-person rate):
- Pension income first appears in {pension_kickin_str}{pension_age_at_kickin_str}
- Final annual pension income at end of simulation: £{final_pension_income:,.2f}
- Peak annual pension income across the horizon: £{peak_pension_income:,.2f}
- Per-partner indexation rules used:
  - Person 1: DB @ {p1_db_growth:.2%}/yr, State Pension @ {p1_sp_growth:.2%}/yr
  - Person 2: DB @ {p2_db_growth:.2%}/yr, State Pension @ {p2_sp_growth:.2%}/yr

Household:
- Person 1: {household['person1']['name']}, age {household['person1']['age']}, retires at {household['person1']['retirement_age']}
- Person 2: {household['person2']['name']}, age {household['person2']['age']}, retires at {household['person2']['retirement_age']}
- Annual spending target: £{household['spending']:,.2f}
- Drawdown strategy: {household.get('drawdown_strategy', 'Fixed')}

Life events included:
{household.get('events', 'None')}

Please provide a clear, friendly explanation of:
1. Whether the plan looks sustainable
2. When assets peak and decline
3. Whether income covers spending
4. When State Pension and DB pension first begin paying for each person, and how their per-year indexation reshapes the household's effective income year-on-year
5. Any risks or pressure points
6. What matters most for improving the outcome
7. A simple summary for Shaz and Dave

Avoid giving advice. Focus on explanation.
"""

    return ask_llm(prompt)
