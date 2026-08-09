FROM python:3.12-slim-bookworm AS database-client

# Keep the full client (and its Perl dependency) out of the runtime image.  The
# backup service only needs mysqldump, which is copied into the final stage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

FROM python:3.12-slim-bookworm AS python-dependencies
ENV PIP_NO_CACHE_DIR=1
WORKDIR /app

# mysqlclient needs a compiler and development headers only while its wheel is
# built.  Keep those packages out of the production image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-libmysqlclient-dev build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libmariadb3 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser
COPY --from=database-client /usr/bin/mariadb-dump /usr/local/bin/mariadb-dump
COPY --from=database-client /usr/bin/mysqldump /usr/local/bin/mysqldump
COPY --from=python-dependencies /install /usr/local
COPY . .
RUN chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
