from typing import Any

from ollama_client import ask_llm
from uk_rules import get_uk_rules, format_uk_rules_for_llm


def build_analysis_prompt(simulation_output: dict[str, Any]) -> str:
    """
    Combine UK rules and simulation results into a single prompt for the LLM.
    `simulation_output` is whatever structure your pension engine produces.
    """
    rules = get_uk_rules()
    rules_text = format_uk_rules_for_llm(rules)

    return f"""
You are a UK-focused retirement planning assistant.

Here are the current UK tax and pension rules:
{rules_text}

Here are the user's simulated retirement results (income, pots, withdrawals, tax, NI, state pension, etc.):
{simulation_output}

Task:
1. Explain whether the projected retirement income is sustainable.
2. Explain how UK tax bands and NI affect their net income.
3. Explain how state pension interacts with their private pensions.
4. Highlight any risks (e.g. MPAA, Annual Allowance, sequencing risk, longevity risk).
5. Suggest practical, UK-appropriate actions they might consider (without giving regulated advice).

Use clear, plain English. Refer explicitly to UK rules where relevant.
"""


def run_ai_analysis(simulation_output: dict[str, Any]) -> str:
    """
    High-level entry point: build prompt, call LLM, return analysis text.
    """
    prompt = build_analysis_prompt(simulation_output)
    return ask_llm(prompt)
