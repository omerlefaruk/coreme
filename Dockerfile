FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir ".[hub]" \
    && adduser --disabled-password --gecos "" coreme \
    && mkdir -p /data && chown -R coreme:coreme /data

USER coreme

ENV COREME_HUB_DATA=/data

EXPOSE 8787

CMD ["sh", "-c", "coreme-hub migrate && exec coreme-hub serve --bind 0.0.0.0:8787"]
