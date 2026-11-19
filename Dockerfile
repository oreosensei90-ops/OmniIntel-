FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir '.[service,youtube,asr]' \
    && useradd --system --uid 10001 --create-home omniintel \
    && mkdir -p /var/lib/omniintel \
    && chown -R omniintel:omniintel /var/lib/omniintel /app

USER omniintel
EXPOSE 8000
ENTRYPOINT ["bash", "/app/deploy/start-service.sh"]
