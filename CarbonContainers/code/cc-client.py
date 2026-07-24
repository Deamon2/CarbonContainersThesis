import argparse
import grpc
import front_pb2
import front_pb2_grpc

IP = "localhost"

PORT = 1994

def do_register(name, pol, thresh, status):
   
    with grpc.insecure_channel(str(IP) + ":" + str(PORT)) as c:
        stub = front_pb2_grpc.FrontStub(c)
        # updateResp = stub.Update(order_pb2.UpdateRequest(number=str(number), name=stock, type=buySell, quantity=quantity))
        resp = stub.Register(front_pb2.RegisterRequest(name=name,policy=pol,thresh=thresh,status=status))

def do_deregister(name):
    print("DEGREG")
    with grpc.insecure_channel(str(IP) + ":" + str(PORT)) as c:
        stub = front_pb2_grpc.FrontStub(c)
        # updateResp = stub.Update(order_pb2.UpdateRequest(number=str(number), name=stock, type=buySell, quantity=quantity))
        resp = stub.Deregister(front_pb2.DeregisterRequest(name=name))
        pass


def do_start(name):
    with grpc.insecure_channel(str(IP) + ":" + str(PORT)) as c:
        stub = front_pb2_grpc.FrontStub(c)
        resp = stub.Start(front_pb2.StartRequest(name=name))


def do_stop(name):
    with grpc.insecure_channel(str(IP) + ":" + str(PORT)) as c:
        stub = front_pb2_grpc.FrontStub(c)
        resp = stub.Stop(front_pb2.StopRequest(name=name))


def do_status(name):
    with grpc.insecure_channel(str(IP) + ":" + str(PORT)) as c:
        stub = front_pb2_grpc.FrontStub(c)
        resp = stub.Status(front_pb2.StatusRequest(name=name))
    
    print(resp.name)
    print(resp.status)


def parse_args():
    parser = argparse.ArgumentParser(description="Front client")
    parser.add_argument("--name", help="Name des Containers")
    parser.add_argument("--thresh", help="Threshold Wert")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.name and args.thresh:
        do_register(args.name, "thresh", args.thresh, "running")
    else:
        do_register("cont1", "thresh", "0.1", "running")
        do_register("cont2", "thresh", "0.1", "running")
        do_register("cont3", "thresh", "0.1", "running")
    
    # do_deregister("cont1")
    # do_start("cont1")
    # do_stop("cont1")

    # do_status("cont1")
    pass
