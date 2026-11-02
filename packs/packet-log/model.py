"""packet-log domain pack: a recording of AX.25 packet radio as data, and the operator policy's truth with a
switch per rule.

A capture is a list of transmissions placed on a time line. Each transmission is a frame (bytes, built here
with its FCS), a start time, a level, and a corruption mode. The truth is computed from this list and the
frame bit counts, never from audio: `truth(off=...)` answers as an agent would if it ignored the rules in
`off`; those answers are the mutants the builder uses to prove each rule is tested and to attribute failures.
"""
from __future__ import annotations

import copy
import re

MARK, SPACE, BAUD = 1200, 2200, 1200
RATES = (8000, 11025, 22050, 44100, 48000)
DUP_WINDOW_MS = 30_000
TOL_MS = 50
PREAMBLE_FLAGS = 16   # TXDELAY: flags sent before the first frame of a burst
TAIL_FLAGS = 2        # flags after the last frame of a burst
UI, PID_APRS = 0x03, 0xF0

# ------------------------------------------------------------------ AX.25 bytes and bits


def crc16_x25(data: bytes) -> int:
    c = 0xFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if c & 1 else c >> 1
    return c ^ 0xFFFF


def encode_address(call: str, ssid: int, last: bool, top: bool = False) -> bytes:
    """Seven address octets: six shifted characters and the SSID octet (bit 7 = C or H, bits 5 and 6 set)."""
    b = bytearray(ord(ch) << 1 for ch in call.ljust(6)[:6])
    b.append((0x80 if top else 0) | 0x60 | ((ssid & 0x0F) << 1) | (1 if last else 0))
    return bytes(b)


def frame_bytes(src, dst, path, control=UI, pid=PID_APRS, info: bytes = b"") -> bytes:
    """A complete frame with its FCS. src, dst: (call, ssid). path: list of (call, ssid, h)."""
    out = encode_address(dst[0], dst[1], last=False, top=True)
    out += encode_address(src[0], src[1], last=not path)
    for i, (call, ssid, h) in enumerate(path):
        out += encode_address(call, ssid, last=i == len(path) - 1, top=h)
    out += bytes([control])
    if pid is not None:
        out += bytes([pid])
    out += info
    fcs = crc16_x25(out)
    return out + bytes([fcs & 0xFF, fcs >> 8])


def parse_frame(fr: bytes):
    """Fields of a frame whose FCS matches, else None. Raw info bytes; the policy's reading is elsewhere."""
    if len(fr) < 17 or crc16_x25(fr[:-2]) != fr[-2] | (fr[-1] << 8):
        return None
    body = fr[:-2]
    addrs, i = [], 0
    while i + 7 <= len(body) and len(addrs) < 10:
        a = body[i:i + 7]
        addrs.append(("".join(chr(c >> 1) for c in a[:6]).strip(), (a[6] >> 1) & 0x0F, bool(a[6] & 0x80)))
        i += 7
        if a[6] & 1:
            break
    if len(addrs) < 2 or i > len(body):
        return None
    control = body[i]
    is_ui = (control & 0xEF) == UI
    pid = body[i + 1] if is_ui and i + 1 < len(body) else None
    info = body[i + 2:] if is_ui else body[i + 1:]
    return {"destination": addrs[0][:2], "source": addrs[1][:2], "path": addrs[2:], "control": control,
            "pid": pid, "info": bytes(info)}


