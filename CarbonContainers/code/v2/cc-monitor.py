import sys
import os
import subprocess
import sqlite3
import argparse
import threading
import time
import socket
import json
import pickle
import re
import math
import requests
from multiprocessing import Process, Queue

from daemon3x import daemon

import grpc
import front_pb2
import front_pb2_grpc

import records_pb2
import records_pb2_grpc

import controller_pb2
import controller_pb2_grpc

from concurrent import futures

import config

events = ["task-clock", "context-switches", "cpu-migrations", "page-faults", "cycles", "instructions", "branches", "branch-misses"]        

def mws_to_kwh(n):
    return n / (3600000000)
    pass


def nextSmaller(current):
    curCPU = config.MIGRATION_MACHINES[current]["cpu"]
    smallerM = dict( (key,val) for key,val in config.MIGRATION_MACHINES.items() if val["cpu"] < curCPU)
    curMax = 0
    curTarget = current
    for m in smallerM:
        if smallerM[m]["cpu"] > curMax:
            curTarget = m
            curMax = smallerM[m]["cpu"]

    if curTarget != current:
        return curTarget
    else:
        return False

def nextBigger(current):
    curCPU = config.MIGRATION_MACHINES[current]["cpu"]
    largerM = dict( (key,val) for key,val in config.MIGRATION_MACHINES.items() if val["cpu"] > curCPU)
    curMin = math.inf
    curTarget = current
    for m in largerM:

        if largerM[m]["cpu"] < curMin:
            curTarget = m
            curMin = largerM[m]["cpu"]

    if curTarget != current:
        return curTarget
    else:
        return False

