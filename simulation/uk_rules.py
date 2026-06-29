from dataclasses import dataclass


@dataclass
class TaxBand:
    name: str
    lower: int
    upper: int | None
    rate: float  # e.g. 0.20 for 20%


@dataclass
class UkFinanceRules:
    tax_bands: list[TaxBand]
    personal_allowance: int
    ni_primary_threshold: int
    ni_upper_earnings_limit: int
    ni_main_rate: float
    ni_upper_rate: float
    state_pension_weekly: float
    mpaa: int
    annual_allowance: int
    isa_limit: int


def get_uk_rules() -> UkFinanceRules:
    """
    Static snapshot of UK rules.
    You can later replace this with live gov.uk scraping or an API.
    """
    tax_bands = [
        TaxBand("Basic rate", lower=12_571, upper=50_270, rate=0.20),
        TaxBand("Higher rate", lower=50_271, upper=125_140, rate=0.40),
        TaxBand("Additional rate", lower=125_141, upper=None, rate=0.45),
    ]

    return UkFinanceRules(
        tax_bands=tax_bands,
        personal_allowance=12_570,
        ni_primary_threshold=12_570,
        ni_upper_earnings_limit=50_270,
        ni_main_rate=0.08,
        ni_upper_rate=0.02,
        state_pension_weekly=221.20,  # update as needed
        mpaa=10_000,
        annual_allowance=60_000,
        isa_limit=20_000,
    )


def format_uk_rules_for_llm(rules: UkFinanceRules) -> str:
    """
    Turn the rules into a readable text block for the LLM.
    """
    lines: list[str] = []

    lines.append(f"Personal allowance: £{rules.personal_allowance:,}")
    lines.append("Income tax bands:")
    for band in rules.tax_bands:
        upper = "and above" if band.upper is None else f"to £{band.upper:,}"
        lines.append(
            f" - {band.name}: from £{band.lower:,} {upper} at {band.rate*100:.1f}%"
        )

    lines.append(
        f"National Insurance: main rate {rules.ni_main_rate*100:.1f}% "
        f"up to £{rules.ni_upper_earnings_limit:,}, "
        f"then {rules.ni_upper_rate*100:.1f}% above."
    )
    lines.append(
        f"Full new State Pension (weekly): £{rules.state_pension_weekly:.2f}"
    )
    lines.append(f"Money Purchase Annual Allowance (MPAA): £{rules.mpaa:,}")
    lines.append(f"Annual Allowance: £{rules.annual_allowance:,}")
    lines.append(f"ISA annual limit: £{rules.isa_limit:,}")

    return "\n".join(lines)