def hdlc_bits(fr: bytes, corrupt: str | None = None, rng=None) -> list[int]:
    """The frame's bits after stuffing, LSB first. 'flip' turns one data bit over before stuffing (a bit error on
    the air: the FCS no longer matches); 'abort' cuts the frame short and sends seven ones."""
    raw = [(b >> k) & 1 for b in fr for k in range(8)]
    if corrupt == "flip":
        j = rng.randrange(16, len(raw) - 16)
        raw[j] ^= 1
    if corrupt == "abort":
        raw = raw[: rng.randrange(len(raw) // 3, 2 * len(raw) // 3)]
    out, run = [], 0
    for b in raw:
        out.append(b)
        run = run + 1 if b else 0
        if run == 5:
            out.append(0)
            run = 0
    if corrupt == "abort":
        out += [1] * 8
    return out


FLAG = [0, 1, 1, 1, 1, 1, 1, 0]


def burst_bits(frames: list[tuple[bytes, str | None]], rng) -> tuple[list[int], list[int]]:
    """Bits of one keyed transmission holding one or more frames, and the bit index at which each frame's
    closing flag ends."""
    bits = FLAG * PREAMBLE_FLAGS
    ends = []
    for fr, corrupt in frames:
        bits += hdlc_bits(fr, corrupt, rng)
        bits += FLAG
        ends.append(len(bits))
    bits += FLAG * (TAIL_FLAGS - 1)
    return bits, ends


# ------------------------------------------------------------------ the policy's reading of a frame


def fmt_call(call: str, ssid: int) -> str:
    return f"{call}-{ssid}" if ssid else call


def fmt_path(path, off=frozenset()) -> list[str]:
    """Rule 3: `*` after the last address whose H bit is set. Mutant: `*` on every repeated address."""
    out = [fmt_call(c, s) for c, s, _ in path]
    hs = [i for i, (_, _, h) in enumerate(path) if h]
    if 3 in off:
        for i in hs:
            out[i] += "*"
    elif hs:
        out[hs[-1]] += "*"
    return out


MSG_RE = re.compile(rb"^:(.{9}):(.*)$", re.S)
ID_RE = re.compile(rb"\{([A-Za-z0-9]{1,5})$")
ACK_RE = re.compile(rb"^ack([A-Za-z0-9]{1,5})$")


def read_message(info: bytes):
    m = MSG_RE.match(info)
    if not m:
        return None
    to, text = m.group(1).decode("latin-1").strip(), m.group(2)
    a = ACK_RE.match(text)
    if a:
        return {"to": to, "ack": a.group(1).decode("latin-1")}
    i = ID_RE.search(text)
    return {"to": to, "id": i.group(1).decode("latin-1") if i else None,
            "text": (text[: i.start()] if i else text).decode("latin-1")}


def kind_of(control: int, pid, info: bytes, off=frozenset()) -> str:
    """Rule 4. Mutant: every frame is read as APRS."""
    if ((control & 0xEF) != UI or pid != PID_APRS) and 4 not in off:
        return "non_aprs"
    if not info:
        return "other"
    c = chr(info[0])
    if c in "!=/@":
        return "position"
    if c == ">":
        return "status"
    if c == ":":
        m = read_message(info)
        if m is None:
            return "other"
        return "ack" if "ack" in m else "message"
    return "other"


# ------------------------------------------------------------------ catalogue

CALLS = ["N0CALL", "KD6XYZ", "W6ABC", "K7JQR", "N6PLM", "WA6TTX", "KJ6HOP", "AE7RW", "KI7MDV", "W1AW",
         "VE7LKJ", "N2QRS", "KC3UVW", "W4DEF", "N8GHI"]
DESTS = ["APDR16", "APRS", "APN391", "APWW11", "APZ001", "APK004", "APU25N", "APOT30"]
PATHS = [[], [("WIDE1", 1, False), ("WIDE2", 1, False)], [("WIDE2", 2, False)], [("WIDE1", 1, True)],
         [("TCPIP", 0, True)], [("K6DIG", 3, True), ("WIDE2", 1, False)]]
STATUS = ["Mobile, monitoring 146.52", "QRV on 2m", "Testing new antenna", "Back in the shack", "Net control tonight",
          "Portable from the ridge", "APRS-IS gate up", "73 de the mountain"]
COMMENTS = ["Test packet one", "PHG5130 Digi", "Heading north on the 5", "Weather station", "Fill-in digi",
            "Lunch stop", "Battery 12.6V", "Grid DM04", ""]
TEXTS = ["hello", "QSL your last", "Meet at the repeater at 7", "Copy all, thanks", "What is your grid?",
         "Antenna is up", "Call me on the phone", "See you at the hamfest"]
LATIN1 = ["Café open, 73", "Nächster Halt Zürich", "Señal fuerte aquí", "Temp 23°C"]

HOUSES = {
    # rate, sample bits, channels, signal level, twist in dB at 2 kHz (positive: space louder), DC offset,
    # most clock drift of the sender's TNC
    "tnc2": dict(rate=44100, bits=16, channels=1, level=0.5, twist=0.0, dc=0.0, drift=0.0, limiter=False),
    "handheld": dict(rate=22050, bits=16, channels=1, level=0.85, twist=6.0, dc=0.08, drift=0.0, limiter=True),
    "sdr": dict(rate=48000, bits=16, channels=2, level=0.25, twist=0.0, dc=0.0, drift=0.0, limiter=False),
    "mobile": dict(rate=11025, bits=8, channels=1, level=0.5, twist=-6.0, dc=0.0, drift=0.01, limiter=False),
}

ROUTES = ("clean", "noise_lo", "noise_hi", "twist", "qsb", "drift", "multipath", "header_lie", "stereo_decoy",
          "stack")
READING_ROUTES = {"noise_hi", "twist", "qsb", "drift", "multipath", "stack"}


def position_info(rng, lead="!"):
    lat = f"{rng.randint(30, 48):02d}{rng.uniform(0, 59.99):05.2f}N"
    lon = f"{rng.randint(70, 124):03d}{rng.uniform(0, 59.99):05.2f}W"
    return f"{lead}{lat}/{lon}{rng.choice('>-_k[')}{rng.choice(COMMENTS)}".encode("latin-1")


def message_info(to: str, text: str, msg_id: str | None) -> bytes:
    return f":{to:<9}:{text}{'{' + msg_id if msg_id else ''}".encode("latin-1")


def ack_info(to: str, msg_id: str) -> bytes:
    return f":{to:<9}:ack{msg_id}".encode("latin-1")


# ------------------------------------------------------------------ the capture

class Tx:
    """One frame on the air. `t0` is the start of its burst in seconds; frames in one burst share flags."""

    def __init__(self, src, dst, path, info, control=UI, pid=PID_APRS, corrupt=None, level=1.0, decoy=False):
        self.src, self.dst, self.path, self.info = src, dst, list(path), info
        self.control, self.pid, self.corrupt, self.level, self.decoy = control, pid, corrupt, level, decoy
        self.t0 = 0.0
        self.burst_with_prev = False
        self.end_bits = 0        # set by schedule(): bit index of the closing flag's end within the burst
        self.burst_start = 0.0   # seconds

    @property
    def bytes(self) -> bytes:
        return frame_bytes(self.src, self.dst, self.path, self.control, self.pid, self.info)

    def tnc2(self) -> str:
        p = fmt_path(self.path)
        return f"{fmt_call(*self.src)}>{fmt_call(*self.dst)}" + ("," + ",".join(p) if p else "") + ":" + \
            self.info.decode("latin-1")


def min_units(features: set[str]) -> int:
    """The fewest valid frames a capture with these features can report."""
    n = 0
    for f in features:
        n += {"dup_retry": 2, "dup_late": 2, "near_dup": 2, "pos_dup": 2, "msg_ack": 2, "msg_retry": 3,
              "ack_other": 2, "pos_update": 2}.get(f, 1 if f in ONE_SLOT else 0)
    if features & {"shared_flag", "quiet_tx"}:
        n = max(n, 2)
    return max(n, 1)


ONE_SLOT = {"msg_noid", "digi_h", "ssid_hi", "non_ui", "pid_other", "status_frame", "long_info", "latin1"}


class Capture:
    """Everything that goes on the air, and the truth derived from it."""

    def __init__(self, cid, house, rng, n_units, features, route):
        self.id, self.house_key, self.house, self.rng = cid, house, HOUSES[house], rng
        self.features, self.route, self.n = set(features), route, n_units
        if n_units < min_units(self.features):
            raise ValueError(f"{sorted(self.features)} need {min_units(self.features)} frames, {n_units} given")
        self.station = rng.choice(CALLS)
        self.stations = [c for c in CALLS if c != self.station]
        rng.shuffle(self.stations)
        self.rate = self.house["rate"]
        self.declared_rate = self.rate
        self.channels = self.house["channels"]
        self.radio_channel = 0
        self.baud = BAUD
        self.txs: list[Tx] = []
        self.decoys: list[Tx] = []
        self.log_lines: list[str] | None = None
        self.params = {}
        self._compose()
        self._route()
        self.schedule()
        self._log()

    # composition ---------------------------------------------------
    def _station(self, i, ssid=None):
        call = self.stations[i % len(self.stations)]
        return (call, self.rng.choice([0, 0, 1, 2, 5, 7, 9]) if ssid is None else ssid)

    def _random_tx(self, i):
        rng = self.rng
        src, dst, path = self._station(i), (rng.choice(DESTS), 0), rng.choice(PATHS)
        k = rng.random()
        if k < 0.5:
            info = position_info(rng, rng.choice("!="))
        elif k < 0.75:
            info = (">" + rng.choice(STATUS)).encode("latin-1")
        else:
            info = message_info(self.station, rng.choice(TEXTS), f"{rng.randint(1, 99):02d}" if rng.random() < 0.7 else None)
        return Tx(src, dst, path, info)

    def _compose(self):
        rng, f = self.rng, self.features
        txs: list[Tx] = []
        later: list[tuple[Tx, float, Tx]] = []     # (frame, seconds after its original, the original)
        i = 0
        if "msg_ack" in f or "ack_other" in f or "msg_retry" in f:
            src, mid = self._station(i), f"{rng.randint(1, 99):02d}"
            i += 1
            msg = Tx(src, (rng.choice(DESTS), 0), rng.choice(PATHS), message_info(self.station, rng.choice(TEXTS), mid))
            txs.append(msg)
            if "msg_retry" in f:
                dup_after = rng.uniform(8, 20)
                later.append((copy.deepcopy(msg), dup_after, msg))                       # a duplicate (within 30 s)
                later.append((copy.deepcopy(msg), dup_after + rng.uniform(31, 36), msg))  # a retry (a new frame)
            if "msg_ack" in f:
                ack = Tx((self.station, 0), (rng.choice(DESTS), 0), [], ack_info(fmt_call(*src), mid))
                later.append((ack, rng.uniform(2, 6), msg))
            if "ack_other" in f:
                other = f"{(int(mid) % 99) + 1:02d}"
                ack = Tx((self.station, 0), (rng.choice(DESTS), 0), [], ack_info(fmt_call(*src), other))
                later.append((ack, rng.uniform(2, 6), msg))
        if "msg_noid" in f:
            txs.append(Tx(self._station(i), (rng.choice(DESTS), 0), rng.choice(PATHS),
                          message_info(self.station, rng.choice(TEXTS), None)))
            i += 1
        if "pos_update" in f or "pos_dup" in f:
            src = self._station(i)
            i += 1
            p1 = Tx(src, (rng.choice(DESTS), 0), rng.choice(PATHS), position_info(rng, "="))
            txs.append(p1)
            if "pos_update" in f:
                p2 = Tx(src, p1.dst, p1.path, position_info(rng, "="))
                later.append((p2, rng.uniform(5, 25), p1))
            if "pos_dup" in f:
                later.append((copy.deepcopy(p1), rng.uniform(3, 20), p1))
        if "dup_retry" in f:
            t = self._random_tx(i)
            i += 1
            txs.append(t)
            later.append((copy.deepcopy(t), rng.uniform(3, 25), t))
        if "dup_late" in f:
            t = self._random_tx(i)
            i += 1
            txs.append(t)
            later.append((copy.deepcopy(t), rng.uniform(31, 38), t))
        if "near_dup" in f:
            t = self._random_tx(i)
            i += 1
            txs.append(t)
            near = copy.deepcopy(t)
            b = bytearray(near.info)
            j = rng.randrange(1, len(b))
            b[j] = ord("X") if b[j] != ord("X") else ord("Y")
            near.info = bytes(b)
            later.append((near, rng.uniform(3, 20), t))
        if "digi_h" in f:
            t = self._random_tx(i)
            i += 1
            t.path = [("WIDE1", 1, True), ("WIDE2", 1, True)] if rng.random() < 0.5 else \
                [("K6DIG", 3, True), ("N6RLY", 1, True), ("WIDE2", 1, False)]
            txs.append(t)
        if "ssid_hi" in f:
            t = self._random_tx(i)
            i += 1
            t.src = (t.src[0], rng.choice([10, 12, 15]))
            t.dst = (t.dst[0], rng.choice([1, 3, 15]))
            txs.append(t)
        if "non_ui" in f:
            t = Tx(self._station(i), self._station(i + 1), [], b"", control=rng.choice([0x2F, 0x63, 0x43]), pid=None)
            i += 2
            txs.append(t)
        if "pid_other" in f:
            t = self._random_tx(i)
            i += 1
            t.pid = rng.choice([0xCF, 0xCC, 0x08])
            txs.append(t)
        if "status_frame" in f:
            t = self._random_tx(i)
            i += 1
            t.info = (">" + rng.choice(STATUS)).encode("latin-1")
            txs.append(t)
        if "long_info" in f:
            t = self._random_tx(i)
            i += 1
            words = rng.choices(["grid", "DM04", "battery", "12.6V", "temp", "23C", "wind", "NW", "gust", "17",
                                 "rain", "0.00", "solar", "ok", "uptime", "41d"], k=60)
            t.info = (">" + " ".join(words))[:200].encode("latin-1")
            txs.append(t)
        if "latin1" in f:
            t = self._random_tx(i)
            i += 1
            t.info = (">" + rng.choice(LATIN1)).encode("latin-1")
            txs.append(t)
        while len(txs) + len(later) < self.n:
            txs.append(self._random_tx(i))
            i += 1
        rng.shuffle(txs)
        self.txs = txs
        self.later = later
        # corrupt copies: a frame with one bit flipped on the air, and a frame cut short
        self.corrupt: list[Tx] = []
        if "bad_fcs" in f:
            c = copy.deepcopy(rng.choice(txs))
            c.corrupt = "flip"
            self.corrupt.append(c)
        if "abort" in f:
            c = copy.deepcopy(rng.choice(txs))
            c.corrupt = "abort"
            self.corrupt.append(c)

    def _route(self):
        rng, r, p = self.rng, self.route, self.params
        if r == "noise_lo":
            p["noise"] = rng.uniform(0.15, 0.25)
        if r == "noise_hi":
            p["noise"] = rng.uniform(0.30, 0.38)
        if r == "twist":
            p["twist"] = rng.choice([-1, 1]) * rng.uniform(8, 14)
        if r == "qsb":
            p["qsb"] = (rng.uniform(0.3, 1.5), rng.uniform(60, 90))
        if r == "drift":
            self.baud = BAUD * (1 + rng.choice([-1, 1]) * rng.uniform(0.012, 0.02))
        if r == "multipath":
            p["echo"] = (rng.uniform(30, 45), rng.uniform(0.4, 0.6))
        if r == "header_lie":
            self.declared_rate = rng.choice([x for x in RATES if x != self.rate and x >= 11025])
        if r == "stereo_decoy":
            self.channels = 2
            self.radio_channel = rng.choice([0, 1])
            for k in range(rng.randint(1, 2)):
                d = self._random_tx(20 + k)
                d.decoy = True
                self.decoys.append(d)
        if r == "stack":
            p["noise"] = rng.uniform(0.18, 0.25)
            p["twist"] = rng.choice([-1, 1]) * rng.uniform(6, 10)
            p["qsb"] = (rng.uniform(0.3, 1.5), rng.uniform(50, 80))
            self.baud = BAUD * (1 + rng.choice([-1, 1]) * rng.uniform(0.01, 0.02))
        if self.house["drift"] and r not in ("drift", "stack"):
            self.baud = BAUD * (1 + rng.choice([-1, 1]) * rng.uniform(0.004, self.house["drift"]))
        if self.channels == 2 and r != "stereo_decoy":
            self.radio_channel = rng.choice([0, 1])
        if "quiet_tx" in self.features:
            rng.choice(self.txs).level = 0.25

    # time line ----------------------------------------------------
    def schedule(self):
        """Place every burst on the time line; the truth's times follow from bit counts and the baud rate."""
        rng, f = self.rng, self.features
        order = list(self.txs) + list(self.corrupt)
        rng.shuffle(order)
        bursts: list[list[Tx]] = [[t] for t in order]
        if "shared_flag" in f and len(bursts) >= 2:
            j = rng.randrange(len(bursts) - 1)
            bursts[j] += bursts.pop(j + 1)
            bursts[j][1].burst_with_prev = True
        t = rng.uniform(0.3, 0.8)
        placed: list[tuple[float, list[Tx]]] = []
        for b in bursts:
            placed.append((t, b))
            t += self._burst_seconds(b) + rng.uniform(0.4, 1.5)
        # copies and acks come a set time after their originals, in their own bursts
        for c, after, orig in self.later:
            start = next(t0 for t0, b in placed if orig in b) + after
            placed.append((start, [c]))
        self.decoy_starts = [rng.uniform(0.5, 3.0) for _ in self.decoys]
        placed.sort(key=lambda x: x[0])
        # a burst may not start before the previous one ends
        last_end = 0.0
        self.bursts = []
        for t0, b in placed:
            t0 = max(t0, last_end + 0.3)
            bits, ends = burst_bits([(x.bytes, x.corrupt) for x in b], rng=self.rng)
            for x, e in zip(b, ends):
                x.burst_start, x.end_bits = t0, e
            self.bursts.append((t0, b, bits))   # these exact bits go on the air: a flipped bit changes the stuffing
            last_end = t0 + len(bits) / self.baud
        self.frames_all = [x for _, b, _ in self.bursts for x in b]
        self.duration = last_end + rng.uniform(0.5, 1.2)

    def _burst_seconds(self, b) -> float:
        bits, _ = burst_bits([(x.bytes, x.corrupt) for x in b], rng=self.rng)
        return len(bits) / self.baud

    def end_ms(self, tx: Tx, off=frozenset()) -> int:
        s = tx.burst_start + tx.end_bits / self.baud
        if 2 in off and self.declared_rate != self.rate:   # trusting the header mis-scales every time
            s *= self.rate / self.declared_rate
        return int(round(s * 1000))

    # operator log ---------------------------------------------------
    def _log(self):
        rng, f = self.rng, self.features
        heard = [x for x in self.frames_all if x.corrupt is None and (x.control & 0xEF) == UI and x.pid == PID_APRS]
        heard.sort(key=lambda x: self.end_ms(x))
        lines = [x.tnc2() for x in heard]
        if "log_missing" in f and lines:
            lines.pop(rng.randrange(len(lines)))
        if "log_typo" in f and lines:
            j = rng.randrange(len(lines))
            s = lines[j]
            digits = [k for k, ch in enumerate(s) if ch.isdigit()]
            if digits:
                k = rng.choice(digits)
                s = s[:k] + str((int(s[k]) + rng.randint(1, 8)) % 10) + s[k + 1:]
            else:
                k = s.index(":") + 1
                s = s[:k] + s[k:].replace("e", "a", 1)
            lines[j] = s
        if "log_extra" in f:
            extra = self._random_tx(30)
            lines.insert(rng.randrange(len(lines) + 1), extra.tnc2())
            self.log_extra = extra
        self.log_lines = lines

    def spec(self) -> dict:
        return {"station": self.station, "radio_channel": self.radio_channel, "sample_rate": self.declared_rate,
                "heard": list(self.log_lines or [])}

    # truth -----------------------------------------------------------
    def truth(self, off=frozenset()) -> dict:
        cands = [x for x in self.frames_all if x.corrupt is None]
        if 2 in off:
            cands += [x for x in self.frames_all if x.corrupt == "flip"]     # "repaired" by a bit-fixing decoder
            for d, s in zip(self.decoys, self.decoy_starts):                 # heard from the wrong channel
                d.burst_start, d.end_bits = s, len(burst_bits([(d.bytes, None)], rng=None)[0])
            cands += self.decoys
        cands.sort(key=lambda x: self.end_ms(x, off))
        frames = []
        for x in cands:
            frames.append({"t_ms": self.end_ms(x, off), "source": fmt_call(*x.src), "destination": fmt_call(*x.dst),
                           "path": fmt_path(x.path, off), "kind": kind_of(x.control, x.pid, x.info, off),
                           "info": x.info.decode("latin-1"), "dup_of": None})
        if 5 not in off:
            for i, fr in enumerate(frames):
                key = (fr["source"], fr["destination"], fr["info"])
                prev = [j for j in range(i) if (frames[j]["source"], frames[j]["destination"], frames[j]["info"]) == key]
                if prev and fr["t_ms"] - frames[prev[-1]]["t_ms"] <= DUP_WINDOW_MS:
                    p = frames[prev[-1]]
                    fr["dup_of"] = p["dup_of"] if p["dup_of"] is not None else prev[-1]
        messages: dict[tuple, dict] = {}
        for i, fr in enumerate(frames):
            if fr["kind"] != "message":
                continue
            m = read_message(fr["info"].encode("latin-1"))
            key = (fr["source"], m["to"], m["id"] if m["id"] is not None else m["text"])
            if key not in messages:
                messages[key] = {"from": fr["source"], "to": m["to"], "id": m["id"], "text": m["text"], "sent": 0,
                                 "status": "open", "_t": fr["t_ms"]}
            messages[key]["sent"] += 1
        if 6 not in off:
            for fr in frames:
                if fr["kind"] != "ack":
                    continue
                a = read_message(fr["info"].encode("latin-1"))
                for key, m in messages.items():
                    if m["from"] == a["to"] and m["to"] == fr["source"] and m["id"] == a["ack"] and fr["t_ms"] > m["_t"]:
                        m["status"] = "acked"
        msgs = [{k: v for k, v in m.items() if k != "_t"} for m in sorted(messages.values(), key=lambda m: m["_t"])]
        positions: dict[str, dict] = {}
        for fr in frames:
            if fr["kind"] != "position":
                continue
            if fr["source"] not in positions or 7 not in off:
                positions[fr["source"]] = {"t_ms": fr["t_ms"], "info": fr["info"]}
        return {"frames": frames, "messages": msgs, "positions": positions}
