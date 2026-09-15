#!/bin/sh
set -eu

rate="${1:?rate is required}"
burst="${2:?burst is required}"
latency="${3:?latency is required}"

case "$rate" in
    5mbit) ;;
    *) echo "Unsupported performance bandwidth" >&2; exit 2 ;;
esac
case "$burst" in
    128kbit) ;;
    *) echo "Unsupported performance burst" >&2; exit 2 ;;
esac
case "$latency" in
    400ms) ;;
    *) echo "Unsupported performance latency" >&2; exit 2 ;;
esac

client_interface="$(ip -o route show default | awk 'NR == 1 { print $5 }')"
if [ -z "$client_interface" ]; then
    echo "Client-facing interface could not be resolved" >&2
    exit 1
fi
if [ "$(ip -o route show default | wc -l | tr -d ' ')" -ne 1 ]; then
    echo "Client-facing interface is ambiguous" >&2
    exit 1
fi

tc qdisc replace dev "$client_interface" root handle 1: tbf \
    rate "$rate" burst "$burst" latency "$latency"
printf '%s\n' "$client_interface" > /run/performance-client-interface
tc -d -s qdisc show dev "$client_interface"

cleanup() {
    tc qdisc del dev "$client_interface" root >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

while :; do
    sleep 3600 &
    wait "$!"
done
