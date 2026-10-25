#!/bin/sh
set -eu
if [ "$#" -ne 0 ]; then
    echo 'Use the declared Moli environment profile; extra launch arguments are unsupported.' >&2
    exit 64
fi
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY http_proxy https_proxy all_proxy no_proxy
set -- serve --host 0.0.0.0 --port 9222 --profile-dir /tmp/moli-profile \
    --log-level warn --http-max-concurrent 8 --http-max-host-open 4 \
    --http-max-response-size 16777216 --http-timeout 15000
case "${MOLI_PROFILE:-dom}" in
    dom) ;;
    layout) set -- "$@" --layout ;;
    *) echo 'MOLI_PROFILE must be dom or layout.' >&2; exit 64 ;;
esac
case "${MOLI_RESOURCES:-0}" in
    0) ;;
    1) set -- "$@" --resource ;;
    *) echo 'MOLI_RESOURCES must be 0 or 1.' >&2; exit 64 ;;
esac
case "${MOLI_ALLOW_PRIVATE_NETWORKS:-0}" in
    0) set -- "$@" --block-private-networks ;;
    1) ;;
    *) echo 'MOLI_ALLOW_PRIVATE_NETWORKS must be 0 or 1.' >&2; exit 64 ;;
esac
exec /usr/local/bin/moli "$@"
