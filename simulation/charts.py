import pandas as pd

def net_worth_chart(simulation_results):
    df = pd.DataFrame({
        "Year": simulation_results["years"],
        "Net Worth": simulation_results["net_worth"]
    })
    return df

def income_vs_spending_chart(simulation_results):
    df = pd.DataFrame({
        "Year": simulation_results["years"],
        "Income": simulation_results["income"],
        "Spending": simulation_results["spending"]
    })
    return df
