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
import asyncio
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
import math

from temporalio.client import Client

from metrics_server import metrics



from threading import Thread

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
            print(f"Temporal connection failed: {error}")
            self.temporal_client = None
            self.workflow_handle = None
        return False

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

    def Migrate(self, request, context):

        # with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
        #     stub = records_pb2_grpc.RecordsStub(c)
        #     resp = stub.Lookup(records_pb2.LookupRequest(name="ALL"))
            
        # self.conts = json.loads(resp.results)

        

        #print("remove remotes")
        # remotes = []
        # for cont in self.conts:
        #     if self.conts[cont]["location"] != self.ip:
        #         remotes.append(cont)

        # for rem in remotes:
        #     del self.conts[rem]

        print("CONTS TO CHECK:")

        self.conts = json.loads(request.conts)
        print(self.conts)

        print("CHECK")
        t = Thread(target=self.migration,args=() )
        t.start()
        return controller_pb2.MigrateReply(code="1")
    
    def Recieve(self, request, context):

        cont = request.cont
        t = Thread(target=self.migrate_recv, args=(cont,))
        t.start()
        return controller_pb2.RecieveReply(code="1")
    
    async def send_state_update(self, cont, scale_direction):
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
            print(f"[{cont}] Updating Prometheus metrics failed: {error}")

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
            print(f"[{cont}] Sending state update to temporal failed: {error}")
        


    def migration(self):
        self.time += 1
        if len(self.conts) == 0:
            print("nothing to do")
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
                    curMach = config.MIGRATION_MACHINES[self.conts[cont]["location"]]

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

                        print(f"[{cont}] FROZEN CHECK: projected carbon {projected_carbon:.4f}, "f"resume threshold {thresh:.4f}")

                        if freeze_cycles >= config.MAX_FROZEN_CYCLES:
                            print(f"[{cont}] Frozen for {freeze_cycles} cycles | resume")
                            self.resume_container(cont)
                        elif projected_carbon < thresh:
                            print(f"[{cont}] Carbon improved | resume")
                            self.resume_container(cont)
                        else:
                            next_cycles = freeze_cycles + 1
                            print(f"[{cont}] Keeping container frozen (cycle {next_cycles}/{config.MAX_FROZEN_CYCLES})")
                            self.update_record_field(cont, "freeze_cycles", next_cycles)
                        continue

                    # True means scaling is possible on the current host
                    scale_up = (cur_cores < max_cores)

                    if nextSmaller(curMach["host"]):
                        next_smaller_cores = config.MIGRATION_MACHINES[nextSmaller(curMach["host"])]["cpu"]

                        # DONT SCALE DOWN IF YOU'LL SCALE TO BELOW THE RESOURCES AT A SMALLER MACHINE; DONT SCALE TO 0
                        if (int(cur_cores * 0.75) <= next_smaller_cores) or int(cur_cores * 0.75) == 0:
                            scale_down = False
                        else: 
                            scale_down = True 
                    else:
                        next_smaller_cores = "-1"
                        # No smaller host exists, only scale if we won't hit 0
                        if int(cur_cores * 0.75) == 0:
                            scale_down = False
                        else:
                            scale_down = True

                    # Carbon is good: scale up or migrate bigger
                    if carb <= thresh:                    
                        if cpu_percent >= 85:
                            print(f"[{cont}] SCENARIO 2: CPU at {cpu_percent:.0f}% but carbon is acceptable: {carb:.2f} < {thresh:.2f}")

                            if scale_up:
                                print(f"[{cont}] Attempt 1: Vertical scale up")
                                self.scale_up(cont, cur_cores)
                                self.scale_direction = "up"
                                continue

                            target = nextBigger(curMach["host"])
                            if target:
                                print(f"[{cont}] Attempt 2: Migrating to larger host: {target}")
                                self.migrate_send(cont, target)
                                continue

                        print(f"[{cont}] SCENARIO 1: Carbon is acceptable: {carb:.2f} < {thresh:.2f}")
                        self.update_record_field(cont, "status", "running")
                        continue

                    # Carbon bad: scale down, migrate smaller or suspend
                    elif carb > thresh:
                        print(f"[{cont}] SCENARIO 3: Carbon is not acceptable: {carb:.2f} > {thresh:.2f}")

                        if scale_down:
                            print(f"[{cont}] Attempt 1: Vertical scale down")
                            self.scale_down(cont, cur_cores)
                            self.scale_direction = "down"
                            continue

                        target = nextSmaller(curMach["host"])
                        if target:
                            print(f"[{cont}] Attempt 2: Migrate to smaller host {target}")
                            self.migrate_send(cont, target)
                            continue

                        print(f"[{cont}] Attempt 3: NO SCALING/MIGRATION/FLAG OPTIONS | SUSPENDING")
                        self.suspend_container(cont)
                        continue
                finally:
                    asyncio.run(self.send_state_update(cont, scale_direction=self.scale_direction))
                    self.scale_direction = None


            # HIGH PERFORMANCE POLICY
            elif self.conts[cont]["policy"].lower() == "target":
                '''
                if throttled and below target
                    size up
                elif carbon exceeded
                    size down
                elif carbon below some parameterized % of target
                    size up
                '''
                cpu = self.conts[cont]["current"]["cpu"]
                carb = self.conts[cont]["current"]["carbon"]
                thresh = self.conts[cont]["threshold"]
                curMach = config.MIGRATION_MACHINES[self.conts[cont]["location"]]
                
                cur_cores = int(self.conts[cont]["cpu_cores"])
                # max_cores = config.MIGRATION_MACHINES[self.conts[cont]["location"]]["cpu"]
                if nextSmaller(curMach["host"]):
                    next_smaller_cores = config.MIGRATION_MACHINES[nextSmaller(curMach["host"])]["cpu"]

                    # DONT SCALE DOWN IF YOU'LL SCALE TO BELOW THE RESOURCES AT A SMALLER MACHINE; DONT SCALE TO 0
                    if (int(cur_cores * 0.75) <= next_smaller_cores) or int(cur_cores * 0.75) == 0:
                        scale = False
                    else: 
                        scale = True
                else:
                    next_smaller_cores = "-1"
                    if int(cur_cores * 0.75) == 0:
                        scale = False
                    else:
                        scale = True
                

                if cpu == float(curMach["cpu"]*100) and carb < float(thresh):
                    print("SIZE UP")
                    target = nextBigger(curMach["host"])
                    if target:
                        print("Migrate to " + str(target))
                        self.migrate_send(cont,target) 

                    pass

                elif carb > float(thresh):
                    print("SIZE DOWN")
                    target = nextSmaller(curMach["host"])
                    if target:
                        print("Migrate to " + str(target))
                        self.migrate_send(cont,target) 

                    pass

                elif carb <= float(thresh) * (1-config.SCALEUP_THRESH):
                    print("SIZE UP")
                    target = nextBigger(curMach["host"])
                    if target:
                        print("Migrate to " + str(target))
                        self.migrate_send(cont,target) 


                else:
                    with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
                        stub = records_pb2_grpc.RecordsStub(c)
                        resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="status", setts="running"))
                pass

            elif self.conts[cont]["policy"].lower() == "suspend":
                pass
        pass
    def migrate_target(self,current, scale_down):
        

        if scale_down:
            target = nextSmaller(current)
        else:
            target = nextBigger(current)

        return target

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
        
        print(f"[{cont}] Container is now FROZEN")

    def resume_container(self, cont):
        command = ["lxc-unfreeze", "-n", str(cont)]
        subprocess.Popen(command).communicate()
        
        self.update_record_field(cont, "status", "running")
        self.update_record_field(cont, "freeze_cycles", 0)
        
        print(f"[{cont}] Container is now RUNNING")

    def migrate_send(self, contName, target):

        with open (config.M_OUTPUT+"/"+str(self.time)+".txt", "w") as f:
            f.write(str(target))

        if os.path.exists(config.WORKING_DIR + "/checkpoint_"+str(contName)):
            os.rmdir(config.WORKING_DIR + "/checkpoint_"+str(contName))

        print("Make check dir")
        #os.mkdir(config.WORKING_DIR + "/checkpoint_"+str(contName))
        os.mkdir("/var/lib/lxc/"+str(contName)+"/check")

        print("lxc-check")
        checkpoint = ["lxc-checkpoint", "-s", "-D", "/var/lib/lxc/"+str(contName)+"/check", "-n", contName]
        subprocess.Popen(checkpoint).communicate()

        print("Copy Container Dict")
        copyContDir = ["cp", "-r", "/var/lib/lxc/"+str(contName), config.WORKING_DIR]
        subprocess.Popen(copyContDir).communicate()

        #print("Move Check into container dir")
        #move = ["mv", config.WORKING_DIR + "/checkpoint_"+str(contName), config.WORKING_DIR + "/" + str(contName) ]
        #subprocess.Popen(move).communicate()



        print("tar container fs")
        tarCont = ["tar", "--numeric-owner", "-czvf", config.WORKING_DIR + "/" + str(contName)+".tar.gz", config.WORKING_DIR+"/"+str(contName)]
        subprocess.Popen(tarCont).communicate()

        # print("zip")
        # zipCont = ["zip", "-r", config.WORKING_DIR+"/"+str(contName)+".zip", config.WORKING_DIR+"/"+str(contName)]
        # subprocess.Popen(zipCont, stdout=subprocess.PIPE).communicate()
    
        
        print("scp filesystem")
        scp = ["scp", "-i", config.SSH_KEY_PATH, config.WORKING_DIR+"/"+str(contName) + ".tar.gz", config.SSH_USER+"@"+target+":"+config.WORKING_DIR]
        subprocess.Popen(scp).communicate()
        
        #os.chdir(config.WORKING_DIR)



        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Update(records_pb2.UpdateRequest(name=contName, value="location", setts=target))
                
        with grpc.insecure_channel( target +":" + config.CONTROLLER_PORT) as c:
            stub = controller_pb2_grpc.ControllerStub(c)
            resp = stub.Recieve(controller_pb2.RecieveRequest(cont=contName))

    
        print("destroy old")
        destroyOldCont = ["lxc-destroy", str(contName)]
        subprocess.Popen(destroyOldCont).communicate()
        rm1 = ["rm", "-r", config.WORKING_DIR+"/"+str(contName)]
        rm2 = ["rm", config.WORKING_DIR+"/"+str(contName)+".tar.gz"]
        subprocess.Popen(rm1).communicate()
        subprocess.Popen(rm2).communicate()
        # self.conts[contName]["status"] = "remote @ " + str(target)

        # with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        #     s.connect( (target, config.MIGRATION_PORT) )
        #     encode = json.dumps({contName: self.conts[contName]}).encode("utf-8")
        #     s.sendall(encode)

        pass


   
    def migrate_recv(self, name):
       
        # with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    
        #     s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        #     s.bind( (self.host, config.MIGRATION_PORT) )
        #     # print("listening")
        #     s.listen(1)
        #     conn, addr = s.accept()
            # with conn:
                # data = conn.recv(2048)
                # cont = json.loads(data.decode("utf-8"))

                # name = list(cont.keys())[0]

        # print("unzip")
        # unzip = ["unzip", config.WORKING_DIR+"/"+str(name)+".zip", "-d", config.WORKING_DIR ]
        # print(unzip)
        # subprocess.Popen(unzip).communicate()

        print("untar")
        untar = ["tar", "--numeric-owner", config.WORKING_DIR + "/" +str(name)+".tar.gz"]
        subprocess.Popen(untar).communicate()

        print("relocate")
        move = ["mv", config.WORKING_DIR+"/var/lib/lxc/"+str(name), "/var/lib/lxc"]
        subprocess.Popen(move).communicate()

        print("restore")
        restart = ["lxc-checkpoint", "-r", "-D", "/var/lib/lxc/"+str(name)+"/check", "-n", str(name)]
        subprocess.Popen(restart).communicate()
        # self.conts[cont[""]]

        print("cleanup")
        cleanup1 = ["rm", config.WORKING_DIR+"/"+str(name)+".tar.gz"]
        cleanup2 = ["rm", "-r", "/var/lib/lxc/"+str(name)+"/check"]
        cleanup3 = ["rm", "-r", config.WORKING_DIR+"/var"]

        subprocess.Popen(cleanup1).communicate()
        subprocess.Popen(cleanup2).communicate()
        subprocess.Popen(cleanup3).communicate()

        print("done")

        #with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
        #    stub = records_pb2_grpc.RecordsStub(c)
        #    resp = stub.Update(records_pb2.UpdateRequest(name=contName, value="ALL", setts=))
        # self.conts[name] = cont[name]


    def scale_up(self,cont,currentCpu):
        cpus = subprocess.check_output(["lxc-cgroup", "-n", cont, "cpuset.cpus"], text=True).strip()
        start_core = int(re.search(r"\d+", cpus).group())           # cpu cures should be a range e.g. 0-1
        new_cpu = max(1, math.ceil(currentCpu * 1.25))
        end_core = start_core + new_cpu - 1
        command = ["lxc-cgroup", "-n", str(cont), "cpuset.cpus", f"{start_core}-{end_core}"]
        subprocess.Popen(command).communicate()
        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="cpu_cores", setts=str(new_cpu)))

        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="status", setts="running"))

        print(f"[{cont}] Container has been SCALED UP")
        return new_cpu
        pass

    def scale_down(self,cont,currentCpu):
        cpus = subprocess.check_output(["lxc-cgroup", "-n", cont, "cpuset.cpus"], text=True).strip()
        start_core = int(re.search(r"\d+", cpus).group())
        new_cpu = max(1, int(currentCpu * 0.75))
        end_core = start_core + new_cpu - 1
        command = ["lxc-cgroup", "-n", str(cont), "cpuset.cpus", f"{start_core}-{end_core}"]
        subprocess.Popen(command).communicate()
        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="cpu_cores", setts=str(new_cpu)))
        
        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="status", setts="running"))

        print(f"[{cont}] Container has been SCALED DOWN")
        return new_cpu
        pass


    def reset_scale(self, cont):
        cpu = config.MACHINES[str(self.ip)]["cpu"]
        command = ["lxc-cgroup", "-n", str(cont), "cpuset", "0-"+str(cpu-1)]
        subprocess.Popen(command).communicate()
        return cpu
    

def run(ip, port):
    server = grpc.server(thread_pool=futures.ThreadPoolExecutor(max_workers=5),maximum_concurrent_rpcs=5)
    # order_pb2_grpc.add_OrderServicer_to_server(Order(mode), server)
    # front_pb2_grpc.add_FrontServicer_to_server(Front(), server)
    # records_pb2_grpc.add_RecordsServicer_to_server(Records(), server)
    controller_pb2_grpc.add_ControllerServicer_to_server(Controller(ip), server)
    server.add_insecure_port("[::]:"+str(port))
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    ip = sys.argv[1]
    port = config.CONTROLLER_PORT

    run(ip,port)
