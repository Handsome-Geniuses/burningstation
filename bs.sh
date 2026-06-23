#!/usr/bin/env bash

cd "$(dirname "$0")"

env_file="$(pwd)/flask/.env"
echo "$env_file" 

set -euo pipefail

COMPOSE_FILE="docker-compose.yml"

usage() {
    cat <<'EOF'
THIS IS RUN OUTSIDE THE CONTAINER!
Usage: ./bs.sh <command>

Commands:
    dev <mode>
        modes: cockpit | engine | worker || all

Examples:
    ./bs.sh 
EOF
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

run_local_dev_mode() {
    local mode="$1"
    case "$mode" in
    cockpit)
        echo launching dev cockpit ... 
        cd "$(dirname "$0")"/next
        npm run dev
        ;;
    engine)
        echo launching dev engine ... 
        cd "$(dirname "$0")"/flask
        .venv/bin/python3 app.py
        ;;
    all)
        run_local_dev_mode cockpit &
        COCKPIT_PID=$!

        run_local_dev_mode engine &
        ENGINE_PID=$!


        cleanup() {
            echo "Stopping services..."
            kill $COCKPIT_PID $ENGINE_PID 2>/dev/null
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
