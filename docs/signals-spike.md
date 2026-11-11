# Signals pilot: feasibility spike (2026-11-01)

Image: `debian:trixie-slim` + direwolf, minimodem, multimon-ng, sox, ebook2cw, python3-numpy, python3-scipy. Builds clean; tag `tf-sigspike:latest`. Dockerfile and scripts were a throwaway spike and are not in the repository.

Generator path works: `gen_packets -o clean.wav -r 44100 -a 50 packets.txt` encodes TNC2 lines to AFSK 1200 AX.25 audio; sox applies the degradations; `atest -B 1200` (direwolf) decodes and is the cross-check for the truth. Count frames with `grep -c 'DECODED\['` (lines carry ANSI colour codes). Noise is mixed with `sox -r 44100 -n noise.wav synth DUR whitenoise vol V` then `sox -m`.

Direwolf's envelope on 4 frames (the reference must stay inside it):

| Degradation | Frames decoded |
|---|---|
| clean, noise vol 0.06 to 0.25, treble -8 or -14, bass +9, gain 18 clipped, speed 0.97 or 1.02, dcshift 0.4, tremolo 90, echo 40 ms, rate 8000 or 6000, tones swapped, amp 150, gen_packets -v 30,2 or -n 6 | 4 |
| noise vol 0.4 | 3 |
| noise vol 0.6 and above | 0 |
| stack: noise 0.3 + treble -8 + tremolo + speed 1.02 + dcshift 0.3 | 3 |
| same stack at noise 0.6 | 0 |
| echo 6 ms (multipath at symbol scale) | 0 |
| speed 1.04 (4% baud error) | 0 |
| WAV header says 48000, samples are 44100 | 0 |
| signal on the right channel only | 0 (atest reads channel 0) |

Lessons for the pack: keep hidden items at noise 0.3 or less, drift 2% or less, echo 20 ms or more; the header lie and the channel rule are real traps and the policy must state how to resolve them (declared rate in the operator log, or derive from the preamble tones; which channel is the radio). Next step: write a naive correlator decoder in numpy and run the same ladder, to find the band where a textbook decoder loses frames and direwolf does not. That band is the hidden-item difficulty.
