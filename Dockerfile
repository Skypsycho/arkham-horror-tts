# Arkham Horror TTS — web app image.
# Code only: campaigns, audio, PDFs, settings and the login live in the
# volume mounted at /storage (see docker-compose.yml).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ARKHAM_STORAGE=/storage

WORKDIR /app

COPY requirements.txt constraints.txt ./
RUN pip install -r requirements.txt -c constraints.txt waitress==3.0.2

COPY *.py ./
COPY templates/ templates/
COPY static/ static/
COPY Banner5.jpg Background.jpg ./

VOLUME /storage
EXPOSE 5000

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/login', timeout=4)" || exit 1

# One process (bulk TTS jobs are tracked in memory), several threads
CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "--threads=8", "app:app"]
