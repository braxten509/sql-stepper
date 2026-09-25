# SQL Stepper for Cloud Run: the app plus its own private MySQL, set up at build time so it starts fast
FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
RUN apt-get update && apt-get install -y --no-install-recommends libaio1 libnuma1 tzdata=2026c-0+deb12u1 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir sqlglot==30.19.0 pymysql==1.2.3 \
 && useradd -m app
USER app
WORKDIR /home/app
ENV XDG_DATA_HOME=/home/app/data HOST=0.0.0.0 NO_BROWSER=1 TRUST_PROXY=1 PYTHONUNBUFFERED=1
COPY --chown=app app.py index.html test_stepper.py ./
# only mysqld and its libraries are needed (drops about 400 MB: client tools, Japanese full-text data, headers)
RUN python -c "import app; app.install()" && cd data/sql-stepper/mysql \
 && find bin -type f ! -name mysqld -delete && rm -rf lib/mecab lib/*.a include man docs
CMD ["python", "app.py"]
