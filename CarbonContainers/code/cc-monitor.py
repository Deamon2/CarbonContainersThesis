import sys
import os
import subprocess
import time
import json
import re
import traceback

from energy_accumulator import EnergyAccumulator
from daemon3x import daemon

import grpc

import records_pb2
import records_pb2_grpc

import controller_pb2
import controller_pb2_grpc

import config


class CC_Monitor(daemon):

    
    
    def __init__(self, pidfile, host):
        self.conts = {}
        self.ip = str(host).strip()
        self.time = 0
        self.cpu_stat_prev = {}
        super().__init__(pidfile)
        self.energy_accumulator = EnergyAccumulator(max_top_consumers=2000)
        self.energy_accumulator.start()
        
    
    def run(self):
        try:
            while True:
                time.sleep(config.UPDATE_PERIOD)
                print("GET RECORDS")
                with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
                    stub = records_pb2_grpc.RecordsStub(c)
                    resp = stub.Lookup(records_pb2.LookupRequest(name="ALL"))
            
                self.conts = json.loads(resp.results)

                not_actionable = []
                for cont in self.conts:
                    status = str(self.conts[cont].get("status", "")).lower()
                    # Controller should only act on running/frozen containers.
                    if status not in ["running", "frozen"]:
                        not_actionable.append(cont)

                for cont in not_actionable:
                    del self.conts[cont]

                active_conts = {}
                for cont, data in self.conts.items():
                    status = str(data.get("status", "")).lower()
                    if status == "frozen":
                        continue
                    active_conts[cont] = data

                self.procMonitor(active_conts)
                print("CONTROL ACTION")
                with grpc.insecure_channel("localhost:" + config.CONTROLLER_PORT) as c:
                    stub = controller_pb2_grpc.ControllerStub(c)
                    resp = stub.Migrate(controller_pb2.MigrateRequest(conts=json.dumps(self.conts)))
                
                print(resp)

        except Exception as ex:

            with open(config.WORKING_DIR + "/run_excep.log", "w") as f:
                f.write(str(ex))
    

    def getAllPids(self):

        try:
            pass
            psCmd = ['ps', '-e', '-o', 'pid']
            out = subprocess.Popen(psCmd, stdout=subprocess.PIPE).communicate()[0]
            out = ''.join(map(chr,out))

            return out.split()[1:]
        except Exception as ex:
                    
            with open(config.WORKING_DIR + "/getpid_excep.log", "w") as f:
                f.write(str(ex))

    def read_cpu_stat(self, cont_name: str):
        path = f"/sys/fs/cgroup/lxc.payload.{cont_name}/cpu.stat"
        try:
            with open(path) as f:
                for line in f:
                    if line.startswith("usage_usec"):
                        return int(line.split()[1])
        except (FileNotFoundError, PermissionError, ValueError):
            pass
        return None

    def getContainerCpu(self, group_map: dict):
        """
        CPU-Auslastung pro Container durch cgroup cpu.stat
        """
        containers = set(group_map.values())
        
        now = time.monotonic()
        cpu_by_container = {}

        for cont in containers:
            usage_usec = self.read_cpu_stat(cont)
            if usage_usec is None:
                cpu_by_container[cont] = 0.0
                continue

            prev = self.cpu_stat_prev.get(cont)
            if prev is None:
                self.cpu_stat_prev[cont] = (usage_usec, now)
                cpu_by_container[cont] = 0.0
                continue

            prev_usec, prev_time = prev
            diff_usec = usage_usec - prev_usec
            diff_wall_usec = (now - prev_time) * 1000000  # s -> µs

            utilization = (diff_usec / diff_wall_usec) * 100.0
            utilization = max(0.0, utilization) # sollte eigentlich nie negativ sein

            cpu_by_container[cont] = utilization
            self.cpu_stat_prev[cont] = (usage_usec, now)

        return cpu_by_container

    def powerEstimate(self, conts, groupMap):
        # groupMap = {pid: container_name}
        carbon = config.getCarbonIntensity() # gCO2/kWh
        self.time += 1

        # Invertiere groupMap: container -> [pids]
        cont_pids = {}
        for pid, cont in groupMap.items():
            cont_pids.setdefault(cont, []).append(int(pid))

        all_pids = [pid for pids in cont_pids.values() for pid in pids]
        energy_by_pid = self.energy_accumulator.read_and_reset(all_pids)

        for cont in conts:
            energy_j = sum(energy_by_pid.get(pid, 0.0) for pid in cont_pids.get(cont, []))
            energy_kwh = energy_j / 3600000
            carb = carbon * energy_kwh  # gCO2

            self.conts[cont]["totals"]["joules_total"] += energy_j
            self.conts[cont]["totals"]["carbon_total"] += carb
            self.conts[cont]["current"]["carbon"] = carb
            self.conts[cont]["current"]["joules"] = energy_j

            os.makedirs(config.OUTPUT, exist_ok=True)
            with open(config.OUTPUT+"/"+str(self.time)+".txt", "w") as f:
                f.write(str(carb))

            with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
                stub = records_pb2_grpc.RecordsStub(c)
                resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="ALL", setts=json.dumps(self.conts[cont])))
                pass
            pass

    def procMonitor(self, active_conts=None):
        try:
            print("MONITOR")
            with open(config.WORKING_DIR + "/monitor.test", "w") as f:
                f.write("Hello")
            all_pids = self.getAllPids()
            if active_conts is None:
                active_conts = self.conts

            group_map = {}
            for pid in all_pids:
                cat = ["cat", "/proc/" + str(pid) + "/cgroup"]
                catOut = str(subprocess.Popen(cat, stdout=subprocess.PIPE).communicate()[0])
                # Versuche erst das alte Muster
                match = re.search(r"lxc/([\w-]+)", str(catOut))
                if not match:
                    # Versuche das neue Muster für Cgroups v2
                    match = re.search(r"lxc\.payload\.([\w-]+)", str(catOut))

                if match:
                    group = match.group(1)
                else:
                    continue

                if group in active_conts:
                    group_map[pid] = group
                else:
                    continue

            if os.path.exists(config.WORKING_DIR + "/procOut"):
                rm = ["rm", "-r", config.WORKING_DIR + "/procOut"]
                subprocess.Popen(rm).communicate()
            os.mkdir(config.WORKING_DIR + "/procOut")
            print(group_map)

            conts = list(dict.fromkeys(group_map.values()))
            cpu_map = self.getContainerCpu(group_map)

            with open(config.WORKING_DIR + "/procMonitor.out", "w") as f:
                f.write(str(conts))

            self.powerEstimate(conts, group_map)

            print("CPU cont: " + str(cpu_map))
            for cont in cpu_map:
                self.conts[cont]["current"]["cpu"] = cpu_map[cont]

            print(self.conts)

        except Exception as ex:
            with open(config.WORKING_DIR + "/procMonitor_excep.log", "w") as f:
                f.write(traceback.format_exc())

   
        
def run():
    while True:
    
        time.sleep(config.UPDATE_PERIOD)
        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Lookup(records_pb2.LookupRequest(name="ALL"))
        
        conts = json.loads(resp.results)

        print(conts)
        

if __name__ == "__main__":
    
    d = CC_Monitor(config.WORKING_DIR + "/daemon.pid", sys.argv[1])
    d.run()
