from sma import SustainabilityMeasurementAgent, Config
import json
import select
import subprocess
import os
import signal
import sys
import time
import urllib.parse
import urllib.request

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
LOGS_DIR = os.path.join(SCRIPT_DIR, "logs")
VENV_PYTHON = "/home/thesis/venvs/thesis/bin/python"

os.makedirs(LOGS_DIR, exist_ok=True)

procs = []  # list of (name, Popen, log_file)


def reset_run_logs():
    for root, _, files in os.walk(LOGS_DIR):
        for filename in files:
            if not filename.endswith(".log"):
                continue

            path = os.path.join(root, filename)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                pass


class WaitForEnterTrigger:
    def trigger(self, cancel, **kwargs):
        print("Hit Enter to to Stop Measuring...", flush=True)

        while True:
            if cancel.is_set():
                return {}

            try:
                readable, _, _ = select.select([sys.stdin], [], [], 0.5)
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


def wait_for_measurements(config, timeout_seconds=60, poll_seconds=2):
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


def start_proc(name, cmd, cwd=ROOT):
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
        subprocess.run(["sudo", "lxc-stop", "-n", "cont1"], timeout=30, check=False)
        subprocess.run(["sudo", "lxc-stop", "-n", "cont2"], timeout=30, check=False)
        subprocess.run(["sudo", "lxc-stop", "-n", "cont3"], timeout=30, check=False)
    except Exception as error:
        write_exception_log("lxc-stop", f"lxc-stop fehlgeschlagen: {error}")
        print(f"Fehler beim Stoppen der Container: {error}")



config = None
sma = None
try:
    reset_run_logs()

    start_proc("prometheus", ["prometheus", f"--config.file={os.path.join(SCRIPT_DIR, 'prometheus.yaml')}"])

    time.sleep(2)

    start_proc("grafana", ["sudo", "grafana", "server"])

    config = Config.from_file(os.path.join(SCRIPT_DIR, "config.yaml"))
    sma = SustainabilityMeasurementAgent(config)
    sma.connect()

    start_proc("carbon-workflow", ["sudo", "bash", "./start_carbon_workflow.sh"])

    time.sleep(3)

    start_proc("lxcc", ["sudo", "bash", "./start_lxcc_services.sh"])

    time.sleep(5)

    start_proc("client", ["sudo", VENV_PYTHON, "CarbonContainers/code/v2/cc-client.py"])
    start_proc("lxc-start", ["sudo", "lxc-start", "-n", "cont1"])
    start_proc("lxc-start", ["sudo", "lxc-start", "-n", "cont2"])
    start_proc("lxc-start", ["sudo", "lxc-start", "-n", "cont3"])

    NUM_WORKERS = 6
    for i in range(NUM_WORKERS):
        start_proc(f"process-worker-{i}", ["sudo", VENV_PYTHON, "-u", "-m", "business_process.start_worker"])

    start_proc("flagd", ["sudo", "flagd", "start", "--uri", "file:///mnt/d/thesis/CarbonContainersThesis/business_process/flags.json", "--port", "8013"])
    time.sleep(3)

    start_proc("compute-1", ["sudo", "lxc-attach", "-n", "cont1", "--", "bash", "-lc",
        (
            "cd ~ && "
            "FLAG_KEY=delivery-mode DEFAULT_MODE=high "
            "venv/bin/python -m uvicorn compute:app "
            "--host 0.0.0.0 --port 8000 --workers 3"
        )
    ])
    start_proc("compute-2", ["sudo", "lxc-attach", "-n", "cont2", "--", "bash", "-lc",
        (
            "cd ~ && "
            "FLAG_KEY=checkout-mode DEFAULT_MODE=high "
            "venv/bin/python -m uvicorn compute:app "
            "--host 0.0.0.0 --port 8000 --workers 3"
        )
    ])
    start_proc("compute-3", ["sudo", "lxc-attach", "-n", "cont3", "--", "bash", "-lc",
        (
            "cd ~ && "
            "FLAG_KEY=payment-mode DEFAULT_MODE=high "
            "venv/bin/python -m uvicorn compute:app "
            "--host 0.0.0.0 --port 8000 --workers 3"
        )
    ])
    # Metriken müssen vor Messbeginn verfügbar sein, sonst werden sie nicht erfasst
    wait_for_measurements(config)

    print("Messung wird gestartet...")
    with sma.start_session():
        sma.run(trigger=WaitForEnterTrigger())
except KeyboardInterrupt:
    print("Abgebrochen. Räume Services auf...")
finally:
    stop_all()
    if sma is not None:
        sma.teardown()

try:
    report_location = (config.report.get("location"))
    if report_location:
        print(f"Report: {report_location}")
except Exception as error:
    pass

