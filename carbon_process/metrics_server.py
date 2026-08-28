from carbon_process import config
from carbon_process.helpers import load_flag_config
from prometheus_client import Gauge, start_http_server

class Metrics:
    def __init__(self):

        self.degradation = Gauge(
            "service_degradation_status",
            "Returns between 0 and 1, where 0 means no degradation and 1 means full degradation",
            ["container_name"],
        )
        self.process_upgrade_threshold = Gauge(
            "process_upgrade_threshold",
            "Process Flag Upgrade Threshold",
        )
        self.process_degrade_threshold = Gauge(
            "process_degrade_threshold",
            "Process Flag degrade Threshold",
        )

        self.process_upgrade_threshold.set(0.0)
        self.process_degrade_threshold.set(0.0)

        containers = load_flag_config().get("containers", {})
        for container_name in containers:
            self.degradation.labels(container_name=container_name)

    def update_degradation_status(self, container_name: str, degradation_status: float):
        self.degradation.labels(container_name=container_name).set(degradation_status)

    def update_process_upgrade_threshold(self, process_upgrade_threshold: float):
        self.process_upgrade_threshold.set(process_upgrade_threshold)

    def update_process_degrade_threshold(self, process_degrade_threshold: float):
        self.process_degrade_threshold.set(process_degrade_threshold)

metrics = Metrics()
start_http_server(config.PROMETHEUS_PORT)
