# packet-log: the signals pack (design)

Second family for the factory, first with a non-PDF medium. The agent writes a decoder for recordings of 1200 baud AFSK packet radio (AX.25, APRS) and outputs an exact log of what was heard, per a written operator policy. Same five mechanisms as coa-intake: a lying channel (the operator's typed log and the WAV header), a reader the agent must build (a demodulator that survives noise, twist, fading and drift), stacking, supersession (duplicates, retries, acks, latest position) and exactness from a truth engine that never listened to the audio.

Calibration from the spike (`signals-spike.md`): a textbook correlator with a fixed slicer decodes every frame under any single degradation direwolf decodes, except noise above 0.3 and stacks of noise 0.2 or more with twist, fading and drift. That band is where the hidden items live. The reference must stay inside direwolf's envelope, which the renderer checks for every item.

## Inputs and output

- `ID.wav`: one recording, 1 to 6 transmissions. Styles set the sample rate, bit depth and channel count.
- `ID.spec.json`: the operator log for the capture. Authoritative fields: `radio_channel` (which channel carries the radio) and `station` (our callsign). Aids only: `sample_rate` as the operator believes it, and `heard`, the operator's typed TNC2 transcript, which may carry typos, miss a frame or list one that was never sent.
- Tool: `python3 /app/intake/intake.py IN.wav SPEC.json OUT.json`.
- Output: `{"frames": [...], "messages": [...], "positions": {...}}`. Each frame: `t_ms` (end of frame, true rate), `source`, `destination`, `path` (list, `*` after the last digipeated hop), `kind`, `info`, `dup_of`. Times compare with a 50 ms tolerance; everything else exactly.

## Styles (station chains)

| Style | Rate, bits, channels | Character |
|---|---|---|
| tnc2 | 44100, 16, mono | flat tones, 50% level |
| handheld | 22050, 16, mono | pre-emphasis twist (space louder), light clipping, DC offset |
| sdr | 48000, 16, stereo | radio on the channel the log names, 25% level; the other channel carries the operator's second receiver |
| mobile | 11025, 8, mono | de-emphasis (mark louder), 1% speed drift |

## Routes (degradation on top of the style)

`clean`, `noise_lo` (0.15 to 0.25), `noise_hi` (0.30 to 0.38), `twist` (±8 to 14 dB at 2 kHz), `qsb` (tremolo), `drift` (speed 0.98 to 1.02), `multipath` (echo 30 to 45 ms), `header_lie` (declared rate differs from the true one), `stereo_decoy` (a second, unrelated transmission on the other channel), `stack` (noise_lo + twist + qsb + drift).

Reading routes: `noise_hi`, `twist`, `qsb`, `drift`, `multipath`, `stack`. Route rules: `header_lie` and `stereo_decoy` exercise rule 2.

The renderer runs direwolf (`atest`) on every rendered capture, at the true rate and on the radio channel, and requires every valid frame to decode. If one is lost, the route's strength steps down and the capture is drawn again; after three steps the item fails the render gate. That is the fairness proof at render time: an existing expert tool decodes every item.

## Rules (policy, numbered as in the pack)

1. Scope: one capture, one operator log; which log fields are authoritative and which are aids.
2. The audio decides. Tones 1200/2200 Hz at 1200 baud; the true sample rate is the one of {8000, 11025, 22050, 44100, 48000} at which the tones measure so; the header and the log are aids. Frames come from the radio channel only. A frame counts only when its FCS (AX.25 2.2 §3.7, CRC-16/X25) matches; a frame with a wrong FCS or cut short is not reported and is not repaired. The transcript is never a source.
3. Addresses: callsign and SSID per AX.25 §2.2.13; SSID omitted when 0; `*` after the last address whose H bit is set.
4. Kinds: UI frame with PID 0xF0 is APRS: `position` (`!`, `=`, `/`, `@`), `status` (`>`), `message` (`:`), `ack` (message whose text is `ack` plus an id), `other`. Any other PID or control field: `non_aprs`. Frames in order of `t_ms`.
5. Duplicates: same source, destination and info as an earlier frame within 30 s: `dup_of` is that frame's index; later than 30 s it is a new frame.
6. Messages: one entry per sender, addressee and id (`{id` at the end of the text; id null when absent): `sent` counts every transmission including duplicates; `status` is `acked` when the addressee sent `ack<id>` to the sender after the first transmission, else `open`.
7. Positions: the latest position frame per source, by `t_ms`.
8. Output: key sets and ordering.

Mutants: 2 (trust the transcript), 3 (`*` on every repeated hop), 4 (every UI frame is APRS), 5 (no duplicates), 6 (no acks), 7 (first position kept).

## Features (traps)

Rule 5: `dup_retry`, `dup_late`, `near_dup`, `pos_dup`. Rule 6: `msg_ack`, `msg_retry`, `msg_noid`, `ack_other`. Rule 7: `pos_update`. Rule 3: `digi_h`, `ssid_hi`. Rule 4: `non_ui`, `pid_other`, `status_frame`. Rule 2: `bad_fcs` (a copy with one flipped bit: a bit-repairing decoder turns it into a duplicate), `abort` (a frame cut short), `shared_flag` (two frames sharing one flag), `log_typo`, `log_missing`, `log_extra`. Reading: `quiet_tx` (one transmission at a quarter of the others' level), `long_info`, `latin1`.

## Builder changes

- Item file extension from the pack (`ext = "wav"`), used by the renderer, the reference runner and the assembler. Default `pdf`.
- Nothing else: pack.toml, plan, gates, fix loop, holdout and trials are reused.

## Environments

- Agent and reference image: python3, numpy, scipy, sox for inspection only. No direwolf, multimon-ng, minimodem, pip or network.
- Generator image: the above plus direwolf and sox.

## Open risks

- A direwolf-quality decoder in pure Python is the reference. `micro-aprs` shows it can be done; the fix loop has to get there with the truth in hand. If it cannot, the hidden band narrows until it can.
- The difficulty band on noise alone is narrow (0.3 to 0.38). Stacks and the rule traps carry the rest.

## Pilot log

- 2026-11-02, seed 1: 10 samples, 29 hidden; 10 of 10 routes and all 23 features in the samples; every mutant rule decides 5 or 6 hidden items.
- Render: 39 of 39 decoded by direwolf. Strengths used: 31 at 1.0, 4 at 0.8, 4 at 0.6. A quarter-level frame under heavy noise was lost even by direwolf, so `quiet_tx` stays off `noise_hi` and `stack`, and the ladder has five rungs.
- Reference: the hand-written decoder picked the wrong rate on an 8-bit capture because the keyed tones spread their energy; it now decodes at every standard rate and keeps the one with the most valid frames. It then dropped one frame on four captures (noise, multipath, stack). One round of the Opus fix loop replaced transition counting with a clock-recovery loop sampling at bit centres, plus an ensemble of loop gains whose valid frames are merged. Reference 39 of 39, holdout seed 1001 40 of 40, slowest item 15 s. The fix is general: no id, name or value from the captures appears in it.
- Task assembled at `out/build-pkt-1f/task/packet-log-s1` (57 MB).
- Oracle 1, nop 0. Cheap screen: Sonnet 5.5 at a 2 h cap passed 29 of 29 in about 1 h 35 min with an 820-line decoder (bandpass, burst detection, timing refinement, Viterbi). Too easy at direwolf-safe levels: the hidden set had 31 of 39 items at the route's drawn strength and my own textbook decoder read 35 of 39.
- Knob turned: every degraded capture is now pushed up a ladder (1.0 to 4.0) to the last strength direwolf still decodes in full; twist is capped at 20 dB; hidden items stack 4 to 6 features and 85% come by a reading route. If Sonnet still passes, the next lever is the mode (PSK31 or 300 baud HF), not the level.
- Seed 2 at the edge: 38 items; the seed-1 reference passed all 38 untouched. Where the hidden items landed: twist all at the ladder's top (saturated by the 20 dB cap), qsb at 1.0 to 1.25 (tremolo depth saturates at 100%), noise_hi from 0.6 to 2.5 (the edge varies with frame length and station), multipath turned down to 0.45 to 0.8, drift and header_lie and stereo_decoy fixed at 1.0 by construction. Only noise and multipath are really searched; the next lever, if needed, is a noise floor on every degraded route so each item sits at its own SNR edge.
- Seed 2 screen (2026-11-02): oracle 1, nop 0. Sonnet 5.5 at the 2 h cap passed 28 of 28 again, but only by running to the kill: `AgentTimeoutError` at 7200 s with a passing decoder already on disk (1355 lines: matched-filter bank, burst detection, noise estimate, weak-bit repair, per-survivor Viterbi with K-best list decoding, coherent polish; about $16, 516k output tokens). The `bad_fcs` trap survived its repair because the flipped bit is a strong one. The edge made it harder, not hard: the next lever is a noise floor on every degraded route or the mode (PSK31, 300 baud HF), else plot digitization. Frontier trials held for Alex's go-ahead.
