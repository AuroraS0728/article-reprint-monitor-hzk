FROM python:3.12.13-alpine3.24 AS database-client

# Keep the full client out of the runtime image. The backup service only needs
# mysqldump; its shared data is provided by the runtime mariadb-common package.
RUN apk add --no-cache mariadb-client

FROM python:3.12.13-alpine3.24 AS python-dependencies
ENV PIP_NO_CACHE_DIR=1
WORKDIR /app

# mysqlclient needs a compiler and development headers only while its wheel is
# built.  Keep those packages out of the production image.
RUN apk add --no-cache build-base mariadb-connector-c-dev pkgconf
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.12.13-alpine3.24
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apk upgrade --no-cache \
    && apk add --no-cache libgcc libstdc++ mariadb-common mariadb-connector-c \
    && addgroup -S -g 10001 appuser \
    && adduser -S -D -H -u 10001 -G appuser appuser
COPY --from=database-client /usr/bin/mariadb-dump /usr/local/bin/mariadb-dump
COPY --from=database-client /usr/bin/mysqldump /usr/local/bin/mysqldump
COPY --from=python-dependencies /install /usr/local
COPY . .
RUN chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
