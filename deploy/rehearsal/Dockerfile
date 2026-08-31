FROM python:3.10.9-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

RUN python -m venv /opt/venv \
    && addgroup --gid 10001 pinkdoo \
    && adduser --disabled-password --gecos "" --uid 10001 --gid 10001 pinkdoo \
    && mkdir -p /data/images \
    && chown -R 10001:10001 /app /data/images

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 pyproject.toml ./pyproject.toml
COPY deploy/rehearsal/app-entrypoint.sh /usr/local/bin/pinkdoo-entrypoint

RUN chmod 0755 /usr/local/bin/pinkdoo-entrypoint

USER 10001:10001

ENTRYPOINT ["/usr/local/bin/pinkdoo-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
