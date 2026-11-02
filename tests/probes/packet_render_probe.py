"""Runs inside the packet-log gen image: renders captures and reports what the file and direwolf say, as JSON."""
import json
import random
import re
import subprocess
import sys
import wave

import numpy as np

sys.path.insert(0, "/pack")
import pack  # noqa: E402


def decode(samples: np.ndarray, rate: int, path: str) -> list[str]:
    with wave.open(path, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(np.round(np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    out = subprocess.run(["atest", "-B", "1200", "-F", "0", path], capture_output=True).stdout.decode("latin-1")
    out = re.sub(r"\x1b\[[0-9;]*m", "", out)      # direwolf colours its output
    return [re.sub(r"<0x..>", "", ln[4:]) for ln in out.splitlines() if ln.startswith("[0] ")]


out = {}
for cid, house, route, units, feats, key in json.loads(sys.argv[1]):
    rng = random.Random(key)
    cap = pack.build(cid, house, route, units, frozenset(feats), rng)
    path = f"/tmp/{cid}.wav"
    note = pack.render(cap, path, rng)
    with wave.open(path, "rb") as w:
        hdr = {"rate": w.getframerate(), "channels": w.getnchannels(), "bits": 8 * w.getsampwidth(),
               "seconds": w.getnframes() / cap.rate}
        raw = w.readframes(w.getnframes())
    if hdr["bits"] == 8:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(float) - 128) / 128
    else:
        x = np.frombuffer(raw, dtype="<i2").astype(float) / 32768
    chans = [x] if hdr["channels"] == 1 else [x.reshape(-1, 2)[:, k] for k in range(2)]
    radio = decode(chans[cap.radio_channel], cap.rate, f"/tmp/{cid}-radio.wav")
    other = decode(chans[1 - cap.radio_channel], cap.rate, f"/tmp/{cid}-other.wav") if len(chans) == 2 else []
    valid = [t for t in cap.frames_all if t.corrupt is None]
    out[cid] = {"header": hdr, "true_rate": cap.rate, "declared_rate": cap.declared_rate, "note": note,
                "radio_channel": cap.radio_channel, "decoded_radio": radio, "decoded_other": other,
                "expected": [t.tnc2() for t in valid], "corrupt": len(cap.frames_all) - len(valid),
                "decoys": [d.tnc2() for d in cap.decoys], "duration": cap.duration}
print(json.dumps(out))
