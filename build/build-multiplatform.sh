#!/usr/bin/env bash
set -euo pipefail

# Multi-platform Docker build script for fabric-webui
# Builds linux/amd64 + linux/arm64 images using docker buildx

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Defaults
REPO="${DOCKER_REPO:-fabrictestbed/loomai}"
TAG="latest"
PUSH=false
NO_CACHE=""
BUILDER_NAME="multiplatform"
PLATFORMS="linux/amd64,linux/arm64"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Build multi-platform Docker image for fabric-webui.

Options:
  --push        Push to Docker Hub after building (runs security audit first)
  --tag TAG     Image tag (default: latest)
  --repo REPO   Docker Hub repository (default: fabrictestbed/loomai)
  --no-cache    Force clean build with no layer cache
  -h, --help    Show this help message

Examples:
  $(basename "$0")                          # Build locally for both platforms
  $(basename "$0") --push                   # Audit + build + push as latest
  $(basename "$0") --push --tag v1.2.0      # Audit + build + push with custom tag
  $(basename "$0") --no-cache --push        # Clean build + audit + push
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --push)   PUSH=true; shift ;;
        --tag)    TAG="$2"; shift 2 ;;
        --repo)   REPO="$2"; shift 2 ;;
        --no-cache) NO_CACHE="--no-cache"; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

# Strip leading 'v' from tag (v1.2.3 → 1.2.3)
TAG="${TAG#v}"

IMAGE="${REPO}:${TAG}"
# When a custom version tag is provided, also push :latest
if [[ "$TAG" != "latest" ]]; then
    IMAGE_LATEST="${REPO}:latest"
else
    IMAGE_LATEST=""
fi

echo "=== fabric-webui multi-platform build ==="
echo "Image:     $IMAGE"
[[ -n "$IMAGE_LATEST" ]] && echo "Also:      $IMAGE_LATEST"
echo "Platforms: $PLATFORMS"
echo "Push:      $PUSH"
echo ""

# --- Check Docker login ---
if $PUSH; then
    if ! docker info 2>/dev/null | grep -q "Username"; then
        echo "ERROR: Not logged in to Docker Hub."
        echo "Run: docker login"
        exit 1
    fi
    echo "[OK] Docker Hub login detected"
fi

# --- Ensure buildx builder exists ---
if ! docker buildx inspect "$BUILDER_NAME" &>/dev/null; then
    echo "Creating buildx builder '$BUILDER_NAME'..."
    docker buildx create --name "$BUILDER_NAME" --driver docker-container --use
    docker buildx inspect --bootstrap "$BUILDER_NAME"
else
    docker buildx use "$BUILDER_NAME"
    echo "[OK] Using existing builder '$BUILDER_NAME'"
fi
echo ""

# --- Build ---
BUILD_ARGS=(
    --platform "$PLATFORMS"
    --tag "$IMAGE"
    -f "$PROJECT_ROOT/Dockerfile"
)
# Add :latest tag when pushing a versioned build
if [[ -n "$IMAGE_LATEST" ]]; then
    BUILD_ARGS+=(--tag "$IMAGE_LATEST")
fi

if [[ -n "$NO_CACHE" ]]; then
    BUILD_ARGS+=(--no-cache)
fi

if $PUSH; then
    # Build single-platform amd64 image into local daemon for audit
    # (--load can't handle multi-platform manifests, so we use separate args here)
    AUDIT_ARGS=(
        --platform linux/amd64
        --tag "$IMAGE"
        -f "$PROJECT_ROOT/Dockerfile"
        --load
    )
    if [[ -n "$NO_CACHE" ]]; then
        AUDIT_ARGS+=(--no-cache)
    fi

    echo "Building amd64 image for audit..."
    docker buildx build "${AUDIT_ARGS[@]}" "$PROJECT_ROOT"

    echo ""
    echo "=== Running security audit ==="
    if ! "$SCRIPT_DIR/audit-image.sh" "$IMAGE"; then
        echo ""
        echo "ABORT: Security audit failed. Image was NOT pushed."
        exit 1
    fi
    echo ""

    echo "Audit passed. Building and pushing multi-platform image..."
    docker buildx build "${BUILD_ARGS[@]}" --push "$PROJECT_ROOT"

    echo ""
    echo "=== Push complete ==="
    echo "Pushed: $IMAGE"
    [[ -n "$IMAGE_LATEST" ]] && echo "Pushed: $IMAGE_LATEST"
    echo ""
    echo "Inspect manifest with:"
    echo "  docker buildx imagetools inspect $IMAGE"
    docker buildx imagetools inspect "$IMAGE" 2>/dev/null | head -20 || true
else
    echo "Building locally (no push)..."
    # --load only works for single platform; for local multi-platform just build to cache
    docker buildx build "${BUILD_ARGS[@]}" "$PROJECT_ROOT"
    echo ""
    echo "=== Build complete (local only) ==="
    echo "To push, re-run with --push"
fi
