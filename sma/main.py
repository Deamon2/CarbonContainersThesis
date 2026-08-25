from sma import SustainabilityMeasurementAgent, Config
import shutil
import yaml
import json
import select
import subprocess
import os
import signal
import sys
import time
import urllib.parse
import urllib.request
import uuid
import types

from parameter_sweep import build_sim_config

VENV = "/home/thesis/venvs/thesis/bin/"

CURRENT_DIR = os.path.abspath(os.path.dirname(__file__))
PARENT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
LXCC_CODE_DIR = os.path.join(PARENT_DIR, "CarbonContainers", "code")
FLAGD_FLAGS_URI = "file:///mnt/d/thesis/CarbonContainersThesis/business_process/flags.json"
FLAGD_PORT = "8013"

NUM_BUSINESS_PROCESS_WORKERS = 6

LXC_CONTAINERS = {
    "cont1": "0.1", 
    "cont2": "0.1", 
    "cont3": "0.1"
}


# container -> flag key
COMPUTE_SERVICES = {
    "cont1": "delivery-mode",
    "cont2": "checkout-mode",
    "cont3": "payment-mode",
}

def load_parameter_config(path: str):
    with open(path) as f:
        return yaml.safe_load(f) or {}
BASE_PARAMETER_CONFIG = load_parameter_config(os.path.join(CURRENT_DIR, "parameter_config.yaml"))

RUN_SIM_CONFIG = build_sim_config(BASE_PARAMETER_CONFIG)
LOCUST_SHAPE = RUN_SIM_CONFIG["load_shape"]["scenario"]

RUN_ID = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
RUN_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "runs", RUN_ID))
LOGS_DIR = os.path.join(RUN_DIR, "logs")
PROM_DATA_DIR = os.path.join(RUN_DIR, "prometheus_data")

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(PROM_DATA_DIR, exist_ok=True)

RUN_SIM_CONFIG_PATH = os.path.abspath(os.path.join(RUN_DIR, "parameter_config.yaml"))
with open(RUN_SIM_CONFIG_PATH, "w") as f:
    yaml.safe_dump(RUN_SIM_CONFIG, f, sort_keys=False)

report_location = {"path": None}

def on_report(report=None):
    if report is not None:
        report_location["path"] = os.path.abspath(report.location)

location_observer = types.SimpleNamespace(onReport=on_report)

procs = []  # list of (name, Popen, log_file)


class WaitForEnterTrigger:
    def trigger(self, cancel, **kwargs):
        print("Hit Enter to to Stop Measuring...", flush=True)

        while True:
            if cancel.is_set():
                return {}

            try:
                readable, _ , _  = select.select([sys.stdin], [], [], 0.5)
            except Exception:
                time.sleep(0.5)
                continue

            if readable:
                sys.stdin.readline()
                return {}


def get_prometheus_address(config):
    services = getattr(config, "services", None)
    prometheus = None

    if services is not None:
        prometheus = getattr(services, "prometheus", None)
        if prometheus is None and isinstance(services, dict):
            prometheus = services.get("prometheus")

    return getattr(prometheus, "address", "http://localhost:9090")


def get_measurement_queries(config):
    queries = []
    measurement_map = config.measurement_queries()

    for name, measurement in measurement_map.items():
        query = getattr(measurement, "query", None)
        if query is None and isinstance(measurement, dict):
            query = measurement.get("query")

        if query:
            queries.append((name, str(query).strip()))

    return queries


def prometheus_has_data(prometheus_address, query):
    url = (
        f"{prometheus_address.rstrip('/')}/api/v1/query?"
        f"query={urllib.parse.quote(query, safe='')}"
    )

    with urllib.request.urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    result = payload.get("data", {}).get("result", [])
    return bool(result)


