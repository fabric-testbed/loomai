#!/bin/sh
set -eu

# Nginx buffers multipart uploads and larger Jupyter saves to disk before
# proxying them. In the standalone container nginx runs as the non-root
# "fabric" user and cannot write the default /var/lib/nginx/body directory,
# producing raw nginx 500 responses:
#   open() "/var/lib/nginx/body/0000000001" failed (13: Permission denied)
#
# Keep the body buffer under the writable user-storage mount so the non-root
# nginx process can write request bodies reliably. This path is hardcoded to
# match `client_body_temp_path` in the nginx config (Dockerfile heredoc); do
# not parameterize it, or the helper could create a directory nginx never
# uses. Idempotent — safe to re-run.
UPLOAD_BODY_DIR="/home/fabric/work/.nginx-client-body"

# Create the dir (or repair its permissions). 1777 (world-writable + sticky) so
# the non-root nginx worker — which runs as the *container* user (fabric), not
# the config's `user www-data` (ignored when nginx isn't root) — can write
# request bodies here. chmod also self-heals a dir left 0700/www-data by an
# older build.
mkdir -p "$UPLOAD_BODY_DIR"
chmod 1777 "$UPLOAD_BODY_DIR"

# Do NOT run `nginx -t` or `nginx -s reload` here. This helper runs from the
# entrypoint as root, *before* supervisor starts nginx. Invoking nginx as root
# re-creates this dir owned by the config's `user` (www-data) with mode 0700 and
# leaves a root-owned /tmp/nginx.pid — both of which the non-root (fabric) nginx
# then cannot use, so nginx crashes on every boot (FATAL, 503). Ensuring the
# directory exists is all this helper needs to do; nginx picks it up when
# supervisor starts it.
