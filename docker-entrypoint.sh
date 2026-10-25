#!/bin/sh
set -e

uvicorn app.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!

nginx -g 'daemon off;' &
NGINX_PID=$!

trap 'kill $API_PID $NGINX_PID 2>/dev/null || true' TERM INT EXIT

wait -n $API_PID $NGINX_PID
exit $?
