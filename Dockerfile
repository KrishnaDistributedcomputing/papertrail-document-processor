FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

RUN apt-get update \
    && apt-get install --yes --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 papertrail \
    && mkdir -p /data/uploads /data/results "$TESSDATA_PREFIX" \
    && chown -R papertrail:papertrail /data

COPY requirements.txt /tmp/requirements.txt
COPY vendor /tmp/vendor
RUN python -m pip install --no-cache-dir --no-index --find-links=/tmp/vendor -r /tmp/requirements.txt \
    && rm -rf /tmp/vendor /tmp/requirements.txt

COPY --chown=papertrail:papertrail app /app/app
COPY --chown=papertrail:papertrail web /app/web
COPY models/eng.traineddata models/osd.traineddata "$TESSDATA_PREFIX"/

WORKDIR /app
USER papertrail
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test

USER root
COPY vendor /tmp/vendor
RUN python -m pip install --no-cache-dir --no-index --find-links=/tmp/vendor pytest \
    && rm -rf /tmp/vendor
COPY --chown=papertrail:papertrail tests /app/tests
USER papertrail

CMD ["pytest", "-q"]