# Moa IEX reference prices

A small, independent collector for VOO, SPY, IVV, VTI and VT. It streams the free IEX HIST TOPS 1.6 capture and retains only those ETF trades, then publishes five last-sale eligible regular-session prices from a completed trading day.

These are IEX venue reference prices, not consolidated US closing prices, NAV, real-time quotes or trading signals. Reference date and actual trade timestamp travel with every quote. No portfolio data, iOS app source, personal data or API credentials are present here.

## Run

Requires Python 3, rustc, curl and gzip. No third-party packages or API key. Run `python3 tests/test_collector.py` and `python3 collector/collect.py`. The collector downloads the multi-GB source as a stream without retaining it. Successful output is only `public/prices.json`.

A public repository using the standard Ubuntu GitHub Actions runner can process daily without paid runner minutes. No artifacts or large-file caches are uploaded. A schedule runs at 07:17 UTC (16:17 Korea time), checking for the newest available completed trading day. IEX publication time is not guaranteed. Schedules are best effort and may be delayed; the app must show the trading date and stale state. Same completed day is skipped to avoid repeat large downloads. A failed HTTP request, gzip checksum, incomplete capture, missing ETF or malformed record does not overwrite the prior good result.

## Accuracy rules

Use IEX TOPS specification v1.66 and IEX-TP v1. Ignore extended-hours and odd-lot trades according to the IEX last-sale eligibility flags. Apply trade breaks and prevent duplicate replay from resurrecting canceled trades. Require End of System Hours and all five ETFs before publication. There is no fallback to an unlicensed provider or a sample price. Prices are for rough portfolio tracking, not order execution or investment decisions.

## Attribution

Data provided for free by IEX. By accessing or using IEX Historical Data, you agree to the [IEX Historical Data Terms of Use](https://www.iex.io/legal/hist-data-terms).

The original IEX data is subject to those terms; this repository does not relicense it. It contains only the narrow daily five-ETF result and the collector, never the original full capture or specification PDF.
