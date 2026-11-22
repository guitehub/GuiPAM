#!/bin/sh
# HEALTHCHECK de l'image : interroge /healthz sur l'écouteur qui existe.
# - écouteur HTTP présent (GUIPAM_HTTP_MODE redirect ou proxy, ou GUIPAM_TLS=off) : http://, /healthz y
#   est servi directement dans tous les modes ;
# - sinon (GUIPAM_HTTP_MODE=off) : https:// sans vérification du certificat (auto-signé, joint par localhost).
tls=$(printf '%s' "${GUIPAM_TLS:-auto}" | tr '[:upper:]' '[:lower:]')
mode=$(printf '%s' "${GUIPAM_HTTP_MODE:-redirect}" | tr '[:upper:]' '[:lower:]')
if [ "$tls" != "off" ] && [ "$mode" = "off" ]; then
    exec curl -fsSk --max-time 4 "https://localhost:${GUIPAM_HTTPS_PORT:-8443}/healthz"
fi
exec curl -fsS --max-time 4 "http://localhost:${GUIPAM_HTTP_PORT:-${GUIPAM_PORT:-8080}}/healthz"
