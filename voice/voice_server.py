"""Voice server: OpenAI-compatible speech-to-text and text-to-speech on CPU (README §6.18).

    POST /v1/audio/transcriptions  multipart "file" (+ "language")  -> {"text": "..."}    faster-whisper
    POST /v1/audio/speech          {"input": "...", "voice": "..."}  -> audio/wav            Piper
    GET  /v1/models, GET /health

Open WebUI's microphone and read-aloud buttons use it through their "OpenAI" audio engines
(ui/open-webui.yaml), so voice works in the existing chat. Models are downloaded on first use
into /models (a volume) and stay there.
"""

import io
import logging
import os
import tempfile
import threading
import time
import wave
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

MODELS = Path(os.environ.get("MODELS_DIR", "/models"))
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")  # tiny | base | small: speed vs accuracy
PIPER_VOICE = os.environ.get("PIPER_VOICE", "en_US-amy-medium")
# the Piper voices a request may pick by name; anything else (OpenAI's alloy, nova, ...) gets
# PIPER_VOICE. A request never names a file or a download directly.
PIPER_VOICES = [v.strip() for v in os.environ.get("PIPER_VOICES", PIPER_VOICE).split(",") if v.strip()]
THREADS = int(os.environ.get("CPU_THREADS", "4"))

log = logging.getLogger("voice")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
app = FastAPI(title="Local voice (Whisper + Piper)")
_lock = threading.Lock()
_whisper = None
_voices: dict = {}


def whisper():
    global _whisper
    with _lock:
        if _whisper is None:
            from faster_whisper import WhisperModel

            t = time.time()
            _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=THREADS,
                                    download_root=str(MODELS / "whisper"))
            log.info("loaded whisper %s in %.1fs", WHISPER_MODEL, time.time() - t)
    return _whisper


def piper(name: str):
    with _lock:
        if name not in _voices:
            from piper import PiperVoice
            from piper.download_voices import download_voice

            folder = (MODELS / "piper").resolve()
            folder.mkdir(parents=True, exist_ok=True)
            onnx = (folder / f"{name}.onnx").resolve()
            if onnx.parent != folder:
                raise ValueError(f"bad voice name {name!r}")
            if not onnx.exists():
                download_voice(name, folder)
            _voices[name] = PiperVoice.load(str(onnx))
            log.info("loaded piper voice %s", name)
    return _voices[name]


def transcribe_file(path: str, language: str | None) -> tuple[str, float, str]:
    """(text, audio seconds, detected language) of an audio file, with Whisper."""
    segments, info = whisper().transcribe(path, language=language or None, beam_size=1, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip(), info.duration, info.language


def synthesize(text: str, voice: str, speed: float) -> bytes:
    """WAV bytes of `text` spoken by a Piper voice."""
    from piper import SynthesisConfig

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        piper(voice).synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=1.0 / max(speed, 0.25)))
    return buf.getvalue()


@app.get("/health")
def health():
    return {"status": "ok", "whisper_loaded": _whisper is not None, "voices_loaded": list(_voices)}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": f"whisper-{WHISPER_MODEL}", "object": "model"},
                                       {"id": f"piper-{PIPER_VOICE}", "object": "model"}]}


@app.post("/v1/audio/transcriptions")
async def transcribe(file: UploadFile = File(...), model: str = Form("whisper-1"),
                     language: str | None = Form(None), response_format: str = Form("json")):
    """OpenAI-style transcription; the model name is accepted and ignored (one Whisper model)."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty audio")
    with tempfile.NamedTemporaryFile(suffix=Path(file.filename or "audio").suffix or ".wav") as f:
        f.write(data)
        f.flush()
        t = time.time()
        text, seconds, lang = transcribe_file(f.name, language)
    log.info("transcribed %.1fs of audio (%s) in %.1fs", seconds, lang, time.time() - t)
    if response_format == "text":
        return Response(text, media_type="text/plain")
    return {"text": text}


class SpeechRequest(BaseModel):
    input: str
    model: str = "tts-1"
    voice: str | None = None
    response_format: str = "wav"
    speed: float = 1.0


@app.post("/v1/audio/speech")
def speech(req: SpeechRequest):
    """OpenAI-style speech; returns WAV (browsers play it; no ffmpeg needed for mp3)."""
    if not req.input.strip():
        raise HTTPException(400, "empty input")
    # OpenAI voice names (alloy, nova, ...) and unknown ones map to the configured Piper voice
    name = next((v for v in PIPER_VOICES if v == req.voice), PIPER_VOICE)
    t = time.time()
    audio = synthesize(req.input, name, req.speed)
    log.info("spoke %d chars in %.1fs", len(req.input), time.time() - t)
    return Response(audio, media_type="audio/wav")
