import json, struct, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
START = 1791504000 * 1_000_000_000  # 2026-10-09 UTC
SYMBOLS = ['VOO', 'SPY', 'IVV', 'VTI', 'VT']
def trade(symbol, price, ident, tick=1, flags=0, kind=b'T'):
    return kind + bytes([flags]) + struct.pack('<Q',START + tick) + symbol.encode().ljust(8,b' ') + struct.pack('<IQQ',100, price,ident)
def packet(messages):
    payload = b''.join(struct.pack('<H',len(m))+m for m in messages)
    iex = struct.pack('<BBHIIHHQQQ',1,0,0x8003,1,1,len(payload),len(messages),0,1,START) + payload
    udp = struct.pack('!HHHH',1,2,len(iex)+8,0) + iex
    ip = bytes([0x45,0]) + struct.pack('!HHH',len(udp)+20,0,0) + bytes([64,17]) + bytes(10) + udp
    eth = bytes(12)+b'\x08\x00'+ip
    return struct.pack('<IIII',0,0,len(eth),len(eth)) + eth
def capture(messages, closing=True):
    header = struct.pack('<IHHIIII',0xa1b2c3d4,2,4,0,0,65535,1)
    if closing: messages += [b'SE'+struct.pack('<Q',START+22*3600*1_000_000_000)]
    return header+packet(messages)
with tempfile.TemporaryDirectory() as tmp:
    binary=Path(tmp)/'collector'
    subprocess.run(['rustc','-O','--edition','2021',str(ROOT/'collector/main.rs'),'-o',str(binary)],check=True)
    baseline = [trade(s,1000000+i,i+1) for i,s in enumerate(SYMBOLS)]
    extras=[trade('VOO',2000000,99,tick=2),trade('VOO',2000000,99,tick=2,kind=b'B'),trade('VOO',2000000,99,tick=2),trade('VOO',9999999,100,tick=3,flags=0x40),trade('VOO',9999999,101,tick=4,flags=0x20)]
    p=subprocess.run([str(binary),'2026-10-09',str(START)],input=capture(baseline+extras),capture_output=True,check=True)
    d=json.loads(p.stdout)
    def ng_capture(classic, endian='<'):
        def block(kind,body):
            length=12+len(body)
            return struct.pack(endian+'II',kind,length)+body+struct.pack(endian+'I',length)
        shb=block(0x0a0d0d0a,struct.pack(endian+'IHHq',0x1a2b3c4d,1,0,-1))
        idb=block(1,struct.pack(endian+'HHI',1,0,65535))
        frame=classic[40:]
        epb=block(6,struct.pack(endian+'IIIII',0,0,0,len(frame),len(frame))+frame+bytes((-len(frame))%4))
        return shb+idb+epb
    for endian in ['<','>']:
        p=subprocess.run([str(binary),'2026-10-09',str(START)],input=ng_capture(capture(baseline+extras),endian),capture_output=True,check=True)
        assert json.loads(p.stdout)['quotes'][0]['priceUSD']==100

    assert len(d['quotes'])==5 and d['quotes'][0]['priceUSD']==100
    for bad in [capture(baseline,False),capture(baseline[:-1]),capture(baseline)[:-5],capture(baseline+[trade('VOO',2000000,1,tick=2)])]:
        p=subprocess.run([str(binary),'2026-10-09',str(START)],input=bad,capture_output=True)
        assert p.returncode and not p.stdout
    print('PASS: five ETF extraction, trade breaks, duplicate replay, extended/odd-lot exclusion, incomplete capture and conflicting IDs')
