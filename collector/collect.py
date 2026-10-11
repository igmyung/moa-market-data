"""Stream IEX TOPS through gzip and the bounded-memory Rust collector.

Never stores the multi-GB source. Publish only after HTTP, gzip checksum, complete
session and all five quote checks succeed; failures retain the last good JSON.
"""
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse
import argparse
import hashlib
import json
import subprocess
import tempfile
from history import archive_snapshot

ROOT = Path(__file__).resolve().parent.parent
SYMBOLS = {"VOO", "SPY", "IVV", "VTI", "VT"}
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, default=ROOT / "public/prices.json")
parser.add_argument("--force", action="store_true")
args = parser.parse_args()
manifest_bytes = subprocess.check_output(["curl", "--fail", "--silent", "--show-error", "--max-time", "60", "https://iextrading.com/api/1.0/hist"])
manifest = json.loads(manifest_bytes)
today = datetime.now(timezone.utc).strftime("%Y%m%d")
dates = sorted((d for d in manifest if d.isdigit() and len(d) == 8 and d <= today), reverse=True)
record = next((r for d in dates for r in manifest[d] if r["feed"] == "TOPS" and r["version"] == "1.6" and r["protocol"] == "IEXTP1"), None)
if not record:
    raise RuntimeError("No supported IEX TOPS day")
day = datetime.strptime(record["date"], "%Y%m%d").replace(tzinfo=timezone.utc)
if (datetime.now(timezone.utc) - day).days > 14:
    raise RuntimeError("IEX source is more than 14 days old")
trading_date = day.strftime("%Y-%m-%d")
if args.output.exists() and not args.force:
    old = json.loads(args.output.read_text())
    if old.get("source") == "IEX HIST" and old.get("tradingDate") == trading_date and {q["symbol"] for q in old.get("quotes", [])} == SYMBOLS:
        archive_snapshot(args.output.with_name("history.json"), old)
        print(f"Already have complete {trading_date}; no large download needed", flush=True)
        raise SystemExit(0)
url = record["link"]
parsed = urlparse(url)
if parsed.scheme != "https" or parsed.hostname not in {"www.googleapis.com", "storage.googleapis.com", "iexpublic.blob.core.windows.net"}:
    raise RuntimeError("Unexpected IEX data host")
print(f"Processing IEX TOPS {trading_date}, {int(record['size']) / 1e9:.2f} GB compressed; streaming only", flush=True)
with tempfile.TemporaryDirectory(prefix="moa-iex-") as temp:
    binary = Path(temp) / "collector"
    subprocess.run(["rustc", "-O", "--edition", "2021", str(ROOT / "collector/main.rs"), "-o", str(binary)], check=True)
    download = subprocess.Popen(["curl", "--fail", "--silent", "--show-error", "--location", "--max-time", "5400", "--speed-time", "120", "--speed-limit", "8192", url], stdout=subprocess.PIPE)
    inflate = subprocess.Popen(["gzip", "-dc"], stdin=download.stdout, stdout=subprocess.PIPE)
    download.stdout.close()
    try:
        result = subprocess.run([str(binary), trading_date, str(int(day.timestamp()) * 1_000_000_000)], stdin=inflate.stdout, stdout=subprocess.PIPE)
    finally:
        inflate.stdout.close()
    gzip_status = inflate.wait()
    http_status = download.wait()
    if result.returncode or gzip_status or http_status:
        raise RuntimeError(f"Incomplete source: parser={result.returncode}, gzip={gzip_status}, HTTP={http_status}; retaining prior prices")
    value = json.loads(result.stdout)
    if {q["symbol"] for q in value["quotes"]} != SYMBOLS or len(value["quotes"]) != 5:
        raise RuntimeError("Missing or duplicate ETF quote")
    value["generatedAt"] = datetime.now(timezone.utc).isoformat()
    value["attribution"] = "Data provided for free by IEX. By accessing or using IEX Historical Data, you agree to the IEX Historical Data Terms of Use."
    value["termsURL"] = "https://www.iex.io/legal/hist-data-terms"
    value["sourceFileBytes"] = int(record["size"])
    value["collectorVersion"] = hashlib.sha256((ROOT / "collector/main.rs").read_bytes()).hexdigest()[:16]
    archive_snapshot(args.output.with_name("history.json"), value)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    target = args.output.with_suffix(".json.tmp")
    target.write_text(json.dumps(value, indent=2) + "\n")
    target.replace(args.output)
    print(f"Published {trading_date}: " + ", ".join(f"{q['symbol']} ${q['priceUSD']}" for q in value["quotes"]), flush=True)
