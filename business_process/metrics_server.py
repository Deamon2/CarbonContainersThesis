from business_process import config
from prometheus_client import Counter, Histogram, start_http_server

class Metrics:
    def __init__(self):

        self.service_requests_total = Counter(
            "service_requests_total",
            "Service requests",
            ["container_name"]
        )
        self.service_successful_total = Counter(
            "service_successful_total",
            "Service successful requests",
            ["container_name", "mode"]
        )
        self.service_failed_total = Counter(
            "service_failed_total",
            "Service failed requests",
            ["container_name"]
        )
        self.service_computation_seconds = Histogram(
            "service_computation_seconds",
            "Service computation time for a container in seconds",       
            ["container_name", "mode"],
            buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 5)
        )

        self.workflow_total = Counter(
            "workflow_total",
            "Workflow requests",
        )
        self.workflow_successful_total = Counter(
            "workflow_successful_total",
            "Workflow successful requests",
        )
        self.workflow_failed_total = Counter(
            "workflow_failed_total",
            "Workflow failed requests",
        )
        self.workflow_computation_seconds = Histogram(
            "workflow_computation_seconds",
            "Workflow total computation time in seconds",
            buckets=(0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10)
        )

        self.workflow_total.labels()
        self.workflow_successful_total.labels()
        self.workflow_failed_total.labels()
        self.workflow_computation_seconds.observe(0)
        
        modes = [
            "high",
            "medium",
            "low"
        ]

        for container in config.CONTAINER_NAMES:
            self.service_requests_total.labels(container_name=container)
            self.service_failed_total.labels(container_name=container)

            for mode in modes:
                self.service_successful_total.labels(container_name=container, mode=mode)
                self.service_computation_seconds.labels(container_name=container, mode=mode)
            

    def update_workflow_requests(self):
        self.workflow_total.inc()

    def update_workflow_successful_requests(self, total_computation_time_ms: float):
        self.workflow_successful_total.inc()
        self.workflow_computation_seconds.observe(total_computation_time_ms / 1000)

    def update_workflow_failed_requests(self):
        self.workflow_failed_total.inc()

    def update_total_service_requests(self, container_name: str):
        self.service_requests_total.labels(container_name=container_name).inc()

    def update_successful_service_requests(self, container_name: str, mode: str):
        self.service_successful_total.labels(container_name=container_name, mode=mode).inc()

    def update_failed_service_requests(self, container_name: str):
        self.service_failed_total.labels(container_name=container_name).inc()

    def update_computation_time(self, container_name: str, mode: str, duration: float):
        self.service_computation_seconds.labels(container_name=container_name, mode=mode).observe(duration / 1000)


metrics = Metrics()

base = config.PROMETHEUS_PORT
for port in range(base, base + 100):
    try:
        start_http_server(port)
        print(f"Prometheus metrics server started on port {port}")
        break
    except OSError:
        if port == base + 99:
            raise RuntimeError("No available port found for Prometheus metrics server")
        continue
