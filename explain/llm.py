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
- comment on state pension timing
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
4. When state pension kicks in and its impact
5. Any risks or pressure points
6. What matters most for improving the outcome
7. A simple summary for Shaz and Dave

Avoid giving advice. Focus on explanation.
"""

    return ask_llm(prompt)
