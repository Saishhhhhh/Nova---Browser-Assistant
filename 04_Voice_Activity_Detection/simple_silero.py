"""The simplest possible Silero VAD demo: listen to the microphone and say when you are speaking.

  python simple_silero.py

Speak, then stop. Press Ctrl+C to quit.
"""
import queue

import numpy as np
import sounddevice as sd
import torch
from silero_vad import load_silero_vad

SAMPLE_RATE = 16000
FRAME = 512              # Silero needs exactly 512 samples (32 ms) per call at 16 kHz
THRESHOLD = 0.5          # probability above this = "speech"
SILENCE_TO_FINISH = 0.5  # seconds of silence before we say "you finished"

model = load_silero_vad()
audio_queue = queue.Queue()


def on_audio(indata, frames, time_info, status):
    audio_queue.put(indata[:, 0].copy())        # the microphone hands us small chunks; queue them


speaking = False
silent_frames = 0
buffer = np.zeros(0, dtype=np.float32)

print("Listening... speak, then stop. Ctrl+C to quit.")
with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=FRAME, callback=on_audio):
    try:
        while True:
            buffer = np.concatenate([buffer, audio_queue.get()])
            while len(buffer) >= FRAME:
                frame, buffer = buffer[:FRAME], buffer[FRAME:]
                probability = model(torch.from_numpy(frame), SAMPLE_RATE).item()   # 0.0 .. 1.0

                if probability >= THRESHOLD:
                    silent_frames = 0
                    if not speaking:
                        speaking = True
                        print("  speech started")
                elif speaking:
                    silent_frames += 1
                    if silent_frames * FRAME / SAMPLE_RATE >= SILENCE_TO_FINISH:
                        speaking = False
                        print("  you finished (0.5 s of silence)")
    except KeyboardInterrupt:
        print("bye")
