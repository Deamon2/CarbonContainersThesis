import subprocess
import threading
import json
import logging
from pathlib import Path

logger = logging.getLogger("scaphandre_reader")
EXCEPTION_LOG_PATH = Path(__file__).resolve().parent / "energy_accumulator_excep.log"

if not logger.handlers:
    logger.setLevel(logging.ERROR)
    logger.addHandler(logging.NullHandler())
    logger.propagate = False


def log_exception(message: str):
    if not any(isinstance(handler, logging.FileHandler) for handler in logger.handlers):
        file_handler = logging.FileHandler(EXCEPTION_LOG_PATH)
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        logger.addHandler(file_handler)
    logger.exception(message)


class EnergyAccumulator:
    """
    Liest kontinuierlich daten vom scaphandre json exporter und integriert sie über die Zeit zu Joule
    """
    def __init__(self, max_top_consumers=2000):
        self.lock = threading.Lock()
        self.energy_by_pid = {}            # pid -> akkumulierte Joule seit letztem read_and_reset()
        self.last_timestamp_by_pid = {}    # pid -> letzter von scaphandre gemeldeter Prozess-Timestamp
        self.missed_ticks_by_pid = {}      # pid -> Anzahl der Ticks, in welchen die PID nciht vorkamm
        self.scaphandre_process = None
        self.stop_event = threading.Event()
        self.max_top_consumers = max_top_consumers

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        try:
            self.read_scaphandre_stream()
        except Exception as error:
            log_exception("Fehler beim scaphandre auslesen: " + str(error))

    def stop(self):
        self.stop_event.set()
        if self.scaphandre_process:
            self.scaphandre_process.terminate()
            try:
                self.scaphandre_process.wait(timeout=3)  # wartet bis Prozess beendet
            except subprocess.TimeoutExpired:
                subprocess.run(["sudo", "pkill", "-TERM", "-f", "scaphandre json"])        

    def read_scaphandre_stream(self):
        cmd = ["sudo", "scaphandre", "json", "-s", "1", "--max-top-consumers", str(self.max_top_consumers)]
        self.scaphandre_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        decoder = json.JSONDecoder()
        buf = ""
        while not self.stop_event.is_set():
            chunk = self.scaphandre_process.stdout.read(4096)
            if not chunk:
                break  # Pipe zu, entweder stop() oder absturz
            buf += chunk.decode("utf-8", errors="replace")
            while True:
                metrics, buf = self.read_next_metrics_object(buf, decoder)
                if metrics is None:
                    break
                self.process_metrics(metrics)

        if not self.stop_event.is_set():
            stderr = self.scaphandre_process.stderr.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"scaphandre unerwartet beendet, stderr: {stderr}")        

    def drop_stream_delimiters(self, buf: str):
        pos = 0
        while pos < len(buf) and buf[pos] in " \n\r\t,[]":
            pos += 1
        return buf[pos:]

    def read_next_metrics_object(self, buf: str, decoder: json.JSONDecoder):
        buf = self.drop_stream_delimiters(buf)
        if not buf:
            return None, buf

        if not buf.startswith("{"):
            next_object = buf.find("{")
            if next_object == -1:
                return None, ""
            buf = buf[next_object:]

        try:
            metrics, idx = decoder.raw_decode(buf)
        except json.JSONDecodeError:
            return None, buf  # Objekt ist noch nicht komplett im Buffer

        if not isinstance(metrics, dict):
            logger.warning("ignoriere unerwarteten scaphandre JSON-Typ: %s", type(metrics).__name__)
            return None, buf[idx:]

        return metrics, buf[idx:]

    def process_metrics(self, metrics: dict):
        processes = metrics.get("consumers", [])
        seen_pids = set()
        with self.lock:
            for proc in processes:
                raw_pid = proc.get("pid")
                timestamp = proc.get("timestamp")
                power_uw = proc.get("consumption", 0.0)
                if raw_pid is None or timestamp is None:
                    continue
                pid = int(raw_pid)
                seen_pids.add(pid)
                last_timestamp = self.last_timestamp_by_pid.get(pid)
                if last_timestamp is not None:
                    dt = timestamp - last_timestamp
                    if dt > 0:
                        power_w = power_uw / 1000000
                        self.energy_by_pid[pid] = self.energy_by_pid.get(pid, 0.0) + power_w * dt
                self.last_timestamp_by_pid[pid] = timestamp

            stale_pids = set(self.energy_by_pid) - seen_pids
            for pid in stale_pids:
                self.energy_by_pid.pop(pid, None)
                self.last_timestamp_by_pid.pop(pid, None)
                self.missed_ticks_by_pid.pop(pid, None)

            all_tracked = set(self.last_timestamp_by_pid) | set(self.energy_by_pid)
            for pid in all_tracked - seen_pids:
                missing_count = self.missed_ticks_by_pid.get(pid, 0) + 1
                self.missed_ticks_by_pid[pid] = missing_count
                if missing_count >= 5:
                    self.energy_by_pid.pop(pid, None)
                    self.last_timestamp_by_pid.pop(pid, None)
                    self.missed_ticks_by_pid.pop(pid, None)

    def read_and_reset(self, pids):
        with self.lock:
            return {pid: self.energy_by_pid.pop(pid, 0.0) for pid in pids}
