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

# Gate B 可由集中 Secret Manager 以只读文件注入；Gate A 未启用微信时
# 不挂载这两个文件，因此保持现有运行边界不变。
if [ -f /run/secrets/wechat_app_secret ]; then
    WECHAT_APP_SECRET="$(read_secret /run/secrets/wechat_app_secret)"
    export WECHAT_APP_SECRET
fi

if [ -f /run/secrets/external_identity_pepper ]; then
    EXTERNAL_IDENTITY_PEPPER="$(
        read_secret /run/secrets/external_identity_pepper
    )"
    export EXTERNAL_IDENTITY_PEPPER
fi

unset redis_password
exec "$@"
