#!/bin/bash
set -e

mkdir -p outputs

ROOT_DIR="$(pwd)"
PYTHON="/home/thesis/venvs/thesis/bin/python"

SIM_PARAMETER_CONFIG_PATH=""

for arg in "$@"; do
    case $arg in
        SIM_PARAMETER_CONFIG_PATH=*)
            SIM_PARAMETER_CONFIG_PATH="${arg#SIM_PARAMETER_CONFIG_PATH=}"
            ;;
        *)
            echo "Unbekanntes Argument: $arg"
            exit 1
            ;;
    esac
done

cleanup() {
    echo ""
    echo "Stopping workflow services..."
    sudo pkill -f "carbon_coordinator.start_worker"   || true
    sudo pkill -f "carbon_coordinator.start_workflow" || true
    sudo pkill -f "temporal"                || true
    echo "Services stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

echo "Starting Temporal Server with UI: http://localhost:8233..."
temporal server start-dev > "$ROOT_DIR/outputs/temporal.out" 2>&1 &
sleep 1

echo "Starting worker..."
sudo SIM_PARAMETER_CONFIG_PATH="$SIM_PARAMETER_CONFIG_PATH" nohup $PYTHON -u -m carbon_coordinator.start_worker > "$ROOT_DIR/outputs/carbon_worker.out" 2>&1 &
sleep 1

echo "Starting workflow..."
sudo SIM_PARAMETER_CONFIG_PATH="$SIM_PARAMETER_CONFIG_PATH" nohup "$PYTHON" -u -m carbon_coordinator.start_workflow > "$ROOT_DIR/outputs/carbon_coordinator.out" 2>&1 &
echo ""
echo "Services started. Press Ctrl+C to stop them."
echo ""

wait