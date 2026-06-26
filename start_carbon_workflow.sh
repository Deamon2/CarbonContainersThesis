#!/bin/bash
set -e

mkdir -p outputs

ROOT_DIR="$(pwd)"
PYTHON="/home/thesis/venvs/thesis/bin/python"

cleanup() {
    echo ""
    echo "Stopping workflow services..."
    sudo pkill -f "carbon_process.start_worker"   || true
    sudo pkill -f "carbon_process.start_workflow" || true
    sudo pkill -f "temporal"                || true
    echo "Services stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

echo "Starting Temporal Server with UI: http://localhost:8233..."
temporal server start-dev > "$ROOT_DIR/outputs/temporal.out" 2>&1 &
sleep 1

echo "Starting worker..."
nohup sudo $PYTHON -u -m carbon_process.start_worker > "$ROOT_DIR/outputs/carbon_worker.out" 2>&1 &
sleep 1

echo "Starting workflow..."
nohup sudo $PYTHON -u -m carbon_process.start_workflow > "$ROOT_DIR/outputs/carbon_workflow.out" 2>&1 &

echo ""
echo "Services started. Press Ctrl+C to stop them."
echo ""

wait