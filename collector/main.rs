use std::{collections::{HashMap, HashSet}, io::{self, Read, BufReader}, process};
const SYMBOLS: [&str; 5] = ["VOO", "SPY", "IVV", "VTI", "VT"];
fn u16le(b: &[u8]) -> u16 { u16::from_le_bytes(b[..2].try_into().unwrap()) }
fn u32le(b: &[u8]) -> u32 { u32::from_le_bytes(b[..4].try_into().unwrap()) }
fn u64le(b: &[u8]) -> u64 { u64::from_le_bytes(b[..8].try_into().unwrap()) }
#[derive(Clone, Copy, PartialEq, Eq)]
struct Trade { symbol: usize, price: u64, time: u64, id: u64 }
fn fail(s: &str) -> ! { eprintln!("Invalid IEX capture: {s}"); process::exit(1) }
fn main() {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 { fail("expected trading date and UTC day-start nanoseconds") }
    let date = &args[1];
    let start: u64 = args[2].parse().unwrap_or_else(|_| fail("bad date boundary"));
    let end = start + 86_400_000_000_000;
    let reader = BufReader::with_capacity(4 * 1024 * 1024, io::stdin().lock());
    let mut capture = Capture::new(reader);
    let mut trades: HashMap<u64, Trade> = HashMap::new();
    let mut broken = HashSet::new();
    let mut final_event = false;
    let mut packets = 0u64;
    let mut bytes = 24u64;
    let mut packet = vec![0u8; 65536];
    while let Some(size) = capture.next(&mut packet) {
        let p = &packet[..size];
        packets += 1; bytes += size as u64 + 16;
        if packets % 5_000_000 == 0 { eprintln!("Processed {packets} packets, {bytes} bytes, {} target trades",trades.len()); }
        if size < 14 { continue }
        let mut ip = 14;
        let mut kind = u16::from_be_bytes(p[12..14].try_into().unwrap());
        while kind == 0x8100 || kind == 0x88a8 {
            if size < ip + 4 { fail("short vlan frame") }
            kind = u16::from_be_bytes(p[ip+2..ip+4].try_into().unwrap()); ip += 4;
        }
        if kind != 0x0800 || size < ip + 20 || p[ip] >> 4 != 4 || p[ip+9] != 17 { continue }
        let ihl = (p[ip] as usize & 15) * 4;
        let udp = ip + ihl;
        if ihl < 20 || size < udp + 8 { fail("invalid IPv4 UDP header") }
        // Capture files contain complete UDP frames; reject fragmentation instead of guessing.
        let frag = u16::from_be_bytes(p[ip+6..ip+8].try_into().unwrap());
        if frag & 0x3fff != 0 { fail("fragmented UDP datagram") }
        let udp_size = u16::from_be_bytes(p[udp+4..udp+6].try_into().unwrap()) as usize;
        if udp_size < 8 || size < udp + udp_size { fail("invalid UDP length") }
        let body = &p[udp+8..udp+udp_size];
        if body.len() < 40 || body[0] != 1 || u16le(&body[2..]) != 0x8003 { continue }
        let length = u16le(&body[12..]) as usize;
        let count = u16le(&body[14..]) as usize;
        if body.len() != 40 + length { fail("IEX payload length mismatch") }
        let mut pos = 40;
        for _ in 0..count {
            if pos + 2 > body.len() { fail("short message length") }
            let n = u16le(&body[pos..]) as usize; pos += 2;
            if n == 0 || pos + n > body.len() { fail("short IEX message") }
            let m = &body[pos..pos+n]; pos += n;
            if m[0] == b'S' && n == 10 && m[1] == b'E' {
                let t = u64le(&m[2..]);
                if t >= start && t < end + 28_800_000_000_000 { final_event = true }
            }
            if (m[0] != b'T' && m[0] != b'B') || n != 38 { continue }
            let symbol = SYMBOLS.iter().position(|s| m[10..18].iter().copied().take_while(|c| *c != b' ').eq(s.bytes()));
            let Some(symbol) = symbol else { continue };
            let id = u64le(&m[30..]);
            if m[0] == b'B' { trades.remove(&id); broken.insert(id); continue }
            // IEX last-sale eligible: regular session and round/mixed lot, per TOPS Appendix A.
            if m[1] & 0x60 != 0 || broken.contains(&id) { continue }
            let time = u64le(&m[2..]); let price = u64le(&m[22..]);
            if time < start || time >= end || price == 0 || price > 10_000_000_000 || u32le(&m[18..]) == 0 { fail("invalid target trade/date/price") }
            let trade = Trade {symbol, price, time, id};
            if let Some(old) = trades.insert(id,trade) { if old != trade { fail("conflicting duplicate trade ID") } }
        }
        if pos != body.len() { fail("IEX message count mismatch") }
    }
    if !final_event { fail("missing End of System event; will not publish incomplete day") }
    let mut latest: [Option<Trade>; 5] = [None;5];
    for t in trades.values() {
        if latest[t.symbol].map_or(true, |old| (t.time,t.id) > (old.time,old.id)) { latest[t.symbol] = Some(*t) }
    }
    if latest.iter().any(Option::is_none) { fail("one or more required ETFs have no eligible trade") }
    println!("{{\"schemaVersion\":1,\"source\":\"IEX HIST\",\"priceKind\":\"iex_regular_session_last_sale\",\"tradingDate\":\"{date}\",\"quotes\":[");
    for (i,t) in latest.iter().enumerate() {
        let t = t.unwrap();
        println!("{{\"symbol\":\"{}\",\"priceUSD\":{}.{:04},\"timestampNs\":\"{}\",\"tradeId\":\"{}\"}}{}",SYMBOLS[i],t.price/10000,t.price%10000,t.time,t.id,if i==4 {""} else {","});
    }
    println!("]}}");
    eprintln!("Complete: {packets} packets, {bytes} decoded bytes, {} eligible ETF trades",trades.len());
}

