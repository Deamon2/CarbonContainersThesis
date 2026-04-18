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
        pass

    def update_record_field(self, cont, field, value):
        if isinstance(value, (dict, list)):
            setts = json.dumps(value)
        else:
            setts = str(value)
        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Update(records_pb2.UpdateRequest(name=cont, value=field, setts=setts))
        return resp

    def set_container_state(self, cont, updates):
        with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
            stub = records_pb2_grpc.RecordsStub(c)
            resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="ALL", setts=json.dumps(updates)))
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


    def migration(self):
        self.time += 1
        if len(self.conts) == 0:
            print("nothing to do")
            return
        for cont in self.conts:
            if self.conts[cont]["policy"].lower() == "none":
                with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
                    stub = records_pb2_grpc.RecordsStub(c)
                    resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="status", setts="running"))
                continue
          
            # ENERGY EFFICIENT POLICY
            elif self.conts[cont]["policy"].lower() == "thresh":
                
                # Load current metrics and configuration
                cpu = self.conts[cont]["current"]["cpu"]
                carb = self.conts[cont]["current"]["carbon"]
                thresh = self.conts[cont]["threshold"]
                curMach = config.MIGRATION_MACHINES[self.conts[cont]["location"]]

                cur_cores = int(self.conts[cont]["cpu_cores"])
                max_cores = config.MIGRATION_MACHINES[self.conts[cont]["location"]]["cpu"]

                if self.conts[cont]["status"] == "frozen":
                    resume_thresh = thresh * (1 - config.SCALEUP_THRESH)
                    current_host_carbon = float(config.getCarbonIntensity())
                    last_cpu = float(self.conts[cont].get("freeze_last_cpu", 0.0))
                    last_joules = float(self.conts[cont].get("freeze_last_joules", 0.0))
                    freeze_cycles = int(self.conts[cont].get("freeze_cycles", 0))

                    # Use the last measured interval before freeze as the load basis.
                    last_energy_kwh = max(0.0, last_joules / 1000.0)
                    cpu_factor = max(0.25, min(1.0, last_cpu / 100.0))
                    projected_energy_kwh = last_energy_kwh * cpu_factor
                    projected_carbon = current_host_carbon * projected_energy_kwh

                    print(
                        f"[{cont}] FROZEN CHECK: projected carbon {projected_carbon:.4f}, "
                        f"resume threshold {resume_thresh:.4f}"
                    )

                    if freeze_cycles >= config.MAX_FROZEN_CYCLES:
                        print(f"[{cont}] Frozen for {freeze_cycles} cycles - RESUME")
                        self.resume_container(cont)
                    elif projected_carbon < resume_thresh:
                        print(f"[{cont}] Carbon improved - RESUME")
                        self.resume_container(cont)
                    else:
                        next_cycles = freeze_cycles + 1
                        print(f"[{cont}] Keeping container frozen (cycle {next_cycles}/{config.MAX_FROZEN_CYCLES})")
                        self.update_record_field(cont, "freeze_cycles", next_cycles)
                    continue

                # True means scaling is possible on the current host.
                scale_up = (cur_cores < max_cores)

                if nextSmaller(curMach["host"]):
                    next_smaller_cores = config.MIGRATION_MACHINES[nextSmaller(curMach["host"])]["cpu"]

                    # DONT SCALE DOWN IF YOU'LL SCALE TO BELOW THE RESOURCES AT A SMALLER MACHINE; DONT SCALE TO 0
                    if (int(cur_cores * 0.75) <= next_smaller_cores) or int(cur_cores * 0.75) == 0:
                        scale_down = False  # No point scaling - smaller host would be better
                    else: 
                        scale_down = True  # Scaling down is sensible at this host
                else:
                    next_smaller_cores = "-1"
                    # No smaller host exists, only scale if we won't hit 0
                    if int(cur_cores * 0.75) == 0:
                        scale_down = False
                    else:
                        scale_down = True
                
                
                # SCENARIO 1: Container using all CPU and carbon is LOW
                # Action: Try scaling up FIRST, then migrate to a BIGGER host
                if cpu == curMach["cpu"]*100 and carb < thresh:
                    print(f"[{cont}] SCENARIO 1: CPU maxed at {cpu}% but carbon {carb:.2f} < {thresh:.2f}")
                    
                    if scale_up:
                        print(f"[{cont}] └─ Attempt 1: Vertical scale-up")
                        self.scale_up(cont, cur_cores)
                    else:
                        target = nextBigger(curMach["host"])
                        if target:
                            print(f"[{cont}] └─ Attempt 2: Migrating to larger host: {target}")
                            self.migrate_send(cont, target)
                        else:
                            print(f"[{cont}] └─ No larger host available - staying (carbon is low anyway)")
                            with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
                                stub = records_pb2_grpc.RecordsStub(c)
                                resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="status", setts="running"))
                    continue

                # SCENARIO 2: Carbon EXCEEDS threshold, REDUCTION NEEDED
                # Action: FIRST scale DOWN, SECOND migrate to SMALLER host, LAST suspend
                elif carb > thresh:
                    print(f"[{cont}] SCENARIO 2: Carbon {carb:.2f} > threshold {thresh:.2f}")
                    
                    if scale_down:
                        print(f"[{cont}] └─ Attempt 1: Vertical scale-down")
                        self.scale_down(cont, cur_cores)
                        continue
                    
                    target = nextSmaller(curMach["host"])
                    if target:
                        print(f"[{cont}] └─ Attempt 2: Migrate to smaller host {target}")
                        self.migrate_send(cont, target)
                    else:
                        print(f"[{cont}] └─ Attempt 3: NO SCALING/MIGRATION OPTIONS - SUSPENDING with lxc-freeze")
                        self.suspend_container(cont)
                    pass
                
                # SCENARIO 3: Container is running normally, nothing to do
                else:
                    print(f"[{cont}] SCENARIO 3: Normal - Carbon {carb:.2f} is acceptable")
                    with grpc.insecure_channel("localhost:" + config.RECORD_PORT) as c:
                        stub = records_pb2_grpc.RecordsStub(c)
                        resp = stub.Update(records_pb2.UpdateRequest(name=cont, value="status", setts="running"))
                pass

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
        frozen_state["freeze_cycles"] = 0
        frozen_state["status"] = "frozen"
        current = dict(frozen_state.get("current", {}))
        current["carbon"] = 0.0
        current["joules"] = 0.0
        current["cpu"] = 0.0
        frozen_state["current"] = current

        # Update records to reflect frozen status.
        self.set_container_state(cont, frozen_state)
        
        print(f"[{cont}] Container is now FROZEN")

    def resume_container(self, cont):
        command = ["lxc-unfreeze", "-n", str(cont)]
        subprocess.Popen(command).communicate()
        
        # Update records to reflect running status
        self.update_record_field(cont, "status", "running")
        self.update_record_field(cont, "freeze_cycles", 0)
        
        print(f"[{cont}] Container is now RUNNIN")

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
        new_cpu = max(1, int(currentCpu * 1.25))
        command = ["lxc-cgroup", "-n", str(cont), "cpuset.cpus", "0-"+str(new_cpu - 1)]
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
        new_cpu = max(1, int(currentCpu * 0.75))
        command = ["lxc-cgroup", "-n", str(cont), "cpuset.cpus", "0-"+str(new_cpu - 1)]
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
