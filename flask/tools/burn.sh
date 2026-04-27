#!/usr/bin/env bash

set -u


# these directories are relative to the container
TOOLS_DIR="/app/tools"
APP_DIR="/app"
CONTAINER_NAME="burn_station_flask"

show_help() {
    cat <<'EOF'
THIS IS RUN OUTSIDE THE CONTAINER!
Usage: ./burn.sh <command>

Commands:
  start     Runs app if not running
  kill      Kill app if running
  restart   Restarts app
  check     Check if app running
  exec      Open a bash shell inside the container
  logs      Follow container logs
  help      Show this help message

Examples:
  ./burn.sh start
  ./burn.sh kill
  ./burn.sh restart
  ./burn.sh check
  ./burn.sh exec
  ./burn.sh logs
EOF
}

docker_shell() {
    docker exec -i "$CONTAINER_NAME" bash -lc "$1"
}

kill_app() {
    docker_shell "cd '$TOOLS_DIR' && python -u ./kill.py" &
}

is_running() {
    docker_shell "cd '$TOOLS_DIR' && python -u ./isrunning.py >/dev/null 2>&1"
}

check_app() {
    if is_running; then
        echo "running"
    else
        echo "not running"
    fi
}

start_app() {
    if is_running; then
        echo "already running"
    else
        echo "starting"
        docker_shell "cd '$APP_DIR' && nohup env PYTHONPATH=/app python -u app.py --host=0.0.0.0 --port=8011 >/dev/null 2>&1 &"
    fi
}

restart_app() {
    echo "restarting..."
    kill_app
    sleep 1
    start_app
}

exec_container() {
    docker exec -it "$CONTAINER_NAME" bash
}

logs_container() {
    docker logs -f "$CONTAINER_NAME"
}

if [ $# -eq 0 ]; then
    show_help
    exit 0
fi

case "$1" in
    start)
        start_app
        ;;
    kill)
        kill_app
        ;;
    restart)
        restart_app
        ;;
    check)
        check_app
        ;;
    exec)
        exec_container
        ;;
    logs)
        logs_container
        ;;
    help|-h|--help)
        show_help
        ;;
    *)
        echo "Unknown command: $1"
        echo
        show_help
        exit 1
        ;;
esac