// Modern IEX files are merged PCAPNG; older captures use classic PCAP.
struct Capture<R: Read> { reader: R, ng: bool, big: bool, first: Option<[u8;4]>, interfaces: Vec<u16>, block: Vec<u8> }
impl<R: Read> Capture<R> {
    fn new(mut reader: R) -> Self {
        let mut magic = [0u8;4];
        reader.read_exact(&mut magic).unwrap_or_else(|_| fail("missing capture header"));
        let ng = magic == [0x0a,0x0d,0x0d,0x0a];
        if !ng {
            if !matches!(magic, [0xd4,0xc3,0xb2,0xa1] | [0x4d,0x3c,0xb2,0xa1]) { fail("unsupported pcap magic") }
            let mut rest=[0u8;20];
            reader.read_exact(&mut rest).unwrap_or_else(|_| fail("short pcap header"));
            if u32le(&rest[16..]) != 1 { fail("unsupported classic link type") }
        }
        Self { reader, ng, big:false, first:if ng {Some(magic)} else {None}, interfaces:vec![], block:vec![] }
    }
    fn num(&self, b:&[u8]) -> u32 { if self.big {u32::from_be_bytes(b[..4].try_into().unwrap())} else {u32le(b)} }
    fn next(&mut self, packet:&mut Vec<u8>) -> Option<usize> {
        loop {
            if !self.ng {
                let mut header=[0u8;16];
                if self.reader.read(&mut header[..1]).unwrap_or_else(|_| fail("pcap read error")) == 0 {return None}
                self.reader.read_exact(&mut header[1..]).unwrap_or_else(|_| fail("short pcap record"));
                let n=u32le(&header[8..]) as usize;
                if n>65536 || n != u32le(&header[12..]) as usize {fail("invalid classic capture length")}
                self.reader.read_exact(&mut packet[..n]).unwrap_or_else(|_| fail("short pcap packet"));
                return Some(n)
            }
            let mut header=[0u8;8];
            if let Some(first)=self.first.take() {header[..4].copy_from_slice(&first);self.reader.read_exact(&mut header[4..]).unwrap_or_else(|_| fail("short initial section"));}
            else {
                if self.reader.read(&mut header[..1]).unwrap_or_else(|_| fail("pcapng read error"))==0 {return None}
                self.reader.read_exact(&mut header[1..]).unwrap_or_else(|_| fail("short block header"));
            }
            let section=header[..4]==[0x0a,0x0d,0x0d,0x0a];
            let mut bom=[0u8;4];
            if section {
                self.reader.read_exact(&mut bom).unwrap_or_else(|_| fail("missing byte order magic"));
                self.big=match bom { [0x4d,0x3c,0x2b,0x1a]=>false, [0x1a,0x2b,0x3c,0x4d]=>true,_=>fail("bad pcapng byte order")};
                self.interfaces.clear();
            }
            let n=self.num(&header[4..]) as usize;
            if n<12 || n>16*1024*1024 || n%4!=0 {fail("invalid pcapng block size")}
            self.block.resize(n-8,0);
            let offset=if section {self.block[..4].copy_from_slice(&bom);4} else {0};
            self.reader.read_exact(&mut self.block[offset..]).unwrap_or_else(|_| fail("truncated pcapng block"));
            if self.num(&self.block[n-12..]) != n as u32 {fail("pcapng trailing block size mismatch")}
            let kind=self.num(&header[..4]);
            if section { if n<28 {fail("short section")};continue }
            if kind==1 {
                if n<20 {fail("short interface")}
                let link=if self.big {u16::from_be_bytes(self.block[..2].try_into().unwrap())} else {u16le(&self.block)};
                self.interfaces.push(link);continue
            }
            if kind==6 {
                if n<32 {fail("short enhanced packet")}
                let iface=self.num(&self.block) as usize;
                let len=self.num(&self.block[12..]) as usize;
                if self.interfaces.get(iface)!=Some(&1) || len>65536 || len != self.num(&self.block[16..]) as usize || 20+len>n-12 {fail("invalid enhanced packet/interface")}
                packet[..len].copy_from_slice(&self.block[20..20+len]);return Some(len)
            }
            if kind==2 || kind==3 {fail("unsupported packet block variant; will not silently skip quotes")}
        }
    }
}
