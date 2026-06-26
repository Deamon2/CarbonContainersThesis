This project connects carbon reduction measures across multiple layers.  
LXCC is used at the system level. It utilizes vertical scaling and suspend/resume to keep a container’s carbon emissions below a specified threshold. LXCC sends carbon and system metrics to a temporal carbon workflow and to Prometheus for further use by SMA and Grafana.  
At the process layer, the Temporal Carbon Workflow periodically checks the container metrics; in the 'analyze' activity, it determines whether actions are necessary; in 'plan’ it decides where to take action; and in 'execute' the change is implemented by modifying flagd's flags.json.  
The Temporal business workflow is used to simulate a business process which calls three microservices sequentially. Each microservices querys flagd for their current flag state. Depending on the flag state, varying amounts of computation are performed at the application layer.  
Metrics from the Carbon and Business workflows are also sent to Prometheus to be available for Sma and Grafana.  
Locust is used for load testing by starting business workflows.  
SMA is used for starting the system and generating report CSVs. 

# Setup & Usage

## Requirements
- Linux OS, because CRIU is used.
- Cannot be run inside a VM because Scaphandre requires direct access to the hardware. 
- Developed in Python 3.14.4. Earlier versions might cause problems, but most likely won't be an issue.
- Not all of the commands listed actually require sudo, but many of them do.

## Installation

### LXCC
```bash
sudo apt-get install lxc
sudo apt-get install criu
sudo apt-get install linux-tools-common
sudo apt-get install scaphandre
pip install -r CarbonContainers/scripte/requirementst.txt
```

### flagd
```bash
wget https://github.com/open-feature/flagd/releases/download/flagd%2Fv0.15.5/flagd_0.15.5_Linux_x86_64.tar.gz
tar -xvzf flagd_0.15.5_Linux_x86_64.tar.gz
sudo mv ./flagd_linux_x86_64 /usr/local/bin/flagd
sudo chmod +x /usr/local/bin/flagd
```

### Temporal
```bash
wget https://github.com/temporalio/cli/releases/download/v1.7.0/temporal_cli_1.7.0_linux_amd64.tar.gz
tar -xvzf temporal_cli_1.7.0_linux_amd64.tar.gz
sudo mv temporal /usr/local/bin/
sudo chmod +x /usr/local/bin/temporal
pip install temporalio httpx pyyaml
```

### Prometheus
```bash
wget https://github.com/prometheus/prometheus/releases/download/v3.4.0/prometheus-3.4.0.linux-amd64.tar.gz
tar -xvzf prometheus-3.4.0.linux-amd64.tar.gz
sudo mv prometheus-3.4.0.linux-amd64/prometheus /usr/local/bin/
sudo chmod +x /usr/local/bin/prometheus
```

### Grafana
```bash
wget https://dl.grafana.com/oss/release/grafana_13.1.0_amd64.deb
sudo dpkg -i grafana_13.1.0_amd64.deb
```
Import `sma/per-container-dashboard.json` and `sma/process-dashboard.json` and select Prometheus `http://localhost:9090` as the data source.

### Locust
```bash
pip install locust nest_asyncio temporalio
```

## Configuration

> **Work in progress:** there isn't a single, central place to configure things like ports. Settings are currently spread across multiple files. The list may be incomplete:

- **LXC core configuration (recommended):** add the following to `/var/lib/lxc/<container_name>/config`:
  ```
  lxc.cgroup2.cpuset.cpus = <start_core>-<end_core>
  ```
  This makes LXCC scaling easier to trigger. Also since containers use distinct cores they won't interfere with each other.

- **Prometheus:** `sma/config.yaml` and `prometheus.yaml`
- **Feature flags / container names/ filepaths:** `carbon_process/flag_config.yaml` and `business_process/flags.json`
- **LXCC System Ressources, Ports, Carbon Policy values:** `CarbonContainers/code/v2/config.py`
- **LXCC Container tresholds:** `CarbonContainers/code/v2/cc-client.py`
- **Thresholds, update interval, ports:** `carbon_process/config.py`
- **Container names and ports:** `business_process/config.py`
- **Flags, container names, ports, filepaths:** `sma/main.py`
- **Filepaths:** `start_lxcc_services.sh` and `start_carbon_workflow.sh`
- **Requests per second:** `business_process/locustfile.py`

## Compute Microservice Setup

Create the containers (the current setup assumes containers named `cont1`, `cont2`, and `cont3` exist):
```bash
sudo lxc-create -n cont1 -t download -- -d ubuntu -r noble -a amd64
```

For **each** container:
```bash
sudo cp business_process/compute.py /var/lib/lxc/cont1/rootfs/root/compute.py
sudo lxc-attach -n cont1 -- bash -lc 'apt-get update'
sudo lxc-attach -n cont1 -- bash -lc 'apt install -y pip python3.12-venv'
sudo lxc-attach -n cont1 -- bash -lc 'python3 -m venv venv'
sudo lxc-attach -n cont1 -- bash -lc 'venv/bin/pip install fastapi uvicorn numpy openfeature-sdk openfeature-provider-flagd'
```
Repeat this for `cont2` and `cont3`.

## Running Everything

`sma/main.py` currently starts (and stops) Prometheus, Grafana, Temporal, the carbon workflow + worker, the LXCC services, the LXC containers, the buisness processes workers, flagd, and the microservices running inside the containers:

```bash
cd sma
sudo /home/thesis/venvs/thesis/bin/python main.py
```
(Replace the venv)

To start the business workflow (requeries the microservices): 
```bash
source /home/thesis/venvs/thesis/bin/activate
locust -f business_process/locustfile.py --headless
```
(Replace the venv)

## Output
Logs are saved at `sma/logs` and `/outputs`. Sma csv reports are saved at `sma/reports`. 

## Running Individual Components

If you don't want to start everything via `sma/main.py`, components can be started individually:

### Carbon Coordinator Workflow
Starts Temporal, the carbon workflow, and a worker:
```bash
sudo ./start_carbon_workflow.sh
```

### LXCC
Starts scaphandre and all LXCC services (records, controller, monitor, front):
```bash
sudo ./start_lxcc_services.sh
```

Register the containers with their thresholds at LXCC:
```bash
sudo /home/thesis/venvs/thesis/bin/python CarbonContainers/code/v2/cc-client.py
```
(Replace the venv)

Containers can then be started and stopped with:
```bash
sudo lxc-start -n cont1
sudo lxc-stop -n cont1
```

### Microservices + Feature Flagging

Start the flagd server (on the host):
```bash
sudo flagd start --uri file:///mnt/d/thesis/CarbonContainersThesis/business_process/flags.json --port 8013
```
(Replace the filepath)

Start the compute microservices (inside the LXC container):
```bash
sudo lxc-attach -n cont1 -- bash -lc 'cd ~ && FLAG_KEY=delivery-mode DEFAULT_MODE=high venv/bin/python -m uvicorn compute:app --host 0.0.0.0 --port 8000'
```

Test the service, from the host or another container (find the container IP via `hostname -I` or `lxc-info -n <name>`):
```bash
curl http://<ip>:8000/compute
```