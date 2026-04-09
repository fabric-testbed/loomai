#!/usr/bin/env bash
#
# LoomAI Install Script
# Install, upgrade, uninstall, or check status of LoomAI.
#
# Usage:
#   bash install.sh              # Install or upgrade
#   bash install.sh --clean      # Remove everything and reinstall from scratch
#   bash install.sh --uninstall  # Remove LoomAI
#   bash install.sh --status     # Show installation info
#   bash install.sh --no-start   # Download and pull only
#   bash install.sh -y           # Skip confirmation prompts
#
# One-liner:
#   curl -fsSL https://raw.githubusercontent.com/fabric-testbed/loomai/main/install.sh | bash
#

set -euo pipefail

# --- Constants ---
IMAGE="fabrictestbed/loomai:latest"
COMPOSE_URL="https://raw.githubusercontent.com/fabric-testbed/loomai/main/docker-compose.yml"
COMPOSE_FILE="docker-compose.yml"
HEALTH_URL="http://localhost:8000/api/health"
UI_URL="http://localhost:3000"
CONTAINER_NAME="loomai"
VOLUME_NAME="fabric_work"
HEALTH_TIMEOUT=60

# --- Flags ---
ACTION="install"
AUTO_YES=false
NO_START=false

# Auto-yes when piped (no TTY on stdin)
if [[ ! -t 0 ]]; then
    AUTO_YES=true
fi

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# --- Helpers ---
info()    { echo -e "${BLUE}ℹ${NC}  $*"; }
success() { echo -e "${GREEN}✔${NC}  $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "${RED}✖${NC}  $*" >&2; }
header()  { echo -e "\n${BOLD}$*${NC}"; }

confirm() {
    if $AUTO_YES; then return 0; fi
    local prompt="$1 [y/N] "
    read -rp "$prompt" answer
    case "$answer" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) return 1 ;;
    esac
}

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --uninstall) ACTION="uninstall"; shift ;;
        --clean)     ACTION="clean"; shift ;;
        --status)    ACTION="status"; shift ;;
        --no-start)  NO_START=true; shift ;;
        -y|--yes)    AUTO_YES=true; shift ;;
        -h|--help)
            echo "Usage: install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  (no args)      Install or upgrade LoomAI"
            echo "  --clean        Remove everything (container, images, data) and reinstall"
            echo "  --uninstall    Remove LoomAI containers, images, and optionally data"
            echo "  --status       Show current installation info"
            echo "  --no-start     Download compose file and pull image but don't start"
            echo "  -y, --yes      Skip confirmation prompts"
            echo "  -h, --help     Show this help message"
            exit 0
            ;;
        *) error "Unknown option: $1"; exit 1 ;;
    esac
done

# --- Prerequisite checks ---
check_prerequisites() {
    local ok=true

    if ! command -v docker &>/dev/null; then
        error "Docker is not installed. Please install Docker first: https://docs.docker.com/get-docker/"
        ok=false
    fi

    if $ok && ! docker compose version &>/dev/null; then
        error "Docker Compose v2 is not available. Please update Docker or install the compose plugin."
        ok=false
    fi

    if $ok && ! docker info &>/dev/null 2>&1; then
        error "Docker daemon is not running. Please start Docker and try again."
        ok=false
    fi

    if ! $ok; then exit 1; fi
}

# --- Detection helpers ---
has_compose_file() {
    [[ -f "$COMPOSE_FILE" ]]
}

has_running_container() {
    if has_compose_file; then
        docker compose ps --status running 2>/dev/null | grep -q "$CONTAINER_NAME" 2>/dev/null
    else
        return 1
    fi
}

has_any_container() {
    if has_compose_file; then
        docker compose ps -a 2>/dev/null | grep -q "$CONTAINER_NAME" 2>/dev/null
    else
        return 1
    fi
}

has_image() {
    docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -q "^fabrictestbed/loomai:" 2>/dev/null
}

has_volume() {
    docker volume ls --format '{{.Name}}' 2>/dev/null | grep -q "^.*${VOLUME_NAME}$" 2>/dev/null
}

get_current_image_id() {
    docker images --format '{{.ID}}' "fabrictestbed/loomai:latest" 2>/dev/null | head -1
}

get_current_image_created() {
    docker images --format '{{.CreatedAt}}' "fabrictestbed/loomai:latest" 2>/dev/null | head -1
}

# --- Health check ---
wait_for_health() {
    info "Waiting for LoomAI to become healthy (up to ${HEALTH_TIMEOUT}s)..."
    local elapsed=0
    while [[ $elapsed -lt $HEALTH_TIMEOUT ]]; do
        if curl -sf "$HEALTH_URL" &>/dev/null; then
            success "LoomAI is healthy!"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    warn "Health check timed out after ${HEALTH_TIMEOUT}s. The container may still be starting."
    warn "Check status with: docker compose logs"
    return 1
}

