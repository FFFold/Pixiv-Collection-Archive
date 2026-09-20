#!/bin/sh
# Fix bind-mount ownership, then drop privileges and run the app as appuser.
#
# A host bind mount (./data:/data) hides the image's own /data ownership, and
# Docker creates a missing bind-mount source as root:root, which appuser
# cannot write. When started as root, chown the data dir (recursively only
# when the top level is wrong, so normal restarts stay cheap) and re-exec as
# appuser via gosu. When already running as appuser, just exec the command.
set -e

if [ "$(id -u)" = "0" ]; then
    DATA_DIR="${DATA_DIR:-/data}"
    mkdir -p "$DATA_DIR"
    if [ "$(stat -c '%u' "$DATA_DIR")" != "1000" ]; then
        chown -R appuser:appuser "$DATA_DIR"
    fi
    exec gosu appuser "$@"
fi

exec "$@"
