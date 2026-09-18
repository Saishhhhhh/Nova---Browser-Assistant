# VAD and Turn-Taking

## Experimentation

Test Silero VAD thresholds and timing configurations with short pauses, mid-sentence hesitations, varying speaking speeds, background noise, false starts, and commands followed by silence.

## Goal

Minimize dead air before the agent acts without cutting the user off mid-sentence.

## What To Measure

- End-of-speech latency
- Premature-cutoff rate
- Delayed-turn rate
- False-trigger rate
- Results by speaking speed and noise condition
- Threshold and hangover configuration

## Final Pick Requirements

- Reliably distinguish a pause from end-of-turn within approximately 300-500 ms
- Mid-sentence pauses are not treated as completed commands
- False starts and background noise are handled predictably
- Configuration is documented and reproducible

## Results

Record audio condition, threshold, silence duration, detected endpoint, actual endpoint, latency, cutoff result, false trigger result, and decision.
