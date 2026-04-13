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
                nonRunning = []
                for cont in self.conts:
                    #print(type(self.conts[cont]["location"]))
                    #print(type(self.ip))
                    #print(self.conts[cont]["location"].strip() == self.ip)
                    #print(self.conts[cont]["location"] + " == " + self.ip)

                    #print(str(self.conts[cont]["location"] != self.ip))
                    if self.conts[cont]["location"] != self.ip:
                        remotes.append(cont)
                        continue
                    if self.conts[cont]["status"].lower() != "running":
                        nonRunning.append(cont)

                #print("remotes")
                #print(remotes)
                removes = set(remotes + nonRunning)
                for rem in removes:
                    del self.conts[rem]

                
                
                print(self.conts)

                self.procMonitor()
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
    

    def getPerfEvents(self, pids):
        #try:
        print("GET PERF EVENTS")
        q = Queue()
        q2 = Queue()
        procs = []
        for pid in pids:
            p = Process(target=self.perfStat, args=(pid,q, q2))
            procs.append(p)
            print("Launcing proc check " + str(pid))
            p.start()
        # print(len(procs))
        for proc in procs:
            print("Waiting on " + str(proc))
            proc.join()
            print("Joined")


        # print("DONE")
        containers = {}
        cpuConts = {}
        for i in range(len(pids)):
            #print("ITER " + str(i))
            #print(pid)
            pid, counters = q.get()
            pidC, cpu = q2.get()
            
            for e in events:
                val = counters.get(e, 0.0)
                if isinstance(val, str):
                    val = val.strip()
                if val in ["<not counted>", "<not supported>", "", None]:
                    counters[e] = 0.0
                else:
                    try:
                        counters[e] = float(val)
                    except Exception:
                        counters[e] = 0.0
            # print("q.get done")
            cont = pids[pid]
            # count = Counter()
            # print("SUM")
            if cont in containers:
                newSums = [i+j for i,j in zip(list(counters.values()),list(containers[cont].values()))]
                newCount = dict(zip(events, newSums))
                containers[cont] = newCount
            else:
                containers[cont] = counters
            
            contC = pids[pidC]
            if contC in cpuConts:
                cpuConts[contC] = cpuConts[contC] + cpu
            else:
                cpuConts[contC] = cpu
        pass
        # print(containers)
        return containers, cpuConts
        # except Exception as ex:

        #     with open(config.WORKING_DIR + "/perfevents_excep.log", "w") as f:
        #         f.write(str(ex))


    def perfStat(self,pid,q,cpuQ):
        pass
        try:
            with open(config.WORKING_DIR + "/perfstat.test", "w") as f:
                f.write("Hello")

            cmd = ["perf", "stat", "-p", str(pid), "-x", ",", "sleep", "5"]
            out = subprocess.Popen(cmd, stderr=subprocess.PIPE).communicate()[1]
            # Read CPU% in a robust way; returns blank if process already exited.
            ps_cpu_cmd = ["ps", "-p", str(pid), "-o", "%cpu="]
            cpu_raw = subprocess.Popen(ps_cpu_cmd, stdout=subprocess.PIPE).communicate()[0]
            cpu_txt = cpu_raw.decode("utf-8").strip()
            cpu = float(cpu_txt) if cpu_txt else 0.0

            cpuQ.put((pid,cpu))

            decoded = out.decode("utf-8", errors="ignore")
            lines = []
            for l in decoded.splitlines():
                if "," not in l:
                    continue
                val = l.split(",", 1)[0].strip()
                if val:
                    lines.append(val)
            d = dict(zip(events, lines))
            for e in events:
                if e not in d:
                    d[e] = 0.0
            
            with open(config.WORKING_DIR + "/procOut/"+str(pid)+"Out.log", 'w') as f:
                f.write(str(lines))
            q.put((pid,d))
       
        except Exception as ex:

            with open(config.WORKING_DIR + "/perfstat_excep.log", "w") as f:
                f.write(str(ex))
            # Always publish defaults so parent process cannot block forever on queue.get().
            cpuQ.put((pid, 0.0))
            q.put((pid, dict(zip(events, [0.0] * len(events)))))

    def getContainerCpu(self, groupMap):
        cpuConts = {}
        containerPids = {}

        for pid, cont in groupMap.items():
            if cont in containerPids:
                containerPids[cont].append(pid)
            else:
                containerPids[cont] = [pid]

        for cont, pids in containerPids.items():
            cmd = ["ps", "-p", ",".join(pids), "-o", "%cpu="]
            out = subprocess.Popen(cmd, stdout=subprocess.PIPE).communicate()[0]
            cpu_total = 0.0
            for line in out.decode("utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    cpu_total += float(line)
                except Exception:
                    continue
            cpuConts[cont] = cpu_total

        return cpuConts

    def powerEstimate(self, conts, procs):
        try:
            with open(config.MODEL, 'rb') as f:
                model = pickle.load(f)

            carbon = config.getCarbonIntensity()

            self.time = self.time + 1
            for cont in conts:
                print("power est")
                print(cont)
                feats = list(conts[cont].values())
                # get the average counts over 5 seconds (model is trained on 5 second intervals)
                feats = list(map(lambda x: x / (config.UPDATE_PERIOD / 5), feats))
                feats = [feats]
                # print(feats)
                pred_raw = model.predict(feats)
                # sklearn may return scalar-like, [x], or [[x]] depending on model/version
                if hasattr(pred_raw, "item"):
                    try:
                        pred = float(pred_raw.item())
                    except Exception:
                        if hasattr(pred_raw, "reshape"):
                            pred = float(pred_raw.reshape(-1)[0])
                        else:
                            pred = float(pred_raw)
                elif isinstance(pred_raw, (list, tuple)):
                    first = pred_raw[0]
                    if isinstance(first, (list, tuple)):
                        pred = float(first[0])
                    else:
                        pred = float(first)
                else:
                    pred = float(pred_raw)
                # print(pred)
                print(config.MIGRATION_MACHINES[self.ip]["basepow"])
                power_marg = (pred - config.MODEL_BASE_POW) + config.MIGRATION_MACHINES[self.ip]["basepow"]
                power = pred - (config.MODEL_BASE_POW) + config.MIGRATION_MACHINES[self.ip]["basepow"]
                energy = mws_to_kwh(power * config.UPDATE_PERIOD)
                carb = carbon * energy 
                print("ENERGY KWh")
                print(energy)
                print("CARBON INTENSE gCO2/KWh")
                print(carbon)
                print("TOTAL CARB gCO2")
                print(carb)

                energy = energy * 1000
                self.conts[cont]["totals"]["joules_total"] += energy
                
                self.conts[cont]["totals"]["carbon_total"] += carb


                self.conts[cont]["current"]["carbon"] = carb
                self.conts[cont]["current"]["joules"] = energy

                os.makedirs(config.OUTPUT, exist_ok=True)
                with open(config.OUTPUT+"/"+str(time)+".txt", "w") as f:
                    f.write(str(carb))

                with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
                    stub = records_pb2_grpc.RecordsStub(c)
                    resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="ALL", setts=json.dumps(self.conts[cont])))
                    pass
                pass

        except Exception as ex:
            with open(config.WORKING_DIR + "/model_excep.log", "w") as f:
                f.write(str(ex))

    def procMonitor(self):
        try:
            print("MONITOR")
            # while True:
                
            #time.sleep(config.UPDATE_PERIOD)

            with open(config.WORKING_DIR + "/monitor.test", "w") as f:
                f.write("Hello")
            pids = self.getAllPids()
            groupMap = {}
            for pid in pids:
                cat = ["cat", "/proc/"+str(pid)+"/cgroup" ]
                systemd = ["systemctl"]
                catOut = str(subprocess.Popen(cat, stdout=subprocess.PIPE).communicate()[0])
                # Versuche erst das alte Muster (falls doch noch was altes läuft)
                match = re.search(r"lxc/([\w-]+)", str(catOut))
                if not match:
                    # Versuche das neue Muster für Cgroups v2 (sucht nach lxc.payload.<NAME>)
                    match = re.search(r"lxc\.payload\.([\w-]+)", str(catOut))

                if match:
                    group = match.group(1)
                else:
                    continue        
                
                if group in self.conts:
                    groupMap[pid] = group
                else:
                    continue

            if os.path.exists(config.WORKING_DIR + "/procOut"):
                rm = ["rm", "-r", config.WORKING_DIR + "/procOut"]
                subprocess.Popen(rm).communicate()
            os.mkdir(config.WORKING_DIR + "/procOut")   
            print(groupMap)
            print(groupMap)
            conts, contsCPU = self.getPerfEvents(groupMap)
            cpuFallback = self.getContainerCpu(groupMap)
            for cont, fb in cpuFallback.items():
                val = contsCPU.get(cont, None)
                if val is None or val == 0 or (isinstance(val, float) and math.isnan(val)):
                    contsCPU[cont] = fb

            with open(config.WORKING_DIR + "/procMonitor.out", "w") as f:
                f.write(str(conts))

            self.powerEstimate(conts, len(pids))
            #print(self.conts)
            
            print("CPU cont")
            print(contsCPU)
            for c in contsCPU:
                #print(str(c) + " : " + str(contsCPU[c]))
                self.conts[c]["current"]["cpu"] = contsCPU[c]

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
