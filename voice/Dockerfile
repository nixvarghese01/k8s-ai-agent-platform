# Voice server: faster-whisper (speech-to-text) + Piper (text-to-speech), OpenAI-compatible
# (infra/k3s/voice/voice.yaml, README section 6.18). Models download into /models on first use.
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY voice_server.py .
USER 1000
ENV PYTHONUNBUFFERED=1 HOME=/tmp HF_HOME=/models/hf
EXPOSE 8000
CMD ["uvicorn", "voice_server:app", "--host", "0.0.0.0", "--port", "8000"]
