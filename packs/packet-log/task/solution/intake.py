#!/usr/bin/env python3
"""Reference decoder for the packet-log task: python3 intake.py IN.wav SPEC.json OUT.json

Reads the radio channel, demodulates 1200 baud AFSK at each standard sample rate with a quadrature correlator
and per-tone normalisation, recovers bits from transition spacing, parses HDLC frames and checks each FCS,
keeps the rate that yields the most valid frames, then applies the operator policy (kinds, paths,
duplicates, messages, positions).
"""
from __future__ import annotations

import json
import re
import sys
import wave

import numpy as np
from scipy.ndimage import maximum_filter1d, uniform_filter1d

RATES = (8000, 11025, 22050, 44100, 48000)
MARK, SPACE, BAUD = 1200.0, 2200.0, 1200.0
DUP_MS = 30_000


# ------------------------------------------------------------------ audio in

def read_wav(path: str, channel: int):
    with wave.open(path, "rb") as w:
        rate, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw == 1:
        x = np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0
        x /= 128.0
    elif sw == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    else:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    if ch > 1:
        x = x.reshape(-1, ch)[:, min(channel, ch - 1)]
    return rate, x - np.mean(x)


SAME_FRAME_MS = 200     # the same bytes decoded by two demodulators this close together are one transmission


def decode_at(x: np.ndarray, rate: int):
    """Union of the valid frames found by several demodulators. Each frame is only accepted on a matching FCS,
    so a frame one demodulator reads and another misses (noise, jitter, clock offset) is still a real frame."""
    d = slicer(x, rate)
    found = list(hdlc_frames(*bits_with_times(d, rate)))
    for alpha in (0.3, 0.15, 0.5):
        for smooth in (0, 0.5):
            ds = uniform_filter1d(d, max(1, int(round(rate / BAUD * smooth)))) if smooth else d
            for fr, t in hdlc_frames(*bits_pll(ds, rate, alpha)):
                if not any(fr == f and abs(t - u) <= SAME_FRAME_MS for f, u in found):
                    found.append((fr, t))
    return found


def best_decode(x: np.ndarray, header_rate: int):
    """Decode at every standard rate and keep the one that yields the most frames with a valid FCS: a
    matching FCS is unambiguous evidence of the true rate, where a tone's spectrum (spread by the keying) is not.
    The header's rate wins ties."""
    order = [header_rate] + [r for r in RATES if r != header_rate]
    best, best_frames = header_rate, decode_at(x, header_rate)
    for r in order[1:]:
        fr = decode_at(x, r)
        if len(fr) > len(best_frames):
            best, best_frames = r, fr
    return best, best_frames


# ------------------------------------------------------------------ demodulation

def envelope(x, rate, f, win):
    t = np.arange(len(x)) / rate
    i = uniform_filter1d(x * np.cos(2 * np.pi * f * t), win)
    q = uniform_filter1d(x * np.sin(2 * np.pi * f * t), win)
    return np.hypot(i, q)


def slicer(x: np.ndarray, rate: int):
    """Mark minus space tone level, each tone normalised by its own recent peak (twist, fading)."""
    bl = rate / BAUD
    win = max(3, int(round(bl)))
    m = envelope(x, rate, MARK, win)
    s = envelope(x, rate, SPACE, win)
    agc = max(1, int(rate * 0.06))
    m = m / (maximum_filter1d(m, agc) + 1e-9)
    s = s / (maximum_filter1d(s, agc) + 1e-9)
    return m - s


def bits_pll(d: np.ndarray, rate: int, alpha: float):
    """NRZI bits sampled at bit centres from a clock that tracks the tone transitions (a phase-locked loop on
    the edge grid), and for each bit the time in ms at which its period ends. Unlike counting the spacing of two
    raw transitions, an edge's jitter does not carry into the next bit count, and a brief glitch between bit
    centres is not sampled."""
    bl = rate / BAUD
    sign = d >= 0
    a = np.flatnonzero(sign[1:] != sign[:-1])      # crossing between a and a+1
    if len(a) < 2:
        return [], []
    da, db = d[a], d[a + 1]
    tau = a + da / np.where(da - db == 0, 1e-12, da - db)
    centres = []
    edge = tau[0]
    for t in tau[1:]:
        k = int(round((t - edge) / bl))
        if k <= 0:
            edge += alpha * (t - edge)
            continue
        if k > 64:                                  # long silence or noise: restart the clock on this edge
            edge = t
            continue
        centres.extend(edge + (j + 0.5) * bl for j in range(k))
        grid = edge + k * bl
        edge = grid + alpha * (t - grid)
    if len(centres) < 2:
        return [], []
    c = np.asarray(centres)
    ci = np.clip(np.round(c).astype(np.int64), 0, len(d) - 1)
    sv = sign[ci]
    bits = (sv[1:] == sv[:-1]).astype(np.int8).tolist()
    ends = ((c[1:] + bl / 2) / rate * 1000.0).tolist()
    return bits, ends


def bits_with_times(d: np.ndarray, rate: int):
    """NRZI bits and, for each, the time in ms at which its bit period ends."""
    bl = rate / BAUD
    sign = np.where(d >= 0, 1, -1)
    idx = np.flatnonzero(np.diff(sign) != 0) + 1
    bits, ends = [], []
    for a, b in zip(idx[:-1], idx[1:]):
        n = int(round((b - a) / bl))
        if n <= 0:
            continue
        step = (b - a) / n
        for k in range(n):
            bits.append(0 if k == 0 else 1)         # a transition is a 0; each further period is a 1
            ends.append((a + (k + 1) * step) / rate * 1000.0)
    return bits, ends


