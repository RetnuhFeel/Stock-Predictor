"""Curated universe for the 'Trending' momentum screen: ~100 liquid US large caps (static, edited by hand).

This is NOT an index and not a recommendation list. It is fixed so that the screen is cheap to compute, cacheable
and reproducible. Names are bundled so the endpoint needs no extra provider calls. Share classes use Yahoo-style
dashes (BRK-B). Review it occasionally: companies get acquired, renamed or delisted (they are simply skipped if
the provider has no data).
"""
from __future__ import annotations

UNIVERSE: list[tuple[str, str]] = [
    ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "NVIDIA"), ("AMZN", "Amazon"), ("GOOGL", "Alphabet (A)"),
    ("META", "Meta Platforms"), ("TSLA", "Tesla"), ("AVGO", "Broadcom"), ("BRK-B", "Berkshire Hathaway (B)"),
    ("JPM", "JPMorgan Chase"), ("V", "Visa"), ("MA", "Mastercard"), ("LLY", "Eli Lilly"),
    ("UNH", "UnitedHealth"), ("XOM", "Exxon Mobil"), ("CVX", "Chevron"), ("WMT", "Walmart"), ("COST", "Costco"),
    ("HD", "Home Depot"), ("PG", "Procter & Gamble"), ("JNJ", "Johnson & Johnson"), ("ABBV", "AbbVie"),
    ("MRK", "Merck"), ("PFE", "Pfizer"), ("TMO", "Thermo Fisher"), ("ABT", "Abbott"), ("DHR", "Danaher"),
    ("AMGN", "Amgen"), ("GILD", "Gilead Sciences"), ("BMY", "Bristol-Myers Squibb"),
    ("ISRG", "Intuitive Surgical"), ("ORCL", "Oracle"), ("CRM", "Salesforce"), ("ADBE", "Adobe"),
    ("NFLX", "Netflix"), ("AMD", "AMD"), ("INTC", "Intel"), ("QCOM", "Qualcomm"), ("TXN", "Texas Instruments"),
    ("MU", "Micron"), ("AMAT", "Applied Materials"), ("LRCX", "Lam Research"), ("KLAC", "KLA"),
    ("ADI", "Analog Devices"), ("CSCO", "Cisco"), ("IBM", "IBM"), ("NOW", "ServiceNow"), ("INTU", "Intuit"),
    ("PANW", "Palo Alto Networks"), ("PLTR", "Palantir"), ("UBER", "Uber"), ("SHOP", "Shopify"),
    ("BKNG", "Booking Holdings"), ("ABNB", "Airbnb"), ("MELI", "MercadoLibre"), ("BAC", "Bank of America"),
    ("WFC", "Wells Fargo"), ("C", "Citigroup"), ("GS", "Goldman Sachs"), ("MS", "Morgan Stanley"),
    ("BLK", "BlackRock"), ("SCHW", "Charles Schwab"), ("AXP", "American Express"), ("SPGI", "S&P Global"),
    ("PYPL", "PayPal"), ("COF", "Capital One"), ("USB", "U.S. Bancorp"), ("KO", "Coca-Cola"),
    ("PEP", "PepsiCo"), ("MCD", "McDonald's"), ("SBUX", "Starbucks"), ("NKE", "Nike"), ("DIS", "Disney"),
    ("CMCSA", "Comcast"), ("T", "AT&T"), ("VZ", "Verizon"), ("TMUS", "T-Mobile US"), ("LOW", "Lowe's"),
    ("TGT", "Target"), ("TJX", "TJX Companies"), ("MDLZ", "Mondelez"), ("PM", "Philip Morris"),
    ("MO", "Altria"), ("CL", "Colgate-Palmolive"), ("CAT", "Caterpillar"), ("DE", "Deere"), ("BA", "Boeing"),
    ("HON", "Honeywell"), ("GE", "GE Aerospace"), ("RTX", "RTX"), ("LMT", "Lockheed Martin"), ("UPS", "UPS"),
    ("UNP", "Union Pacific"), ("LIN", "Linde"), ("NEE", "NextEra Energy"), ("DUK", "Duke Energy"),
    ("COP", "ConocoPhillips"), ("SLB", "Schlumberger"), ("F", "Ford"), ("GM", "General Motors"), ("MMM", "3M"),
    ("ACN", "Accenture"), ("MCK", "McKesson"), ("CVS", "CVS Health"), ("CI", "Cigna"),
    ("ELV", "Elevance Health"),
]

SYMBOLS: list[str] = [s for s, _ in UNIVERSE]
NAMES: dict[str, str] = dict(UNIVERSE)
assert len(SYMBOLS) == len(set(SYMBOLS)), "duplicate ticker in UNIVERSE"
