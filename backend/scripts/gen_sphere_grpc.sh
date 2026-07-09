#!/usr/bin/env bash
# Regenerate the vendored MergeTB / SPHERE portal gRPC client.
#
# Reproduces backend/app/sphere_grpc/ from upstream protobufs. The portal's gRPC
# server reflection advertises the services but omits the transitive
# `mergetb/xir/pb/core.proto` descriptor, so we must compile from source protos
# (gitlab.com/mergetb/api + its deps) rather than from reflection.
#
# Requires: git, curl, and grpcio-tools in the active venv
#   (pip install grpcio-tools).
#
# Usage:  source backend/.venv/bin/activate && backend/scripts/gen_sphere_grpc.sh
set -euo pipefail

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # backend/
DEST="$HERE/app/sphere_grpc"
STAGE="$WORK/protos"

echo "==> cloning upstream proto sources into $WORK"
git clone --depth 1 https://gitlab.com/mergetb/api.git              "$WORK/api"
git clone --depth 1 https://gitlab.com/mergetb/xir.git              "$WORK/xir"
git clone --depth 1 https://gitlab.com/mergetb/tech/reconcile.git   "$WORK/reconcile"
git clone --depth 1 https://github.com/mwitkow/go-proto-validators.git "$WORK/validators"
git clone --depth 1 https://github.com/grpc-ecosystem/grpc-gateway.git  "$WORK/gw"

echo "==> staging import tree"
mkdir -p "$STAGE"/{portal/v1,google/api,mergetb/xir/pb,mergetb/tech/reconcile,mwitkow/go-proto-validators,protoc-gen-openapiv2/options}
cp "$WORK"/api/proto/portal/v1/*.proto              "$STAGE/portal/v1/"
cp "$WORK"/xir/pb/core.proto                        "$STAGE/mergetb/xir/pb/"
cp "$WORK"/reconcile/taskstatus.proto               "$STAGE/mergetb/tech/reconcile/"
cp "$WORK"/validators/validator.proto               "$STAGE/mwitkow/go-proto-validators/"
cp "$WORK"/gw/protoc-gen-openapiv2/options/*.proto  "$STAGE/protoc-gen-openapiv2/options/"

# google/api annotations live in googleapis (no longer vendored by grpc-gateway).
GAPI=https://raw.githubusercontent.com/googleapis/googleapis/master/google/api
for f in annotations.proto http.proto field_behavior.proto; do
  curl -fsSL "$GAPI/$f" -o "$STAGE/google/api/$f"
done

echo "==> generating python stubs into $DEST"
rm -rf "$DEST"
mkdir -p "$DEST"
python -m grpc_tools.protoc -I"$STAGE" \
  --python_out="$DEST" --grpc_python_out="$DEST" \
  "$STAGE"/portal/v1/*.proto \
  "$STAGE"/mergetb/xir/pb/core.proto \
  "$STAGE"/mergetb/tech/reconcile/taskstatus.proto \
  "$STAGE"/mwitkow/go-proto-validators/validator.proto \
  "$STAGE"/google/api/*.proto \
  "$STAGE"/protoc-gen-openapiv2/options/*.proto

find "$DEST" -name "__pycache__" -type d -prune -exec rm -rf {} +

# Restore the package loader + helpers (overwritten by the rm -rf above).
git -C "$HERE/.." checkout -- backend/app/sphere_grpc/__init__.py backend/app/sphere_grpc/client.py 2>/dev/null || \
  echo "NOTE: re-add app/sphere_grpc/__init__.py and client.py (not generated)."

echo "==> done. Vendored client in $DEST"
