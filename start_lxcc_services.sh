#!/bin/bash
set -e

mkdir -p outputs

ROOT_DIR="$(pwd)"
PYTHON="/home/thesis/venvs/thesis/bin/python"

cleanup() {
    echo ""
    echo "Stopping services..."
    sudo pkill -f "scaphandre"       || true
    sudo pkill -f "cc-records.py"    || true
    sudo pkill -f "cc-controller.py" || true
    sudo pkill -f "cc-monitor.py"    || true
    sudo pkill -f "cc-front.py"      || true
    echo "All services stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

echo "Starting LXCC Services..."
echo ""

pushd CarbonContainers/code/v2 >/dev/null

echo "Starting scaphandre..."
nohup sudo scaphandre prometheus --port 8080 > "$ROOT_DIR/outputs/scaphandre.out" 2>&1 &
sleep 1

echo "Starting Records Service..."
nohup sudo $PYTHON -u cc-records.py 127.0.0.1 > "$ROOT_DIR/outputs/records.out" 2>&1 &
sleep 1

echo "Starting Controller Service..."
nohup sudo $PYTHON -u cc-controller.py 127.0.0.1 > "$ROOT_DIR/outputs/controller.out" 2>&1 &
sleep 1

echo "Starting Monitor Service..."
nohup sudo $PYTHON -u cc-monitor.py 127.0.0.1 > "$ROOT_DIR/outputs/monitor.out" 2>&1 &
sleep 1

echo "Starting Frontend Service..."
nohup sudo $PYTHON -u cc-front.py 127.0.0.1 > "$ROOT_DIR/outputs/front.out" 2>&1 &

echo ""
echo "Services started. Press Ctrl+C to stop them"
echo ""

popd >/dev/null

wait