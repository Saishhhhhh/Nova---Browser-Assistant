# VAD results (40 commands in 10 recordings + 1 silent recording)

Per setting: commands handled **ok** out of 40 (clean audio), commands **split** (end declared mid-command), **merged** (two commands in one clip), **clipped** (start cut), **missed**, and **false alarms** (speech reported where nobody spoke, including the silent recording). `end wait` = time from the real end of speech to the VAD declaring it (median / 95th percentile). `start lag` = how late the start was detected.

| Detector | thr | hangover | ok | split | merged | clipped | missed | false alarms | end wait (ms) | start lag (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| silero | 0.3 | 300 ms | 39/40 | 0 | 0 | 1 | 0 | 0 | 424 / 564 | 0 |
| silero | 0.3 | 500 ms | 39/40 | 0 | 0 | 1 | 0 | 0 | 616 / 756 | 0 |
| silero | 0.3 | 800 ms | 40/40 | 0 | 0 | 0 | 0 | 0 | 904 / 1044 | 0 |
| silero | 0.5 | 300 ms | 39/40 | 0 | 0 | 1 | 0 | 0 | 412 / 532 | 8 |
| silero | 0.5 | 500 ms | 39/40 | 0 | 0 | 1 | 0 | 0 | 604 / 724 | 8 |
| silero | 0.5 | 800 ms | 40/40 | 0 | 0 | 0 | 0 | 0 | 892 / 1012 | 8 |
| silero | 0.7 | 300 ms | 39/40 | 0 | 0 | 1 | 0 | 0 | 404 / 517 | 14 |
| silero | 0.7 | 500 ms | 39/40 | 0 | 0 | 1 | 0 | 0 | 596 / 709 | 14 |
| silero | 0.7 | 800 ms | 40/40 | 0 | 0 | 0 | 0 | 0 | 884 / 997 | 14 |
| webrtc0 | 0.5 | 300 ms | 39/40 | 1 | 0 | 0 | 0 | 29 | 500 / 658 | -20 |
| webrtc0 | 0.5 | 500 ms | 32/40 | 0 | 8 | 0 | 0 | 14 | 700 / 1065 | -50 |
| webrtc0 | 0.5 | 800 ms | 23/40 | 0 | 17 | 0 | 0 | 6 | 1000 / 1138 | -80 |
| webrtc1 | 0.5 | 300 ms | 39/40 | 1 | 0 | 0 | 0 | 24 | 500 / 640 | 0 |
| webrtc1 | 0.5 | 500 ms | 32/40 | 0 | 8 | 0 | 0 | 13 | 700 / 1065 | -20 |
| webrtc1 | 0.5 | 800 ms | 27/40 | 0 | 13 | 0 | 0 | 7 | 1000 / 1330 | -20 |
| webrtc2 | 0.5 | 300 ms | 40/40 | 0 | 0 | 0 | 0 | 5 | 450 / 591 | 0 |
| webrtc2 | 0.5 | 500 ms | 36/40 | 0 | 4 | 0 | 0 | 3 | 660 / 820 | 0 |
| webrtc2 | 0.5 | 800 ms | 28/40 | 0 | 12 | 0 | 0 | 0 | 950 / 1281 | -20 |
| webrtc3 | 0.5 | 300 ms | 39/40 | 0 | 0 | 1 | 0 | 0 | 380 / 420 | 10 |
| webrtc3 | 0.5 | 500 ms | 40/40 | 0 | 0 | 0 | 0 | 0 | 580 / 620 | 10 |
| webrtc3 | 0.5 | 800 ms | 40/40 | 0 | 0 | 0 | 0 | 0 | 880 / 920 | 10 |
| energy | 9.0 | 300 ms | 39/40 | 1 | 0 | 0 | 0 | 0 | 300 / 300 | 0 |
| energy | 9.0 | 500 ms | 40/40 | 0 | 0 | 0 | 0 | 0 | 500 / 500 | 0 |
| energy | 9.0 | 800 ms | 40/40 | 0 | 0 | 0 | 0 | 0 | 800 / 800 | 0 |
| energy | 12.0 | 300 ms | 39/40 | 1 | 0 | 0 | 0 | 0 | 280 / 300 | 0 |
| energy | 12.0 | 500 ms | 40/40 | 0 | 0 | 0 | 0 | 0 | 480 / 500 | 0 |
| energy | 12.0 | 800 ms | 40/40 | 0 | 0 | 0 | 0 | 0 | 780 / 800 | 0 |
| energy | 15.0 | 300 ms | 38/40 | 1 | 0 | 1 | 0 | 0 | 280 / 300 | 20 |
| energy | 15.0 | 500 ms | 39/40 | 0 | 0 | 1 | 0 | 0 | 480 / 500 | 20 |
| energy | 15.0 | 800 ms | 40/40 | 0 | 0 | 0 | 0 | 0 | 780 / 800 | 20 |

## With noise

ok out of 40 / false alarms, per condition. `pinkN` = pink (fan-like) noise N dB below the speech level, so pink5 is loud noise. `clicks` = keyboard-like bursts as loud as speech.

| Detector | thr | hangover | clean | pink20 | pink10 | pink5 | clicks |
|---|---|---|---|---|---|---|---|
| silero | 0.3 | 300 ms | 39 / 0 | 39 / 0 | 39 / 0 | 39 / 0 | 39 / 0 |
| silero | 0.3 | 500 ms | 39 / 0 | 40 / 0 | 40 / 0 | 40 / 0 | 40 / 0 |
| silero | 0.3 | 800 ms | 40 / 0 | 40 / 0 | 40 / 0 | 40 / 0 | 40 / 0 |
| silero | 0.5 | 300 ms | 39 / 0 | 39 / 0 | 39 / 0 | 39 / 0 | 39 / 0 |
| silero | 0.5 | 500 ms | 39 / 0 | 39 / 0 | 40 / 0 | 40 / 0 | 39 / 0 |
| silero | 0.5 | 800 ms | 40 / 0 | 40 / 0 | 40 / 0 | 40 / 0 | 40 / 0 |
| silero | 0.7 | 300 ms | 39 / 0 | 39 / 0 | 39 / 0 | 39 / 0 | 39 / 0 |
| silero | 0.7 | 500 ms | 39 / 0 | 39 / 0 | 40 / 0 | 40 / 0 | 39 / 0 |
| silero | 0.7 | 800 ms | 40 / 0 | 40 / 0 | 40 / 0 | 40 / 0 | 40 / 0 |
| webrtc0 | 0.5 | 300 ms | 39 / 29 | 39 / 2 | 39 / 7 | 34 / 8 | 37 / 51 |
| webrtc0 | 0.5 | 500 ms | 32 / 14 | 40 / 2 | 39 / 6 | 36 / 6 | 21 / 19 |
| webrtc0 | 0.5 | 800 ms | 23 / 6 | 40 / 1 | 37 / 3 | 34 / 1 | 11 / 7 |
| webrtc1 | 0.5 | 300 ms | 39 / 24 | 39 / 1 | 38 / 4 | 31 / 2 | 37 / 51 |
| webrtc1 | 0.5 | 500 ms | 32 / 13 | 40 / 1 | 39 / 3 | 35 / 1 | 23 / 22 |
| webrtc1 | 0.5 | 800 ms | 27 / 7 | 40 / 0 | 40 / 2 | 36 / 1 | 12 / 9 |
| webrtc2 | 0.5 | 300 ms | 40 / 5 | 39 / 1 | 38 / 1 | 24 / 0 | 38 / 20 |
| webrtc2 | 0.5 | 500 ms | 36 / 3 | 39 / 1 | 39 / 1 | 31 / 0 | 30 / 10 |
| webrtc2 | 0.5 | 800 ms | 28 / 0 | 40 / 0 | 40 / 0 | 36 / 0 | 14 / 4 |
| webrtc3 | 0.5 | 300 ms | 39 / 0 | 39 / 1 | 38 / 1 | 22 / 0 | 39 / 7 |
| webrtc3 | 0.5 | 500 ms | 40 / 0 | 40 / 1 | 39 / 1 | 30 / 0 | 36 / 6 |
| webrtc3 | 0.5 | 800 ms | 40 / 0 | 40 / 0 | 39 / 1 | 35 / 0 | 25 / 2 |
| energy | 9.0 | 300 ms | 39 / 0 | 39 / 0 | 34 / 0 | 25 / 0 | 39 / 0 |
| energy | 9.0 | 500 ms | 40 / 0 | 39 / 0 | 36 / 0 | 31 / 0 | 36 / 0 |
| energy | 9.0 | 800 ms | 40 / 0 | 38 / 0 | 34 / 0 | 29 / 0 | 20 / 0 |
| energy | 12.0 | 300 ms | 39 / 0 | 37 / 0 | 28 / 0 | 6 / 0 | 39 / 0 |
| energy | 12.0 | 500 ms | 40 / 0 | 39 / 0 | 32 / 0 | 11 / 0 | 36 / 0 |
| energy | 12.0 | 800 ms | 40 / 0 | 40 / 0 | 33 / 0 | 13 / 0 | 21 / 0 |
| energy | 15.0 | 300 ms | 38 / 0 | 36 / 0 | 12 / 0 | 0 / 0 | 38 / 0 |
| energy | 15.0 | 500 ms | 39 / 0 | 38 / 0 | 22 / 0 | 0 / 0 | 39 / 0 |
| energy | 15.0 | 800 ms | 40 / 0 | 39 / 0 | 28 / 0 | 0 / 0 | 29 / 0 |

## Cost per frame (one CPU core)

| Detector | frame | time per frame | share of real time |
|---|---|---|---|
| silero | 32 ms | 0.93 ms | 2.9% |
| webrtc0 | 20 ms | 0.014 ms | 0.1% |
| webrtc1 | 20 ms | 0.01 ms | 0.1% |
| webrtc2 | 20 ms | 0.008 ms | 0.0% |
| webrtc3 | 20 ms | 0.011 ms | 0.1% |
| energy | 20 ms | 0.128 ms | 0.6% |
