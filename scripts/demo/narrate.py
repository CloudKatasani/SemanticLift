"""Voice-over for the demo video, generated locally with the Kokoro neural TTS model (no cloud service).

    python scripts/demo/narrate.py speak OUT_DIR      # one WAV per narration line + durations.json
    python scripts/demo/narrate.py mix OUT_DIR TOTAL  # place clips at their caption times -> narration.wav

Needs ``pip install kokoro-onnx soundfile`` and the model files in KOKORO_DIR (default ./.kokoro):
kokoro-v1.0.int8.onnx and voices-v1.0.bin from https://github.com/thewh1teagle/kokoro-onnx/releases (model-files-v1.0).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
VOICE = os.environ.get("DEMO_VOICE", "af_heart")
SPEED = float(os.environ.get("DEMO_SPEED", "1.0"))
SR = 24000


def lines() -> dict:
    return {k: v for k, v in json.loads((HERE / "narration.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}


def speak(out: Path) -> None:
    from kokoro_onnx import Kokoro
    model_dir = Path(os.environ.get("KOKORO_DIR", ".kokoro"))
    tts = Kokoro(str(model_dir / "kokoro-v1.0.int8.onnx"), str(model_dir / "voices-v1.0.bin"))
    out.mkdir(parents=True, exist_ok=True)
    durations = {}
    for key, line in lines().items():
        audio, sr = tts.create(line.get("say") or line["text"], voice=VOICE, speed=SPEED, lang="en-us")
        assert sr == SR
        sf.write(out / f"{key}.wav", audio, SR)
        durations[key] = round(len(audio) / SR, 2)
        print(f"{key:16} {durations[key]:5.1f}s")
    (out / "durations.json").write_text(json.dumps(durations, indent=2))


def mix(out: Path, total: float) -> None:
    track = np.zeros(int((total + 1) * SR), dtype=np.float32)
    for seg in json.loads((out / "segments.json").read_text()):
        audio, _ = sf.read(out / f"{seg['key']}.wav", dtype="float32")
        i = int(seg["start"] * SR)
        track[i:i + len(audio)] += audio[: max(0, len(track) - i)]
    peak = float(np.max(np.abs(track))) or 1.0
    sf.write(out / "narration.wav", track * (0.9 / peak), SR)


if __name__ == "__main__":
    cmd, out = sys.argv[1], Path(sys.argv[2])
    speak(out) if cmd == "speak" else mix(out, float(sys.argv[3]))
