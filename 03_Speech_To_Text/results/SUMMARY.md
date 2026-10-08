# Speech-to-text results

| Engine | Mode | WER | Exact | Intent | Key terms | Median (ms) | Slowest (ms) | Silence words | Errors |
|---|---|---|---|---|---|---|---|---|---|
| assemblyai+boost | batch | 0.6% | 97% | 97% | 100% | 2595 | 3827 | 0 | 0 |
| assemblyai | batch | 0.6% | 97% | 97% | 100% | 2651 | 4099 | 0 | 0 |
| assemblyai:universal-3-5-pro | batch | 0.6% | 97% | 97% | 100% | 2175 | 4813 | 0 | 0 |
| elevenlabs+boost | batch | 0.6% | 97% | 97% | 100% | 832 | 1554 | 0 | 0 |
| elevenlabs | batch | 0.6% | 97% | 97% | 100% | 792 | 1222 | 0 | 0 |
| groq:whisper-large-v3-turbo | batch | 1.2% | 94% | 94% | 95% | 183 | 218 | 0 | 0 |
| groq:whisper-large-v3 | batch | 1.7% | 94% | 94% | 100% | 208 | 256 | 1 | 0 |
| sarvam | batch | 1.7% | 94% | 94% | 100% | 143 | 264 | 0 | 0 |
| sarvam:saaras:v4 | batch | 1.7% | 94% | 94% | 100% | 137 | 525 | 0 | 0 |
| deepgram+boost | batch | 2.3% | 92% | 92% | 100% | 374 | 1276 | 0 | 0 |
| deepgram | batch | 2.3% | 92% | 92% | 100% | 598 | 2179 | 0 | 0 |
| deepgram | stream | 2.3% | 92% | 92% | 100% | 743 | 3475 | n/a | 0 |
| assemblyai:universal-2 | batch | 2.9% | 92% | 92% | 100% | 1563 | 2643 | 0 | 0 |
| sarvam:saaras:v3 | batch | 4.0% | 89% | 89% | 95% | 126 | 638 | 1 | 0 |
| sarvam:saarika:v2.5 | batch | 4.0% | 89% | 89% | 95% | 135 | 434 | 1 | 0 |
| elevenlabs_rt | stream | 4.6% | 86% | 86% | 95% | 999 | 1287 | n/a | 4 |
| deepgram_flux | stream | 5.2% | 83% | 83% | 85% | 1229 | 1455 | n/a | 0 |
| assemblyai | stream | 9.5% | 94% | 94% | 88% | 650 | 1745 | n/a | 6 |

Batch latency = time to upload one clip and get the transcript back. Stream latency = time from the end of speech to the final transcript, with audio sent at real-time speed.
