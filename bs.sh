#!/usr/bin/env bash

cd "$(dirname "$0")"

env_file="$(pwd)/flask/.env"
echo "$env_file"

set -euo pipefail

COMPOSE_FILE="docker-compose.yml"
COCKPIT_STACK_SERVICES=(burn-station-next)
ENGINE_STACK_SERVICES=(burn-station-flask)

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

usage() {
    cat <<'EOF'
THIS IS RUN OUTSIDE THE CONTAINER!
Usage: ./bs.sh <command> [target]

Commands:
    dev <mode>                  modes: cockpit | engine | all
    start <target>              target: cockpit | engine | all
    rebuild <target>            target: cockpit | engine | all
    restart <target>            target: cockpit | engine | all
    stop <target>               target: cockpit | engine | all
    logs <target>               target: cockpit | engine | all
    pull                        git pulls
    help                        show this help

Examples:
    ./bs.sh dev all
    ./bs.sh start cockpit
    ./bs.sh rebuild all
    ./bs.sh restart engine
    ./bs.sh stop engine
    ./bs.sh logs cockpit
EOF
}

pull_updates() {
    git pull
}

load_env_file() {
    if [[ -f "$env_file" ]]; then
        set -a
        . "$env_file"
        set +a
    else
        echo "Missing env file: $env_file" >&2
        exit 1
    fi
}

resolve_services() {
    local target="$1"

    case "$target" in
        cockpit)
            printf '%s\n' "${COCKPIT_STACK_SERVICES[@]}"
            ;;
        engine)
            printf '%s\n' "${ENGINE_STACK_SERVICES[@]}"
            ;;
        all)
            printf '%s\n' "${COCKPIT_STACK_SERVICES[@]}" "${ENGINE_STACK_SERVICES[@]}"
            ;;
        *)
            log "Unknown target: $target"
            usage
            exit 1
            ;;
    esac
}

start_services() {
    local target="${1:-all}"
    mapfile -t services < <(resolve_services "$target")

    log "Starting services: ${services[*]}"
    docker compose -f "$COMPOSE_FILE" up -d "${services[@]}"
}

rebuild_services() {
    local target="${1:-all}"
    mapfile -t services < <(resolve_services "$target")

    log "Rebuilding services: ${services[*]}"
    docker compose -f "$COMPOSE_FILE" up -d --build "${services[@]}"
}

restart_services() {
    local target="${1:-all}"
    mapfile -t services < <(resolve_services "$target")

    log "Restarting services: ${services[*]}"
    docker compose -f "$COMPOSE_FILE" restart "${services[@]}"
}

stop_services() {
    local target="${1:-all}"
    mapfile -t services < <(resolve_services "$target")

    log "Stopping services: ${services[*]}"
    docker compose -f "$COMPOSE_FILE" stop "${services[@]}"
}

follow_logs() {
    local target="${1:-all}"
    mapfile -t services < <(resolve_services "$target")

    for service in "${services[@]}"; do
        local container
        container="$(docker compose -f "$COMPOSE_FILE" ps -q "$service")"

        if [[ -z "$container" ]]; then
            log "No container found for service: $service"
            continue
        fi

        log "Following logs for service $service container $container"
        docker logs -f "$container"
    done
}

run_local_dev_mode() {
    local mode="$1"

    case "$mode" in
        cockpit)
            log "Launching dev cockpit ..."
            cd "$(dirname "$0")"/next
            npm run dev
            ;;
        engine)
            log "Launching dev engine ..."
            cd "$(dirname "$0")"/flask
            .venv/bin/python3 app.py
            ;;
        all)
            run_local_dev_mode cockpit &
            COCKPIT_PID=$!

            run_local_dev_mode engine &
            ENGINE_PID=$!

            cleanup() {
                log "Stopping services..."
                kill "$COCKPIT_PID" "$ENGINE_PID" 2>/dev/null || true
            }

            trap cleanup EXIT INT TERM
            wait
            ;;
        *)
            log "Unknown mode: $mode"
            usage
            exit 1
            ;;
    esac
}

main() {
    load_env_file

    local command="${1:-help}"
    shift || true

    case "$command" in
        dev)
            if (($# < 1)); then
                usage
                exit 1
            fi
            run_local_dev_mode "$1"
            ;;
        pull)
            pull_updates
            ;;
        start)
            start_services "${1:-all}"
            ;;
        rebuild)
            rebuild_services "${1:-all}"
            ;;
        restart)
            restart_services "${1:-all}"
            ;;
        stop)
            stop_services "${1:-all}"
            ;;
        logs | log)
            follow_logs "${1:-all}"
            ;;
        help | -h | --help)
            usage
            ;;
        *)
            log "Unknown command: $command"
            usage
            exit 1
            ;;
    esac
}

main "$@"