def wait_for_measurements(config, timeout_seconds=30, poll_seconds=2):
    prometheus_address = get_prometheus_address(config)
    queries = get_measurement_queries(config)
    pending = {name: query for name, query in queries}
    deadline = time.monotonic() + timeout_seconds

    if not pending:
        return

    print("Warte auf verfügbare Messwerte...")
    while pending and time.monotonic() < deadline:
        ready = []

        for name, query in pending.items():
            try:
                if prometheus_has_data(prometheus_address, query):
                    ready.append(name)
            except Exception as e:
                print(f"warte auf {name}: {e}")

        for name in ready:
            pending.pop(name, None)

        if pending:
            time.sleep(poll_seconds)

    if pending:
        print("Warnung: nicht alle Messwerte wurden rechtzeitig verfügbar: " + ", ".join(pending.keys()))


def write_exception_log(name, message):
    path = os.path.join(LOGS_DIR, f"{name}.log")
    with open(path, "a") as log_f:
        log_f.write(f"{message}\n")


def start_proc(name, cmd, cwd=PARENT_DIR):
    log_f = None
    try:
        log_path = os.path.join(LOGS_DIR, f"{name}.log")
        log_f = open(log_path, "a", buffering=1)
        prozess = subprocess.Popen(
            cmd, cwd=cwd,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )
        procs.append((name, prozess, log_f))
        print(f"gestartet: {name} (PID {prozess.pid})")
    except Exception as error:
        write_exception_log(name, f"Fehler beim Starten: {error}")
        print(f"Fehler beim Starten von {name}: {error}")
        try:
            if log_f:
                log_f.close()
        except Exception:
            pass


def run_monitoring():
    start_proc("prometheus", ["prometheus", f"--config.file={os.path.join(CURRENT_DIR, 'prometheus.yaml')}", f"--storage.tsdb.path={PROM_DATA_DIR}"])
    time.sleep(2)
    start_proc("grafana", ["sudo", "grafana", "server"])


def run_lxcc_services():
    start_proc("cc-records", ["sudo", f"{VENV}python", "-u", "cc-records.py", "127.0.0.1"], cwd=LXCC_CODE_DIR)
    time.sleep(1)
    start_proc("cc-controller", ["sudo", f"SIM_PARAMETER_CONFIG_PATH={RUN_SIM_CONFIG_PATH}", f"{VENV}python", "-u", "cc-controller.py", "127.0.0.1"], cwd=LXCC_CODE_DIR)
    time.sleep(1)
    start_proc("cc-monitor", ["sudo", f"SIM_PARAMETER_CONFIG_PATH={RUN_SIM_CONFIG_PATH}", f"{VENV}python", "-u", "cc-monitor.py", "127.0.0.1"], cwd=LXCC_CODE_DIR)
    time.sleep(1)
    start_proc("cc-front", ["sudo", f"{VENV}python", "-u", "cc-front.py", "127.0.0.1"], cwd=LXCC_CODE_DIR)
    time.sleep(1)


def run_carbon_workflow():
    start_proc("temporal-server", ["temporal", "server", "start-dev"])
    time.sleep(1)
    start_proc("carbon-worker", ["sudo", f"SIM_PARAMETER_CONFIG_PATH={RUN_SIM_CONFIG_PATH}", f"{VENV}python", "-u", "-m", "carbon_process.start_worker"])
    time.sleep(1)
    start_proc("carbon-workflow", [ "sudo", f"SIM_PARAMETER_CONFIG_PATH={RUN_SIM_CONFIG_PATH}", f"{VENV}python", "-u", "-m", "carbon_process.start_workflow" ])
    time.sleep(1)

def run_lxcc_client_and_containers():
    for container, thresh in LXC_CONTAINERS.items():
        start_proc("cc-client", ["sudo", f"{VENV}python", "CarbonContainers/code/cc-client.py", "--name", container, "--thresh", thresh])
        start_proc(f"lxc-start-{container}", ["sudo", "lxc-start", "-n", container])


def run_business_process_workers(count=NUM_BUSINESS_PROCESS_WORKERS):
    for i in range(count):
        start_proc(f"process-worker-{i}", ["sudo", f"{VENV}python", "-u", "-m", "business_process.start_worker"])


def run_flagd():
    start_proc("flagd", ["sudo", "flagd", "start", "--uri", FLAGD_FLAGS_URI, "--port", FLAGD_PORT])
    time.sleep(1)


