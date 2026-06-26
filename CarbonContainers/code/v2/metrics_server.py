import config
from prometheus_client import Gauge, start_http_server

class Metrics:
    def __init__(self):

        self.carbon_intensity = Gauge(
            "lxcc_carbon_intensity",
            "Current grid carbon intensity in gCO2/kWh",
        )

        self.carbon_treshold = Gauge(
            "lxcc_carbon_threshold",
            "Carbon emission threshold for the container in gCO2/s",
            ["container_name"],
        )
        self.cpu = Gauge(
            "lxcc_current_cpu",
            "Current CPU usage of the container in percent (per CPU core normalized)",
            ["container_name"],
        )
        self.current_cpu_core = Gauge(
            "lxcc_current_cpu_core",
            "Current CPU cores available of the container",
            ["container_name"],
        )
        self.max_cpu_core = Gauge(
            "lxcc_max_cpu_core",
            "Maximum CPU cores available of the container",
            ["container_name"],
        )
        self.current_joules = Gauge(
            "lxcc_current_joules",
            "Current power draw of the container in Joules",
            ["container_name"],
        )
        self.current_carbon = Gauge(
            "lxcc_current_carbon",
            "Current carbon emission rate of the container in gCO2/s",
            ["container_name"],
        )
        self.suspended = Gauge(
            "lxcc_suspended",
            "Whether the container is currently suspended (1) or not (0)",
            ["container_name"],
        )
        self.total_joules = Gauge(
            "lxcc_total_joules",
            "Total energy consumed by the container in Joules",
            ["container_name"],
        )
        self.total_carbon = Gauge(
            "lxcc_total_carbon",
            "Total carbon emitted by the container in gCO2",
            ["container_name"],
        )


    def set_carbon_intensity(self, gco2_per_kwh: float):
        self.carbon_intensity.set(gco2_per_kwh)

    def update_container(
        self,
        container_name: str,
        carbon_threshold: float,
        cpu: float,
        current_cpu_core: int,
        max_cpu_core: int,
        current_joules: float,
        current_carbon: float,
        suspended: bool,
        total_joules: float,
        total_carbon: float,
    ):
        self.cpu.labels(container_name=container_name).set(cpu)
        self.carbon_treshold.labels(container_name=container_name).set(carbon_threshold)
        self.current_cpu_core.labels(container_name=container_name).set(current_cpu_core)
        self.max_cpu_core.labels(container_name=container_name).set(max_cpu_core)
        self.current_joules.labels(container_name=container_name).set(current_joules)
        self.current_carbon.labels(container_name=container_name).set(current_carbon)
        self.suspended.labels(container_name=container_name).set(1 if suspended else 0)
        self.total_joules.labels(container_name=container_name).set(total_joules)
        self.total_carbon.labels(container_name=container_name).set(total_carbon)
    

metrics = Metrics()
start_http_server(config.PROMETHEUS_PORT)
