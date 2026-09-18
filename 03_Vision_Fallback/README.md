# Vision Fallback

## Experimentation

Compare a small local VLM, such as Qwen2-VL-2B/7B or Moondream, with an API vision model. Invoke vision only when DOM extraction cannot represent the target, including canvas content, custom widgets, and image-heavy UI.

## Goal

Confirm that vision is an exception path and select the cheapest model that grounds click coordinates accurately.

## What To Measure

- Percentage of steps that trigger vision
- Coordinate error in pixels
- Successful click rate
- Retry rate
- Fallback latency
- Local resource use and API cost
- Uncertainty detection and recovery behavior

## Final Pick Requirements

- Triggered only for a small, documented percentage of steps
- Coordinates accurate enough that retries remain rare
- Uncertainty detected rather than converted into a blind click
- Latency acceptable for interactive use

## Results

Record the page type, target, screenshot conditions, model, hardware, coordinates, pixel error, latency, retries, result, and failure example.