def run_compute_services():
    for container, flag_key in COMPUTE_SERVICES.items():
        start_proc(f"compute-{container}", ["sudo", "lxc-attach", "-n", container, "--", "bash", "-lc",
            (
                "cd ~ && "
                f"FLAG_KEY={flag_key} DEFAULT_MODE=high "
                "venv/bin/python -m uvicorn compute:app "
                "--host 0.0.0.0 --port 8000 --workers 3"
            )
        ])

def run_locust(shape):
    start_proc("locust", [f"{VENV}locust", "-f", "business_process/locustfile.py", "--headless", "--shape", shape])


def stop_all():
    print("Stoppe Services...")

    for entry in reversed(procs):
        try:
            name, prozess, log_f = entry
        except ValueError:
            continue
        try:
            if prozess.poll() is not None:
                continue

            os.killpg(prozess.pid, signal.SIGINT)
            prozess.wait(timeout=10)
            print(f"gestoppt: {name}")
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            try:
                os.killpg(prozess.pid, signal.SIGTERM)
                prozess.wait(timeout=10)
                print(f"SIGTERM gesendet: {name}")
            except subprocess.TimeoutExpired:
                os.killpg(prozess.pid, signal.SIGKILL)
                prozess.wait(timeout=5)
                print(f"SIGKILL gesendet: {name}")
            except ProcessLookupError:
                pass
            except Exception as error:
                write_exception_log(name, f"Fehler beim Beenden: {error}")
                print(f"Fehler beim Beenden von {name}: {error}")
        except Exception as error:
            write_exception_log(name, f"Fehler beim Stoppen: {error}")
            print(f"Fehler beim Stoppen von {name}: {error}")
        finally:
            try:
                if log_f:
                    log_f.close()
            except Exception:
                pass

    try:
        for container in LXC_CONTAINERS:
            subprocess.run(["sudo", "lxc-stop", "-n", container], timeout=30, check=False)
    except Exception as error:
        write_exception_log("lxc-stop", f"lxc-stop fehlgeschlagen: {error}")
        print(f"Fehler beim Stoppen der Container: {error}")


def finalize_run(report_location):
    if not report_location:
        print(f"Warnung: report_location unbekannt, Logs bleiben unter {LOGS_DIR}.")
        return

    os.makedirs(report_location, exist_ok=True)

    logs_target = os.path.join(report_location, "logs")
    if os.path.exists(logs_target):
        shutil.rmtree(logs_target)
    shutil.move(LOGS_DIR, logs_target)

    prometheus_target = os.path.join(report_location, "prometheus_data")
    if os.path.exists(prometheus_target):
        shutil.rmtree(prometheus_target)
    if os.path.exists(PROM_DATA_DIR):
        shutil.move(PROM_DATA_DIR, prometheus_target)

    if os.path.exists(RUN_SIM_CONFIG_PATH):
        shutil.copy2(RUN_SIM_CONFIG_PATH, os.path.join(report_location, "parameter_config.yaml"))

    shutil.rmtree(RUN_DIR)  # löscht gesamtes run dir, lieber nur den run löschen?

    print(f"Logs und Prometheus-Daten liegen unter: {report_location}")


config = None
sma = None
try:
    run_monitoring()

    config = Config.from_file(os.path.join(CURRENT_DIR, "config.yaml"))
    sma = SustainabilityMeasurementAgent(config, observers=[location_observer])
    sma.connect()

    run_carbon_workflow()

    run_lxcc_services()

    run_lxcc_client_and_containers()
    time.sleep(5)

    run_flagd()

    run_compute_services()

    run_business_process_workers()
    time.sleep(3)

    # Metriken müssen vor Messbeginn verfügbar sein, sonst werden sie nicht erfasst
    wait_for_measurements(config)
    time.sleep(5)

    run_locust(LOCUST_SHAPE)

    print("Messung wird gestartet...")
    with sma.start_session():
        sma.run(trigger=WaitForEnterTrigger())
except KeyboardInterrupt:
    print("Abgebrochen. Räume Services auf...")
finally:
    stop_all()
    if sma is not None:
        sma.teardown()
    finalize_run(report_location["path"])
