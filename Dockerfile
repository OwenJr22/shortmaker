FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces lance l'app avec l'utilisateur 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=7860 \
    WHISPER_MODEL=base \
    HTTPS_COOKIES=1 \
    DATA_DIR=/home/user/data

WORKDIR /home/user/app
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Télécharge le modèle Whisper « base » dès la construction (premier lancement plus rapide)
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')" \
 && mkdir -p /home/user/data

COPY --chown=user . .

EXPOSE 7860
CMD ["python", "app.py"]