class CC_Monitor(daemon):

    
    
    def __init__(self, pidfile, host):
        self.conts = {}
        self.ip = str(host).strip()
        self.time = 0
        self.cpu_stat_prev = {}
        super().__init__(pidfile)
        
    
    def run(self):
        try:
            while True:
                time.sleep(config.UPDATE_PERIOD)
                print("GET RECORDS")
                with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
                    stub = records_pb2_grpc.RecordsStub(c)
                    resp = stub.Lookup(records_pb2.LookupRequest(name="ALL"))
            
                self.conts = json.loads(resp.results)

                #print("remove remotes")
                remotes = []
                not_actionable = []
                for cont in self.conts:
                    #print(type(self.conts[cont]["location"]))
                    #print(type(self.ip))
                    #print(self.conts[cont]["location"].strip() == self.ip)
                    #print(self.conts[cont]["location"] + " == " + self.ip)

                    #print(str(self.conts[cont]["location"] != self.ip))
                    if self.conts[cont]["location"] != self.ip:
                        remotes.append(cont)
                        continue

                    status = str(self.conts[cont].get("status", "")).lower()
                    # Controller should only act on running/frozen containers.
                    if status not in ["running", "frozen"]:
                        not_actionable.append(cont)

                #print("remotes")
                #print(remotes)
                removes = set(remotes + not_actionable)
                for rem in removes:
                    del self.conts[rem]

                active_conts = {}
                for cont, data in self.conts.items():
                    status = str(data.get("status", "")).lower()
                    if status == "frozen":
                        continue
                    active_conts[cont] = data

                
                
                print(self.conts)

                self.procMonitor(active_conts)
                print("CONTROL ACTION")
                # self.migration()
                with grpc.insecure_channel("localhost:" + config.CONTROLLER_PORT) as c:
                    stub = controller_pb2_grpc.ControllerStub(c)
                    resp = stub.Migrate(controller_pb2.MigrateRequest(conts=json.dumps(self.conts)))
                
                print(resp)
            # t1 = threading.Timer(1.0, self.check_carbon)
            # # t2 = threading.Timer(1.0, self.listen)
            # t3 = threading.Timer(1.0, self.procMonitor)
            # t4 = threading.Timer(1.0, self.migrate_recv)

            # # t1.start()
            # # t2.start()
            # t3.start()

        except Exception as ex:

            with open(config.WORKING_DIR + "/run_excep.log", "w") as f:
                f.write(str(ex))

    
        except Exception as ex:

            with open(config.WORKING_DIR + "/checkcarbon_excep.log", "w") as f:
                f.write(str(ex))

    def applyPolicy(self, contName, contSetts, carb):
        pass
    

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
    

    def getPerfEvents(self, group_map):
        """Run `perf stat` for each PID in parallel and aggregate results per container.

        `group_map` is a dict mapping pid -> container_name. Returns a tuple
        (event_counters_by_container, cpu_by_container).
        """
        event_q = Queue()
        cpu_q = Queue()
        workers = []

        # Launch a worker process per PID to collect perf counters and cpu%%
        for pid in group_map:
            process = Process(target=self.perfStat, args=(pid, event_q, cpu_q))
            workers.append(process)
            process.start()

        # Wait for all workers to finish
        for worker in workers:
            worker.join()

        # Aggregate results per container
        containers = {}
        cpu_by_container = {}
        for _ in range(len(group_map)):
            pid, counters = event_q.get()
            pid_for_cpu, cpu = cpu_q.get()

            # normalize counter values to floats
            for event in events:
                val = counters.get(event, 0.0)
                if isinstance(val, str):
                    val = val.strip()
                if val in ["<not counted>", "<not supported>", "", None]:
                    counters[event] = 0.0
                else:
                    try:
                        counters[event] = float(val)
                    except Exception:
                        counters[event] = 0.0

            cont = group_map[pid]
            # sum counters if multiple PIDs belong to the same container
            if cont in containers:
                new_sums = [i + j for i, j in zip(list(counters.values()), list(containers[cont].values()))]
                containers[cont] = dict(zip(events, new_sums))
            else:
                containers[cont] = counters

            cont_cpu = group_map[pid_for_cpu]
            cpu_by_container[cont_cpu] = cpu_by_container.get(cont_cpu, 0.0) + cpu

        return containers, cpu_by_container
        # except Exception as ex:

        #     with open(config.WORKING_DIR + "/perfevents_excep.log", "w") as f:
        #         f.write(str(ex))


    def perfStat(self, pid, event_q, cpu_q):
        # Run `perf stat -p <pid>` for a short duration and parse counters.
        # Push parsed event counters to `event_q` and CPU percent to `cpu_q`.
        try:
            with open(config.WORKING_DIR + "/perfstat.test", "w") as f:
                f.write("Hello")

            cmd = ["perf", "stat", "-p", str(pid), "-x", ",", "sleep", "5"]
            perf_out = subprocess.Popen(cmd, stderr=subprocess.PIPE).communicate()[1]

            top = "top -b -n 2 -d 0.5 -p" + str(pid) + " | tail -1 | awk '{print $9}'"
            cpu = subprocess.Popen(top, shell=True, stdout=subprocess.PIPE).communicate()[0]
            cpu = float(cpu.decode("utf-8").strip())

            cpu_q.put((pid, cpu))

            lines = [l.replace("b'", "").split(",")[0] for l in str(perf_out).split("\\n") if l != "'" ]
            counters_dict = dict(zip(events, lines))

            with open(config.WORKING_DIR + "/procOut/" + str(pid) + "Out.log", 'w') as f:
                f.write(str(lines))

            event_q.put((pid, counters_dict))

        except Exception as ex:
            with open(config.WORKING_DIR + "/perfstat_excep.log", "w") as f:
                f.write(str(ex))
            # Always publish defaults so parent process cannot block forever on queue.get().
            cpu_q.put((pid, 0.0))
            event_q.put((pid, dict(zip(events, [0.0] * len(events)))))


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

    def get_scaphandre_pid_powers(self):
        try:
            request = requests.get("http://localhost:8080/metrics")
        except Exception as error:
            print(f"Could not fetch Scaphandre metrics: {error}")
            return {}
        pid_power = {}
        for line in request.text.splitlines():
            if line.startswith("scaph_process_power_consumption_microwatts"):
                pid_match = re.search(r'pid="(\d+)"', line)
                mw_match = re.search(r'\}\s+([\d.]+)', line)
                if pid_match and mw_match:
                    pid = pid_match.group(1)
                    microwatts = float(mw_match.group(1))
                    if microwatts > 0:
                        pid_power[pid] = microwatts
        return pid_power

    def powerEstimate(self, conts, groupMap):
        # groupMap = {pid: container_name}
        carbon = config.getCarbonIntensity() # gCO2/kWh
        self.time += 1

        pid_power = self.get_scaphandre_pid_powers()

        # Invertiere groupMap: container -> [pids]
        cont_pids = {}
        for pid, cont in groupMap.items():
            cont_pids.setdefault(cont, []).append(str(pid))

        for cont in conts:
            # Summiere Scaphandre-Power für alle PIDs dieses Containers
            power_uw = sum(pid_power.get(pid, 0.0) for pid in cont_pids.get(cont, []))
            power_w = power_uw / 1000000

            energy_kwh = mws_to_kwh(power_w * 1000 * config.UPDATE_PERIOD)
            energy_j = energy_kwh * 3600000
            carb = carbon * energy_kwh # gCO2

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
            # while True:
                
            #time.sleep(config.UPDATE_PERIOD)

            with open(config.WORKING_DIR + "/monitor.test", "w") as f:
                f.write("Hello")
            all_pids = self.getAllPids()
            if active_conts is None:
                active_conts = self.conts

            group_map = {}
            for pid in all_pids:
                cat = ["cat", "/proc/" + str(pid) + "/cgroup"]
                systemd = ["systemctl"]
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

            conts, cpu_from_perf = self.getPerfEvents(group_map)      # perf gibt nicht die korrekte CPU auslastung zurück -> nutze cpu.stat
            cpu_map = self.getContainerCpu(group_map)

            with open(config.WORKING_DIR + "/procMonitor.out", "w") as f:
                f.write(str(conts))

            self.powerEstimate(conts, group_map)

            print("CPU cont: " + str(cpu_map))
            for cont in cpu_map:
                self.conts[cont]["current"]["cpu"] = cpu_map[cont]

            print(self.conts)
            #for c in groupMap:
                #if groupMap[c] in self.conts:

                #print(str(c) + " : " + str(groupMap[c]))

        except Exception as ex:
            with open(config.WORKING_DIR + "/procMonitor_excep.log", "w") as f:
                f.write(str(ex))

   
        
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
    # if sys.argv[2] == "start":
    #     d.start()
    
    # elif sys.argv[2] == "stop":
    #     d.stop()

    # sys.exit(0)
    #run()
