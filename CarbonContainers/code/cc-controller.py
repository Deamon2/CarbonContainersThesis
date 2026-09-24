import sys

import subprocess
import json
import re
import asyncio
import logging

from daemon3x import daemon

import grpc

import records_pb2
import records_pb2_grpc

import controller_pb2
import controller_pb2_grpc

from concurrent import futures

import config
import math

from temporalio.client import Client

from metrics_server import metrics

from threading import Thread


logger = logging.getLogger(__name__)


class Controller(controller_pb2_grpc.ControllerServicer):

    def __init__(self, host):
        controller_pb2_grpc.ControllerServicer.__init__(self)
        self.ip = host
        self.time = 0
        self.temporal_client = None
        self.workflow_handle = None
        self.scale_direction = None
        pass

    async def ensure_temporal_connected(self):
        if self.temporal_client and self.workflow_handle:
            return True
        try:
            self.temporal_client = await Client.connect(config.TEMPORAL_ADDRESS)
            self.workflow_handle = self.temporal_client.get_workflow_handle(config.WORKFLOW_ID)
            return True
        except Exception as error:
            logger.info(f"Temporal connection failed: {error}")
            self.temporal_client = None
            self.workflow_handle = None
        return False    

    def Migrate(self, request, context):

        logger.info("CONTS TO CHECK:")

        self.conts = json.loads(request.conts)
        logger.info(self.conts)

        logger.info("CHECK")
        t = Thread(target=self.control,args=() )
        t.start()
        return controller_pb2.MigrateReply(code="1")

    def control(self):
        self.time += 1
        if len(self.conts) == 0:
            logger.info("nothing to do")
            return
        current_carbon = self.publish_carbon_intensity()
        for cont in self.conts:
            if self.conts[cont]["policy"].lower() == "none":
                with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
                    stub = records_pb2_grpc.RecordsStub(c)
                    resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="status", setts="running"))
                continue
          
            elif self.conts[cont]["policy"].lower() == "thresh":
                try:
                    cpu = self.conts[cont]["current"]["cpu"]
                    cur_cores = int(self.conts[cont]["cpu_cores"])
                    max_cores = config.MIGRATION_MACHINES[self.conts[cont]["location"]]["cpu"]
                    carb = self.conts[cont]["current"]["carbon"]
                    thresh = self.conts[cont]["threshold"]

                    cpu_percent = cpu / cur_cores

                    # check if container is frozen and if so decide whether to resume
                    if self.conts[cont]["status"] == "frozen":
                        last_cpu = float(self.conts[cont].get("freeze_last_cpu", 0.0))
                        last_joules = float(self.conts[cont].get("freeze_last_joules", 0.0))
                        freeze_cycles = int(self.conts[cont].get("freeze_cycles", 0))

                        # Convert stored Joules back to kWh for the carbon projection.
                        last_energy_kwh = max(0.0, last_joules / 3600000.0)
                        cpu_factor = max(0.25, min(1.0, last_cpu / 100.0))
                        projected_energy_kwh = last_energy_kwh * cpu_factor
                        projected_carbon = current_carbon * projected_energy_kwh

                        logger.info(f"[{cont}] FROZEN CHECK: projected carbon {projected_carbon:.7f}, "f"resume threshold {thresh:.7f}")

                        if freeze_cycles >= config.MAX_FROZEN_CYCLES:
                            logger.info(f"[{cont}] Frozen for {freeze_cycles} cycles | resume")
                            self.resume_container(cont)
                        elif projected_carbon < thresh:
                            logger.info(f"[{cont}] Carbon improved | resume")
                            self.resume_container(cont)
                        else:
                            next_cycles = freeze_cycles + 1
                            logger.info(f"[{cont}] Keeping container frozen (cycle {next_cycles}/{config.MAX_FROZEN_CYCLES})")
                            self.update_record_field(cont, "freeze_cycles", next_cycles)
                        continue

                    # True means scaling is possible on the current host
                    scale_up = (cur_cores < max_cores)
                    scale_down = (cur_cores > 1)

                    # Carbon is good: scale up if possible
                    if carb <= thresh:                    
                        if cpu_percent >= 85:
                            logger.info(f"[{cont}] SCENARIO 2: CPU at {cpu_percent:.7f}% but carbon is acceptable: {carb:.7f} < {thresh:.7f}")

                            if scale_up:
                                logger.info(f"[{cont}] Attempt 1: Vertical scale up")
                                self.scale_up(cont, cur_cores)
                                self.scale_direction = "up"
                                continue

                        logger.info(f"[{cont}] SCENARIO 1: Carbon is acceptable: {carb:.7f} < {thresh:.7f}")
                        self.update_record_field(cont, "status", "running")
                        continue

                    # Carbon bad: scale down, migrate smaller or suspend
                    elif carb > thresh:
                        logger.info(f"[{cont}] SCENARIO 3: Carbon is not acceptable: {carb:.7f} > {thresh:.7f}")

                        if scale_down:
                            logger.info(f"[{cont}] Attempt 1: Vertical scale down")
                            self.scale_down(cont, cur_cores)
                            self.scale_direction = "down"
                            continue

                        logger.info(f"[{cont}] Attempt 2: NO SCALING | SUSPENDING")
                        self.suspend_container(cont)
                        continue
                finally:
                    asyncio.run(self.send_state_update(cont))
                    self.scale_direction = None


    def publish_carbon_intensity(self):
        current_carbon = float(config.getCarbonIntensity())
        metrics.set_carbon_intensity(current_carbon)
        return current_carbon

    def update_record_field(self, cont, field, value):
        if isinstance(value, (dict, list)):
            setts = json.dumps(value)
        else:
            setts = str(value)
        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Update(records_pb2.UpdateRequest(name=cont, value=field, setts=setts))
        return resp
    
    async def send_state_update(self, cont):
        try:
            metrics.update_container(
                container_name=cont,
                carbon_threshold=self.conts[cont]["threshold"],
                cpu=self.conts[cont]["current"]["cpu"],
                current_cpu_core=int(self.conts[cont]["cpu_cores"]),
                max_cpu_core=config.MIGRATION_MACHINES[self.conts[cont]["location"]]["cpu"],
                current_joules=self.conts[cont]["current"]["joules"],
                current_carbon=self.conts[cont]["current"]["carbon"],
                suspended=self.conts[cont]["status"] == "frozen",
                total_joules=self.conts[cont]["totals"]["joules_total"],
                total_carbon=self.conts[cont]["totals"]["carbon_total"],
            )
        except Exception as error:
            logger.info(f"[{cont}] Updating Prometheus metrics failed: {error}")

        if not await self.ensure_temporal_connected():
            return
        state = {
            "container_name": cont,
            "carbon_threshold": self.conts[cont]["threshold"],
            "current_carbon": self.conts[cont]["current"]["carbon"],
            "cpu_percentage": self.conts[cont]["current"]["cpu"] / int(self.conts[cont]["cpu_cores"]),
            "current_cpu_core": int(self.conts[cont]["cpu_cores"]),
            "max_cpu_core": config.MIGRATION_MACHINES[self.conts[cont]["location"]]["cpu"],
            "suspended": self.conts[cont]["status"] == "frozen",
        }
        try: 
            await self.workflow_handle.signal("state_update", state)
        except Exception as error:
            logger.info(f"[{cont}] Sending state update to temporal failed: {error}")

    def suspend_container(self, cont):
        last_metrics = self.conts.get(cont, {}).get("current", {})
        freeze_last_cpu = float(last_metrics.get("cpu", 0.0))
        freeze_last_joules = float(last_metrics.get("joules", 0.0))

        command = ["lxc-freeze", "-n", str(cont)]
        subprocess.Popen(command).communicate()

        frozen_state = dict(self.conts.get(cont, {}))
        frozen_state["freeze_last_cpu"] = freeze_last_cpu
        frozen_state["freeze_last_joules"] = freeze_last_joules
        frozen_state["freeze_cycles"] = 1
        frozen_state["status"] = "frozen"
        current = dict(frozen_state.get("current", {}))
        current["carbon"] = 0.0
        current["joules"] = 0.0
        current["cpu"] = 0.0
        frozen_state["current"] = current

        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="ALL", setts=json.dumps(frozen_state)))
        
        logger.info(f"[{cont}] Container is now FROZEN")

    def resume_container(self, cont):
        command = ["lxc-unfreeze", "-n", str(cont)]
        subprocess.Popen(command).communicate()
        
        self.update_record_field(cont, "status", "running")
        self.update_record_field(cont, "freeze_cycles", 0)
        
        logger.info(f"[{cont}] Container is now RUNNING")

    def build_cpuset_range(self, start_core, new_cpu, physical_cores):
        """new_cpu logische Threads ab start_core.
        erwartet 2 Threads/Kern (Sibling-Offset = physical_cores)"""
        n_thread0 = math.ceil(new_cpu / 2)
        n_thread1 = new_cpu - n_thread0

        end0 = start_core + n_thread0 - 1
        part0 = str(start_core) if start_core == end0 else f"{start_core}-{end0}"

        if n_thread1 <= 0:
            return part0

        base = start_core + physical_cores
        end1 = base + n_thread1 - 1
        part1 = str(base) if base == end1 else f"{base}-{end1}"

        return f"{part0},{part1}"

    # scaled logische cores 
    def scale_up(self,cont,currentCpu):
        cpus = subprocess.check_output(["lxc-cgroup", "-n", cont, "cpuset.cpus"], text=True).strip()
        start_core = int(re.search(r"\d+", cpus).group())           # cpu cures should be a range e.g. 0-1, 6-7 
        host_max_threads = config.MIGRATION_MACHINES[self.conts[cont]["location"]]["cpu"]
        physical_cores  = config.MIGRATION_MACHINES[self.conts[cont]["location"]]["physical_cores"]
        new_cpu = min(host_max_threads, max(1, math.ceil(currentCpu * 1.25)))
        cpuset_str = self.build_cpuset_range(start_core, new_cpu, physical_cores)
        command = ["lxc-cgroup", "-n", str(cont), "cpuset.cpus", cpuset_str]
        subprocess.Popen(command).communicate()
        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="cpu_cores", setts=str(new_cpu)))

        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="status", setts="running"))

        logger.info(f"[{cont}] Container has been SCALED UP")
        return new_cpu

    def scale_down(self,cont,currentCpu):
        cpus = subprocess.check_output(["lxc-cgroup", "-n", cont, "cpuset.cpus"], text=True).strip()
        start_core = int(re.search(r"\d+", cpus).group())
        physical_cores  = config.MIGRATION_MACHINES[self.conts[cont]["location"]]["physical_cores"]
        new_cpu = max(1, int(currentCpu * 0.75))
        cpuset_str = self.build_cpuset_range(start_core, new_cpu, physical_cores)
        command = ["lxc-cgroup", "-n", str(cont), "cpuset.cpus", cpuset_str]
        subprocess.Popen(command).communicate()
        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="cpu_cores", setts=str(new_cpu)))
        
        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="status", setts="running"))

        logger.info(f"[{cont}] Container has been SCALED DOWN")
        return new_cpu
    

def run(ip, port):
    server = grpc.server(thread_pool=futures.ThreadPoolExecutor(max_workers=5),maximum_concurrent_rpcs=5)
    controller_pb2_grpc.add_ControllerServicer_to_server(Controller(ip), server)
    server.add_insecure_port("[::]:"+str(port))
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    ip = sys.argv[1]
    port = config.CONTROLLER_PORT

    run(ip,port)