# --- Actions ---

do_status() {
    header "LoomAI Status"
    echo ""

    # Compose file
    if has_compose_file; then
        success "Compose file: ${COMPOSE_FILE} (found)"
    else
        warn "Compose file: not found in current directory"
    fi

    # Image
    if has_image; then
        local created
        created=$(get_current_image_created)
        success "Image: fabrictestbed/loomai:latest (built ${created})"
    else
        warn "Image: not found"
    fi

    # Container
    if has_running_container; then
        success "Container: running"
        # Show port bindings
        local ports
        ports=$(docker compose port "$CONTAINER_NAME" 3000 2>/dev/null || echo "unknown")
        info "  UI: http://localhost:3000"
        info "  API: http://localhost:8000"
        info "  Jupyter: http://localhost:8889"
    elif has_any_container; then
        warn "Container: stopped"
    else
        warn "Container: not found"
    fi

    # Volume
    if has_volume; then
        local vol_name
        vol_name=$(docker volume ls --format '{{.Name}}' 2>/dev/null | grep "${VOLUME_NAME}$" | head -1)
        success "Data volume: ${vol_name}"
    else
        warn "Data volume: not found"
    fi

    # Health
    if curl -sf "$HEALTH_URL" &>/dev/null; then
        success "Health: OK"
    else
        warn "Health: not reachable"
    fi

    echo ""
}

do_install() {
    local is_upgrade=false
    local old_image_id=""

    # Detect existing installation
    if has_image || has_any_container; then
        is_upgrade=true
        old_image_id=$(get_current_image_id)
    fi

    if $is_upgrade; then
        header "Existing LoomAI installation detected"
        echo ""

        if has_image; then
            local created
            created=$(get_current_image_created)
            info "Current image built: ${created}"
        fi

        if has_volume; then
            info "Data volume exists (credentials, slices, artifacts)."
        fi

        if ! $AUTO_YES; then
            echo ""
            echo "  1) Upgrade — pull latest image, keep existing data"
            echo "  2) Clean install — remove everything and start fresh"
            echo "  3) Cancel"
            echo ""
            local choice
            read -rp "Choose [1/2/3] (default: 1): " choice
            case "$choice" in
                2)
                    echo ""
                    do_clean
                    return
                    ;;
                3)
                    info "Cancelled."
                    exit 0
                    ;;
                *)
                    # Default: upgrade (keep data)
                    ;;
            esac
        fi

        echo ""

        # Ensure compose file exists (may have image/volume from a different directory)
        if ! has_compose_file; then
            info "Downloading docker-compose.yml..."
            curl -fsSL "$COMPOSE_URL" -o "$COMPOSE_FILE"
            success "Compose file downloaded."
        fi

        # Stop running container
        if has_any_container; then
            info "Stopping current container..."
            docker compose down 2>/dev/null || true
            success "Container stopped."
        fi

        # Pull latest image
        info "Pulling latest image..."
        docker compose pull
        success "Image pulled."

        # Clean up old dangling images
        local new_image_id
        new_image_id=$(get_current_image_id)
        if [[ -n "$old_image_id" && "$old_image_id" != "$new_image_id" ]]; then
            info "Cleaning up old image..."
            docker rmi "$old_image_id" 2>/dev/null || true
        fi

        # Start
        if $NO_START; then
            success "Upgrade complete (--no-start: container not started)."
            return
        fi

        info "Starting LoomAI..."
        docker compose up -d
        success "Container started."

    else
        header "Installing LoomAI"
        echo ""

        if ! $AUTO_YES; then
            echo "This will:"
            echo "  • Download docker-compose.yml to the current directory"
            echo "  • Pull the LoomAI Docker image (~2 GB)"
            echo "  • Start LoomAI on ports 3000, 8000, 8889, 9100-9199"
            echo ""
            if ! confirm "Proceed with installation?"; then
                info "Installation cancelled."
                exit 0
            fi
        fi

        echo ""

        # Download compose file
        if ! has_compose_file; then
            info "Downloading docker-compose.yml..."
            curl -fsSL "$COMPOSE_URL" -o "$COMPOSE_FILE"
            success "Compose file downloaded."
        else
            info "Using existing docker-compose.yml"
        fi

        # Pull image
        info "Pulling LoomAI image (this may take a few minutes)..."
        docker compose pull
        success "Image pulled."

        # Start
        if $NO_START; then
            success "Installation complete (--no-start: container not started)."
            info "Run 'docker compose up -d' when ready to start."
            return
        fi

        info "Starting LoomAI..."
        docker compose up -d
        success "Container started."
    fi

    echo ""

    # Health check
    wait_for_health || true

    echo ""
    header "LoomAI is ready!"
    echo ""
    echo -e "  ${BOLD}Web UI:${NC}     ${UI_URL}"
    echo -e "  ${BOLD}API:${NC}        http://localhost:8000"
    echo -e "  ${BOLD}Jupyter:${NC}    http://localhost:8889"
    echo ""
    echo "  Manage:     docker compose logs -f    (view logs)"
    echo "  Upgrade:    bash install.sh            (pull latest)"
    echo "  Uninstall:  bash install.sh --uninstall"
    echo ""
}

