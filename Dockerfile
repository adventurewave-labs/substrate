# Substrate — core services image.
# The Railway service overrides CMD with its start command (migrate + idle until
# the W9 scheduler lane replaces the placeholder).
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

CMD ["substrate", "--help"]
