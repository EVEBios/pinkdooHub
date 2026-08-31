#!/bin/sh
set -eu

read_secret() {
    secret_path="$1"
    if [ ! -f "$secret_path" ]; then
        echo "Required runtime Secret is unavailable" >&2
        exit 1
    fi
    value="$(tr -d '\r\n' < "$secret_path")"
    if [ -z "$value" ]; then
        echo "Required runtime Secret is empty" >&2
        exit 1
    fi
    printf '%s' "$value"
}

DB_PASSWORD="$(read_secret /run/secrets/mysql_app_password)"
JWT_SECRET_KEY="$(read_secret /run/secrets/jwt_secret)"
redis_password="$(read_secret /run/secrets/redis_password)"

export DB_PASSWORD JWT_SECRET_KEY
export REDIS_URL="redis://:${redis_password}@redis:6379/0"

if [ -f /run/secrets/bootstrap_password ]; then
    PINKDOOHUB_BOOTSTRAP_PASSWORD="$(
        read_secret /run/secrets/bootstrap_password
    )"
    export PINKDOOHUB_BOOTSTRAP_PASSWORD
fi

unset redis_password
exec "$@"
