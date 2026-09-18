# Speech-to-Text

## Experimentation

Compare faster-whisper base and small models, including quantized local variants, with Moonshine. Use Deepgram as a cloud quality-ceiling reference. Test streaming command-style speech with URLs, site names, tab/click vocabulary, different speaking speeds, and background noise.

## Goal

Find the lowest time-to-first-token and total transcription latency at an acceptable word-error rate.

## What To Measure

- Time to first partial transcript
- Time to final transcript
- Word-error rate
- Command success rate
- Accuracy of URLs, site names, and browser terms
- Streaming correction rate
- CPU/GPU use and network dependency

## Final Pick Requirements

- Partial transcript begins within approximately 200-300 ms of speech start
- Short command finalizes well under 1 second where hardware permits
- Domain terms remain accurate
- Streaming corrections do not trigger unsafe premature actions

## Results

Record audio condition, language, model, quantization, hardware, chunk size, latency, transcript, reference text, word-error rate, command result, and decision.