# ------------------------------------------------------------------ HDLC and AX.25

def crc16_x25(data: bytes) -> int:
    c = 0xFFFF
    for byte in data:
        c ^= byte
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if c & 1 else c >> 1
    return c ^ 0xFFFF


def hdlc_frames(bits, ends):
    """(frame bytes without FCS, ms at the end of the closing flag) for every frame whose FCS matches."""
    out, buf, ones = [], [], 0
    for i, b in enumerate(bits):
        if b:
            ones += 1
            buf.append(1)
            if ones > 6:                            # abort
                buf, ones = [], 0
            continue
        if ones == 5:                               # stuffed zero
            ones = 0
            continue
        if ones == 6:                               # flag: 0 1 1 1 1 1 1 0
            data = buf[:-7]
            buf, ones = [], 0
            if len(data) >= 8 * 17 and len(data) % 8 == 0:
                by = bytes(sum(data[j + k] << k for k in range(8)) for j in range(0, len(data), 8))
                if crc16_x25(by[:-2]) == by[-2] | (by[-1] << 8):
                    out.append((by[:-2], ends[i]))
            continue
        ones = 0
        buf.append(0)
    return out


def parse(fr: bytes):
    addrs, i = [], 0
    while i + 7 <= len(fr) and len(addrs) < 10:
        a = fr[i:i + 7]
        addrs.append(("".join(chr(c >> 1) for c in a[:6]).strip(), (a[6] >> 1) & 0x0F, bool(a[6] & 0x80)))
        i += 7
        if a[6] & 1:
            break
    if len(addrs) < 2 or i >= len(fr):
        return None
    control = fr[i]
    ui = (control & 0xEF) == 0x03
    pid = fr[i + 1] if ui and i + 1 < len(fr) else None
    info = fr[i + 2:] if ui else fr[i + 1:]
    return addrs[0], addrs[1], addrs[2:], control, pid, bytes(info)


# ------------------------------------------------------------------ the policy

def call(c, s):
    return f"{c}-{s}" if s else c


def path_strs(path):
    out = [call(c, s) for c, s, _ in path]
    hs = [k for k, (_, _, h) in enumerate(path) if h]
    if hs:
        out[hs[-1]] += "*"
    return out


MSG = re.compile(rb"^:(.{9}):(.*)$", re.S)
ACK = re.compile(rb"^ack([A-Za-z0-9]{1,5})$")
MID = re.compile(rb"\{([A-Za-z0-9]{1,5})$")


def message(info: bytes):
    m = MSG.match(info)
    if not m:
        return None
    to, text = m.group(1).decode("latin-1").strip(), m.group(2)
    a = ACK.match(text)
    if a:
        return {"to": to, "ack": a.group(1).decode("latin-1")}
    i = MID.search(text)
    return {"to": to, "id": i.group(1).decode("latin-1") if i else None,
            "text": (text[: i.start()] if i else text).decode("latin-1")}


def kind(control, pid, info):
    if (control & 0xEF) != 0x03 or pid != 0xF0:
        return "non_aprs"
    if not info:
        return "other"
    c = chr(info[0])
    if c in "!=/@":
        return "position"
    if c == ">":
        return "status"
    if c == ":":
        m = message(info)
        return "other" if m is None else ("ack" if "ack" in m else "message")
    return "other"


def apply_policy(decoded):
    frames = []
    for fr, t in sorted(decoded, key=lambda x: x[1]):
        p = parse(fr)
        if p is None:
            continue
        dst, src, path, control, pid, info = p
        frames.append({"t_ms": int(round(t)), "source": call(*src[:2]), "destination": call(*dst[:2]),
                       "path": path_strs(path), "kind": kind(control, pid, info),
                       "info": info.decode("latin-1"), "dup_of": None})
    for i, fr in enumerate(frames):
        key = (fr["source"], fr["destination"], fr["info"])
        prev = [j for j in range(i) if (frames[j]["source"], frames[j]["destination"], frames[j]["info"]) == key]
        if prev and fr["t_ms"] - frames[prev[-1]]["t_ms"] <= DUP_MS:
            p = frames[prev[-1]]
            fr["dup_of"] = p["dup_of"] if p["dup_of"] is not None else prev[-1]
    msgs = {}
    for fr in frames:
        if fr["kind"] != "message":
            continue
        m = message(fr["info"].encode("latin-1"))
        key = (fr["source"], m["to"], m["id"] if m["id"] is not None else m["text"])
        if key not in msgs:
            msgs[key] = {"from": fr["source"], "to": m["to"], "id": m["id"], "text": m["text"], "sent": 0,
                         "status": "open", "_t": fr["t_ms"]}
        msgs[key]["sent"] += 1
    for fr in frames:
        if fr["kind"] != "ack":
            continue
        a = message(fr["info"].encode("latin-1"))
        for m in msgs.values():
            if m["from"] == a["to"] and m["to"] == fr["source"] and m["id"] == a["ack"] and fr["t_ms"] > m["_t"]:
                m["status"] = "acked"
    messages = [{k: v for k, v in m.items() if k != "_t"} for m in sorted(msgs.values(), key=lambda m: m["_t"])]
    positions = {}
    for fr in frames:
        if fr["kind"] == "position":
            positions[fr["source"]] = {"t_ms": fr["t_ms"], "info": fr["info"]}
    return {"frames": frames, "messages": messages, "positions": positions}


def main(wav_path, spec_path, out_path):
    spec = json.load(open(spec_path))
    header_rate, x = read_wav(wav_path, int(spec.get("radio_channel", 0)))
    rate, decoded = best_decode(x, header_rate)
    with open(out_path, "w") as f:
        json.dump(apply_policy(decoded), f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:4])
