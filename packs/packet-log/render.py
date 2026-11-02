"""Put a capture on the air: AFSK modulation of the scheduled bits, the station's character, the route's
degradation (sox), then a check that direwolf still decodes every valid frame. Runs in the generator image."""
from __future__ import annotations

import re
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

import model

STRENGTHS = (1.0, 0.8, 0.6, 0.45, 0.3)   # a route that loses a frame for direwolf is turned down, then the item fails


def afsk(bits: list[int], rate: int, baud: float, mark=model.MARK, space=model.SPACE) -> np.ndarray:
    """Continuous-phase AFSK of NRZI-coded bits: a 0 changes the tone, a 1 keeps it. Tones scale with the baud."""
    scale = baud / model.BAUD
    tone, freqs = mark, []
    for b in bits:
        if b == 0:
            tone = space if tone == mark else mark
        freqs.append(tone * scale)
    edges = np.round(np.arange(len(bits) + 1) * rate / baud).astype(int)
    f = np.zeros(edges[-1])
    for i, fr in enumerate(freqs):
        f[edges[i]:edges[i + 1]] = fr
    phase = np.cumsum(2 * np.pi * f / rate)
    return np.sin(phase)


def lay_down(cap: model.Capture) -> tuple[np.ndarray, np.ndarray | None]:
    """The radio channel and, for a stereo capture, the other channel, as float arrays in [-1, 1]."""
    rate, h = cap.rate, cap.house
    n = int(cap.duration * rate) + rate
    radio = np.zeros(n)
    for t0, txs, bits in cap.bursts:
        sig = afsk(bits, rate, cap.baud)
        # one burst, one key-down: the quietest frame's level sets the whole burst
        level = h["level"] * min(x.level for x in txs)
        s = int(round(t0 * rate))
        radio[s:s + len(sig)] += level * sig[: max(0, n - s)]
    radio += h["dc"]
    other = None
    if cap.channels == 2:
        other = np.random.default_rng(abs(hash(cap.id)) % 2**32).normal(0, 0.004, n)
        for d, start in zip(cap.decoys, cap.decoy_starts):
            bits, _ = model.burst_bits([(d.bytes, None)], rng=None)
            sig = afsk(bits, rate, model.BAUD)
            s = int(round(start * rate))
            other[s:s + len(sig)] += 0.6 * h["level"] * sig[: max(0, n - s)]
    return radio, other


def write_wav(path: str, data: np.ndarray, rate: int, bits: int = 16) -> None:
    data = np.clip(data, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1 if data.ndim == 1 else data.shape[1])
        w.setsampwidth(bits // 8)
        w.setframerate(rate)
        if bits == 8:
            w.writeframes((np.round(data * 127) + 128).astype(np.uint8).tobytes())
        else:
            w.writeframes(np.round(data * 32767).astype("<i2").tobytes())


def sox(*args: str) -> None:
    subprocess.run(["sox", *args], check=True, capture_output=True)


def degrade(src: str, dst: str, cap: model.Capture, strength: float, td: Path) -> None:
    """The station's character and the route's degradation, scaled by `strength`."""
    p, h = cap.params, cap.house
    fx: list[str] = []
    twist = h["twist"] + p.get("twist", 0.0) * strength
    if twist:
        fx += ["treble", f"{twist:.1f}", "2000"]
    if h["limiter"]:
        fx += ["gain", "-l", "3"]
    if "qsb" in p:
        speed, depth = p["qsb"]
        fx += ["tremolo", f"{speed:.2f}", f"{depth * strength:.0f}"]
    if "echo" in p:
        delay, decay = p["echo"]
        fx += ["echo", "0.8", "0.7", f"{delay:.0f}", f"{decay * strength:.2f}"]
    cur = src
    if fx:
        sox(cur, str(td / "fx.wav"), *fx)
        cur = str(td / "fx.wav")
    if "noise" in p:
        vol = p["noise"] * strength * h["level"] / 0.5
        dur = subprocess.run(["soxi", "-D", cur], capture_output=True, text=True, check=True).stdout.strip()
        sox("-r", str(cap.rate), "-n", str(td / "noise.wav"), "synth", dur, "whitenoise", "vol", f"{vol:.3f}")
        sox("-m", cur, str(td / "noise.wav"), str(td / "mixed.wav"))
        cur = str(td / "mixed.wav")
    if cur != dst:
        sox(cur, dst)


def direwolf_frames(path: str) -> int:
    # bytes, not text: an information field may hold ISO 8859-1 bytes that are not UTF-8
    out = subprocess.run(["atest", "-B", "1200", "-F", "0", path], capture_output=True).stdout
    return len(re.findall(rb"DECODED\[", out))


def render_item(cap: model.Capture, out_path: str, rng) -> str:
    out = Path(out_path)
    radio, other = lay_down(cap)
    expected = sum(1 for x in cap.frames_all if x.corrupt is None)
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        write_wav(str(td / "radio.wav"), radio, cap.rate)
        for strength in STRENGTHS:
            degrade(str(td / "radio.wav"), str(td / "deg.wav"), cap, strength, td)
            got = direwolf_frames(str(td / "deg.wav"))
            if got == expected:
                break
        else:
            raise RuntimeError(f"direwolf decodes {got} of {expected} frames even at strength {STRENGTHS[-1]}")
        with wave.open(str(td / "deg.wav")) as w:
            deg = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float) / 32767
        if other is not None:
            n = min(len(deg), len(other))
            chans = [deg[:n], other[:n]] if cap.radio_channel == 0 else [other[:n], deg[:n]]
            data = np.stack(chans, axis=1)
        else:
            data = deg
        write_wav(str(out), data, cap.declared_rate, cap.house["bits"])
    return f"{cap.house_key} {cap.route} strength {strength} ({expected} frames, {len(cap.frames_all) - expected} corrupt)"
