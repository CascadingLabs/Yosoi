#!/bin/sh
set -eu
case "${QUERY_STRING:-}" in
    url=*)
        url=${QUERY_STRING#*url=}
        url=$(httpd -d "$url")
        case "$url" in http://fixture:8080/cgi-bin/request.cgi\?nonce=*) ;; *) exit 64 ;; esac
        nonce=${url#*nonce=}
        nonce=${nonce%%&*}
        case "$nonce" in ''|*[!0-9a-f]*) exit 64 ;; esac
        printf '%s\n' "$nonce" >> /state/redirects
        printf 'Status: 302 Found\r\nLocation: %s\r\nAccess-Control-Allow-Origin: *\r\nCache-Control: no-store\r\nContent-Length: 0\r\n\r\n' "$url"
        exit 0
        ;;
esac
printf '%s\n' "${QUERY_STRING:-}" >> /state/hits
case "${QUERY_STRING:-}" in
    *kind=timeout*)
        # Controlled latency exceeds the native 15-second HTTP deadline.
        # This is a delayed server response, not client readiness polling.
        sleep 20
        ;;
    *kind=signal*)
        channel=${QUERY_STRING#*channel=}
        channel=${channel%%&*}
        case "$channel" in ''|*[!0-9a-f]*) exit 64 ;; esac
        printf '%s\n' "$channel" > "/state/notify-$channel"
        ;;
esac
printf 'Access-Control-Allow-Origin: *\r\nCache-Control: no-store\r\n'
case "${QUERY_STRING:-}" in
    *kind=image*)
        printf 'Content-Type: image/svg+xml\r\n\r\n'
        printf '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect width="1" height="1" fill="red"/></svg>'
        ;;
    *kind=large*)
        printf 'Content-Type: text/plain\r\nContent-Length: 20971520\r\n\r\n'
        dd if=/dev/zero bs=1048576 count=20 2>/dev/null
        ;;
    *) printf 'Content-Type: text/plain\r\n\r\nhit' ;;
esac
