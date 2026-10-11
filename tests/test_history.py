from pathlib import Path
from datetime import datetime, timezone
import sys, json, tempfile, copy
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "collector"))
from history import archive_snapshot

def sample(day):
    ns = str(int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) * 1_000_000_000)
    return {"schemaVersion":1,"source":"IEX HIST","priceKind":"iex_regular_session_last_sale",
            "tradingDate":day,"generatedAt":"test","collectorVersion":"test",
            "quotes":[{"symbol":s,"priceUSD":100,"timestampNs":ns} for s in ("VOO","SPY","IVV","VTI","VT")]}

with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/"history.json"
    first, second=sample("2020-01-02"), sample("2020-01-03")
    assert archive_snapshot(path,first)
    assert not archive_snapshot(path,first)
    assert archive_snapshot(path,second)
    assert [x["tradingDate"] for x in json.loads(path.read_text())["snapshots"]] == ["2020-01-02","2020-01-03"]
    correction=copy.deepcopy(first);correction["quotes"][0]["priceUSD"]=101
    assert archive_snapshot(path,correction)
    assert len(json.loads(path.read_text())["snapshots"]) == 2
    injected=copy.deepcopy(second)
    injected["goalShares"]=666
    injected["quotes"][0]["baseShares"]=666
    archive_snapshot(path,injected)
    assert "goalShares" not in path.read_text() and "baseShares" not in path.read_text()
    before=path.read_bytes()
    for change in ({"quotes":[]},{"source":"other"},{"tradingDate":"2099-01-01"}):
        invalid={**second,**change}
        try: archive_snapshot(path,invalid)
        except ValueError: pass
        else: raise AssertionError("Invalid daily data was accepted")
        assert path.read_bytes()==before
    broken=json.loads(before);broken["snapshots"][0]["quotes"] = []
    path.write_text(json.dumps(broken));before=path.read_bytes()
    try: archive_snapshot(path,second)
    except ValueError: pass
    else: raise AssertionError("Corrupt existing history was overwritten")
    assert path.read_bytes()==before
print("PASS: daily ETF archive retention, idempotence, corrections and invalid-data preservation")
