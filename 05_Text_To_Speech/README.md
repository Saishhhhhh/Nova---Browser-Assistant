# Text-to-Speech Talk-Back

## Experimentation

Compare Piper and Kokoro-82M locally. Generate short confirmations, clarification questions, progress updates, and error messages.

## Goal

Find the fastest local voice with acceptable naturalness for repeated interactive use.

## What To Measure

- Time to first audio
- Total generation time
- Real-time factor
- Intelligibility
- Naturalness during repeated use
- Interruption and replacement behavior
- CPU/GPU and memory use

## Final Pick Requirements

- Starts speaking within a few hundred milliseconds of receiving text
- Sounds natural enough not to be annoying when repeated
- Remains intelligible at normal playback speed
- Interruptions behave predictably

## Results

Record text, voice, model, hardware, audio format, time to first audio, total latency, listening ratings, interruption behavior, and decision.
