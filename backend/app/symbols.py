import re

from .errors import InvalidSymbol

# Always used with fullmatch (a "$" anchor would also accept a trailing newline). A leading ^ is allowed for index
# symbols such as ^GSPC (the docs list them as supported by the Yahoo provider; they used to be rejected).
SYMBOL_RE = re.compile(r"[A-Z0-9^][A-Z0-9.\-=^]{0,14}")


def normalize_symbol(raw: str) -> str:
    symbol = raw.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise InvalidSymbol(f"'{raw[:20]}' is not a valid ticker symbol")
    return symbol
