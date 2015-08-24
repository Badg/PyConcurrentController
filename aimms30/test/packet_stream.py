import sys
sys.path.append('../../')
import aimms30
import serial
from collections import deque
from collections import ChainMap
from collections import OrderedDict
from threading import Thread
from threading import Event
from queue import Queue
import os
import json


checksum_warning = \
'''############ DROPPED BAD PACKET #########################
#########################################################
#########################################################
#########################################################
#########################################################
#########################################################
#########################################################'''


def listen(connection):
    '''  Listens on a connection using connection.read(), returning the
    first read byte. Assumes the connection.read() will wait for traffic
    (potentially with a timeout).
    '''
    bite = connection.read()
    # Make sure it actually returned something
    # This might be dangerous
    if not bite:
        return None
    else:
        return bite
    
    
def listen_forever(connection, bffr, exit_flag):
    ''' Calls listen() indefinitely, appending the recorded bytes into 
    the specified buffer. 
    '''
    try:
        while not exit_flag.is_set():
            bite = listen(connection)
            if bite != None:
                bffr.append(bite)
    except Exception as e:
        exit_flag.set()
        raise e
            
            
def parse(stream):
    ''' Processes the stream, returning the resulting object.
    '''        
    # This will align the stream. Design decision: check for parity
    # each iteration.
    return aimms30.Packet.from_stream(stream)
    

def parse_forever(stream, q, exit_flag, stream_buffer=500):
    ''' Parses data in stream forever, placing the resulting objects in
    the q. Waits for the stream to buffer to stream_buffer bytes before
    parsing.
    '''
    try:
        while not exit_flag.is_set():
            # Stall for time while the buffer builds up
            while len(bffr) > stream_buffer:
                try:
                    packet = parse(stream)
                # If the packet is too small, break out.
                except aimms30.PacketSizeError:
                    break
                # Catch bad checksums and delete the header. This
                # forces the stream to realign.
                except aimms30.ChecksumMismatch:
                    print(checksum_warning)
                    del stream[0:5]
                    break
                q.put_nowait(packet)
    except Exception as e:
        exit_flag.set()
        raise e
            
            
def dump(filename, obj):
    ''' Appends a string to the supplied file and adds a newline.
    '''
    s = json.dumps(obj)
    with open(filename, 'a+') as f:
        f.write(s)
        f.write('\n')
        

def dump_forever(filename, q, exit_flag):
    ''' Listens to a queue, calling dump on every string added there.
    '''
    try:
        while not exit_flag.is_set():
            obj = q.get()
            dump(filename, obj)
    except Exception as e:
        exit_flag.set()
        raise e


########################################################################

# Now create the serial interface and buffer. Might want to change some of 
# these fiddlybits to arguments passed to __main__
baud = 115200
ser = serial.Serial('COM5', baud, timeout=30)
# This is how big the parser wants the buffer to be before it parses.
bffr_size = 500

# Create the buffer and the queues and the exit_flag
bffr = aimms30.utils.SliceDeque()
# bffr = bytearray()
record_q = Queue()
obj_q = Queue()
exit_flag = Event()
# These aren't being used when doing state.update(newstate)
# most_recent_met = deque(maxsize=1)
# most_recent_position = deque(maxsize=1)
most_recent_state = OrderedDict()

########################################################################

# Now let's figure out what to call the output file.
fprefix = 'sample_data_'
fext = '.txt'
fsuffix = 1
fname = None
while not fname:
    testname = fprefix + str(fsuffix) + fext
    if os.path.isfile(testname):
        fsuffix += 1
    else:
        fname = testname
# Now we have an output filename.

########################################################################

# Create a serial listener.
listener = Thread(target=listen_forever, name='listener', 
                  args=(ser, bffr, exit_flag), daemon=True)
# Create a parser.
parser = Thread(target=parse_forever, name='parser', 
                args=(bffr, obj_q, exit_flag, bffr_size), daemon=True)
# Create a recorder.
recorder = Thread(target=dump_forever, name='recorder', 
                  args=(fname, record_q, exit_flag), daemon=True)

# Start serial collection.
listener.start()
# Start recording.
parser.start()
# Start recording.
recorder.start()

########################################################################

# Now we command all the threads.
try:
    while True:
        obj = obj_q.get(timeout=30)
        record_q.put(obj)
        # Update the state dict
        most_recent_state.update(obj)
        most_recent_state.update({'_type': 'state'})
        
        s = json.dumps(most_recent_state, indent=4)
        print(s)
except:
    exit_flag.set()
    #listener.join(5)
    #parser.join(5)
    #recorder.join(5)
    raise
        
        
# record_q.put_nowait(item)