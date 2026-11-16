# Substrate — core services image.
# The Railway service overrides CMD with its start command (migrate + idle until
# the W9 scheduler lane replaces the placeholder).
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir . && \
    python -c "import substrate.db as d; assert (d.MIGRATIONS_DIR / '001_init.sql').exists(), 'migrations missing from the installed package'"

# The guard checks the INSTALLED runner's actual resolution path — a source-tree
# copy alone would leave site-packages without migrations and the deploy would
# report "nothing pending" over an empty database (caught live, Railway #1).

CMD ["substrate", "--help"]