do_uninstall() {
    header "Uninstalling LoomAI"
    echo ""

    if ! has_image && ! has_any_container && ! has_volume && ! has_compose_file; then
        info "LoomAI is not installed. Nothing to do."
        exit 0
    fi

    if ! $AUTO_YES; then
        if ! confirm "Remove LoomAI containers and images?"; then
            info "Uninstall cancelled."
            exit 0
        fi
    fi

    echo ""

    # Stop and remove containers
    if has_compose_file && has_any_container; then
        info "Stopping and removing container..."
        docker compose down 2>/dev/null || true
        success "Container removed."
    fi

    # Volume — ask separately, default NO
    if has_volume; then
        echo ""
        warn "Data volume contains your FABRIC credentials, slices, and artifacts."
        if $AUTO_YES; then
            info "Keeping data volume (use 'docker volume rm' to remove manually)."
        else
            if confirm "Remove data volume? THIS WILL DELETE ALL YOUR DATA"; then
                local vol_name
                vol_name=$(docker volume ls --format '{{.Name}}' 2>/dev/null | grep "${VOLUME_NAME}$" | head -1)
                if [[ -n "$vol_name" ]]; then
                    docker volume rm "$vol_name" 2>/dev/null || true
                    success "Data volume removed."
                fi
            else
                info "Data volume preserved."
            fi
        fi
    fi

    # Remove images
    if has_image; then
        info "Removing LoomAI images..."
        docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
            | grep "^fabrictestbed/loomai:" \
            | xargs -r docker rmi 2>/dev/null || true
        success "Images removed."
    fi

    # Remove compose file
    if has_compose_file; then
        echo ""
        if $AUTO_YES; then
            rm -f "$COMPOSE_FILE"
            success "Removed ${COMPOSE_FILE}."
        else
            if confirm "Remove ${COMPOSE_FILE}?"; then
                rm -f "$COMPOSE_FILE"
                success "Removed ${COMPOSE_FILE}."
            else
                info "Kept ${COMPOSE_FILE}."
            fi
        fi
    fi

    echo ""
    success "LoomAI has been uninstalled."
    echo ""
}

do_clean() {
    header "Clean Install — LoomAI"
    echo ""

    if has_image || has_any_container || has_volume; then
        warn "This will remove ALL existing LoomAI data, containers, and images"
        warn "and perform a fresh installation."
        echo ""

        if ! $AUTO_YES; then
            if ! confirm "THIS WILL DELETE ALL YOUR DATA. Proceed with clean install?"; then
                info "Clean install cancelled."
                exit 0
            fi
        fi

        echo ""

        # Stop and remove containers
        if has_compose_file && has_any_container; then
            info "Stopping and removing container..."
            docker compose down 2>/dev/null || true
            success "Container removed."
        fi

        # Remove volume
        if has_volume; then
            info "Removing data volume..."
            local vol_name
            vol_name=$(docker volume ls --format '{{.Name}}' 2>/dev/null | grep "${VOLUME_NAME}$" | head -1)
            if [[ -n "$vol_name" ]]; then
                docker volume rm "$vol_name" 2>/dev/null || true
                success "Data volume removed."
            fi
        fi

        # Remove images
        if has_image; then
            info "Removing LoomAI images..."
            docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
                | grep "^fabrictestbed/loomai:" \
                | xargs -r docker rmi 2>/dev/null || true
            success "Images removed."
        fi

        # Remove compose file
        if has_compose_file; then
            rm -f "$COMPOSE_FILE"
            success "Removed ${COMPOSE_FILE}."
        fi

        echo ""
        success "Previous installation removed."
    else
        info "No existing installation found."
    fi

    echo ""
    info "Starting fresh install..."
    echo ""

    # Now do a fresh install (force fresh path by ensuring detection returns false)
    do_install
}

# --- Main ---
check_prerequisites

case "$ACTION" in
    install)   do_install ;;
    clean)     do_clean ;;
    uninstall) do_uninstall ;;
    status)    do_status ;;
esac
