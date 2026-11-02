#!/usr/bin/env python3
"""Reference decoder for the packet-log task: python3 intake.py IN.wav SPEC.json OUT.json

Reads the radio channel, finds the true sample rate from the tones, demodulates 1200 baud AFSK with a
quadrature correlator and per-tone normalisation, recovers bits from transition spacing, parses HDLC frames
and checks each FCS, then applies the operator policy (kinds, paths, duplicates, messages, positions).
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


def true_rate(x: np.ndarray, header_rate: int) -> int:
    """The standard rate at which the two tones sit at 1200 and 2200 Hz."""
    n = min(len(x), 1 << 20)
    seg = x[:n] * np.hanning(n)
    p = np.abs(np.fft.rfft(seg)) ** 2
    best, best_score = header_rate, -1.0
    for r in RATES:
        score = 0.0
        for tone in (MARK, SPACE):
            f_bin = tone * n / r            # where the tone falls if the samples are really at rate r
            lo, hi = int(f_bin * 0.965), int(f_bin * 1.035) + 1
            if hi >= len(p):
                score = -1.0
                break
            score += p[lo:hi].max()
        if score > best_score:
            best, best_score = r, score
    return best


# ------------------------------------------------------------------ demodulation

def envelope(x, rate, f, win):
    t = np.arange(len(x)) / rate
    i = uniform_filter1d(x * np.cos(2 * np.pi * f * t), win)
    q = uniform_filter1d(x * np.sin(2 * np.pi * f * t), win)
    return np.hypot(i, q)


def bits_with_times(x: np.ndarray, rate: int):
    """NRZI bits and, for each, the time in ms at which its bit period ends."""
    bl = rate / BAUD
    win = max(3, int(round(bl)))
    m = envelope(x, rate, MARK, win)
    s = envelope(x, rate, SPACE, win)
    agc = max(1, int(rate * 0.06))                 # each tone normalised by its own recent peak (twist, fading)
    m = m / (maximum_filter1d(m, agc) + 1e-9)
    s = s / (maximum_filter1d(s, agc) + 1e-9)
    d = m - s
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
    rate = true_rate(x, header_rate)
    bits, ends = bits_with_times(x, rate)
    decoded = hdlc_frames(bits, ends)
    with open(out_path, "w") as f:
        json.dump(apply_policy(decoded), f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:4])
