#!/bin/sh
set -eu

umask 077
secret_dir="${1:-./deploy/secrets}"
mkdir -p "$secret_dir"

create_secret() {
    name="$1"
    bytes="$2"
    target="$secret_dir/$name"
    if [ -e "$target" ]; then
        echo "Refusing to overwrite existing secret: $target" >&2
        exit 1
    fi
    openssl rand -base64 "$bytes" | tr -d '\n' > "$target"
    printf '\n' >> "$target"
    chmod 600 "$target"
}

create_secret django_secret_key 64
create_secret db_password_app 36
cp "$secret_dir/db_password_app" "$secret_dir/db_password_mysql"
create_secret db_root_password_mysql 48
create_secret redis_password_app 36
cp "$secret_dir/redis_password_app" "$secret_dir/redis_password_redis"
openssl rand -base64 32 | tr '/+' '_-' | tr -d '\n' > "$secret_dir/field_encryption_key"
printf '\n' >> "$secret_dir/field_encryption_key"
chmod 400 "$secret_dir"/*
if [ "$(id -u)" -eq 0 ]; then
    chown 10001:10001 \
        "$secret_dir/django_secret_key" \
        "$secret_dir/db_password_app" \
        "$secret_dir/redis_password_app" \
        "$secret_dir/field_encryption_key"
    chown 999:999 "$secret_dir/db_password_mysql" "$secret_dir/db_root_password_mysql"
    chown 999:1000 "$secret_dir/redis_password_redis"
fi
echo "Production secrets created in $secret_dir. Values were not printed."
