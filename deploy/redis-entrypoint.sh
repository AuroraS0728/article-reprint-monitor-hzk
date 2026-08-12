#!/bin/sh
set -eu

exec redis-server \
    --appendonly yes \
    --requirepass "$(cat /run/secrets/redis_password)"
