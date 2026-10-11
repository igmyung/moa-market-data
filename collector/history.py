"""Archive validated daily public ETF data only. Never accepts portfolio data."""
from pathlib import Path
from datetime import datetime, timezone
import json
import math

SYMBOLS = {"VOO", "SPY", "IVV", "VTI", "VT"}
ATTRIBUTION = "Data provided for free by IEX. By accessing or using IEX Historical Data, you agree to the IEX Historical Data Terms of Use."
TERMS = "https://www.iex.io/legal/hist-data-terms"

def validate_snapshot(value):
    if value.get("schemaVersion") != 1 or value.get("source") != "IEX HIST" or value.get("priceKind") != "iex_regular_session_last_sale":
        raise ValueError("Unknown price snapshot source")
    day = datetime.strptime(value["tradingDate"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if day.strftime("%Y-%m-%d") != value["tradingDate"] or day > datetime.now(timezone.utc):
        raise ValueError("Invalid trading day")
    quotes = value.get("quotes", [])
    if len(quotes) != 5 or {q["symbol"] for q in quotes} != SYMBOLS:
        raise ValueError("Incomplete daily ETF data")
    start = int(day.timestamp()) * 1_000_000_000
    for q in quotes:
        price = q["priceUSD"]
        timestamp = q["timestampNs"]
        if isinstance(price, bool) or not isinstance(price, (float, int)) or not math.isfinite(price) or not 0 < price <= 1_000_000:
            raise ValueError("Invalid ETF price")
        if not isinstance(timestamp, str) or not timestamp.isdigit() or not start <= int(timestamp) < start + 86_400_000_000_000:
            raise ValueError("Trade timestamp outside trading day")
    return value

def archive_snapshot(path: Path, value: dict) -> bool:
    validate_snapshot(value)
    def public_row(row):
        quotes = []
        for q in row["quotes"]:
            quotes.append({k: q[k] for k in ("symbol", "priceUSD", "timestampNs", "tradeId") if k in q})
        return {"tradingDate": row["tradingDate"], "quotes": quotes,
                "generatedAt": row["generatedAt"], "collectorVersion": row["collectorVersion"]}
    days = {}
    if path.exists():
        prior = json.loads(path.read_text())
        if prior.get("schemaVersion") != 1 or prior.get("source") != "IEX HIST" or prior.get("priceKind") != value["priceKind"]:
            raise ValueError("Invalid price archive; preserving the prior file")
        for row in prior["snapshots"]:
            validate_snapshot({"schemaVersion": 1, "source": "IEX HIST", "priceKind": value["priceKind"], **row})
            if row["tradingDate"] in days:
                raise ValueError("Duplicate trading date in archive")
            days[row["tradingDate"]] = public_row(row)
    # Explicit whitelist: this file contains only provider data, never app snapshots.
    row = public_row(value)
    if days.get(row["tradingDate"]) == row:
        return False
    days[row["tradingDate"]] = public_row(row)
    history = {"schemaVersion": 1, "source": "IEX HIST", "priceKind": value["priceKind"],
               "attribution": ATTRIBUTION, "termsURL": TERMS,
               "snapshots": [days[d] for d in sorted(days)]}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(history, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)
    return True
