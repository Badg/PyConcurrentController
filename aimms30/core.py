''' Should there be an automatic restmaker that converts the methods in 
each of these to RESTful API endpoints? That could handle the whole of 
the server code, too.

Use dir() to list attr and getattr + callable() to figure if functions.

# This generates a list of callable items in an instance of class a
[it for it in dir(a) if callable(getattr(a, it))]
# This excludes anything defined for a standard object
[it for it in dir(a) if callable(getattr(a, it)) and it not in dir(object)]
'''
import serial
from collections import deque
from collections import ChainMap
from collections import OrderedDict
from threading import Thread
from threading import Event
from queue import Queue
from queue import Empty
from queue import Full
import os
import json
from .aimms30 import Packet as AimmsPacket
from .utils import PacketSizeError
from .utils import ChecksumMismatch
from .utils import ParsingError
from .utils import SliceDeque
from .utils import MinimumLoopDelay
from .utils import RestfulDictHandler
from .utils import QuietRestfulDictHandler
from .utils import TestHandler
from .utils import ThreadedStatefulSocketServer
from abc import ABCMeta
from abc import abstractmethod
import http.server
import socketserver
import time


checksum_warning = \
'''############ DROPPED BAD PACKET #########################
#########################################################
#########################################################
#########################################################
#########################################################
#########################################################
#########################################################'''


class ThreadMonster():
    def __init__(self, create_master=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.exit_flag = Event()
        
        self._threads = {}
        if create_master:
            self.add_thread(self.my_captain, 'master')
        
    def __enter__(self):
        self.start()
        for thread in self.threads.values():
            thread.start()
        self.on_start()
        return self
        
    def __exit__(self, exception_type, exception_value, traceback):
        # Make sure that even if a badly-behaving subclass does not call
        # super(), we still kill the thread.
        self.exit_flag.set()
        self.stop()
        
    def add_thread(self, task, name, no_faster_than, *args, **kwargs):
        # This will memoize the task and insert it into a more clever callable
        def target():
            self.do_forever(task, no_faster_than, *args, **kwargs)
        # Create a thread for the memoized forever task
        self._threads[name] = \
                Thread(target=target, name=name, args=(), daemon=True)
        
    @property
    def threads(self):
        return self._threads
        
    def my_captain(self):
        ''' Fallback for super() calls to support multiple inheritance.
        '''
        pass
        
    def do_forever(self, task, no_faster_than, *args, **kwargs):
        ''' Manages exit flags and stuff while performing a task 
        indefinitely.
        '''
        try:
            while not self.exit_flag.is_set():
                with MinimumLoopDelay(no_faster_than):
                    task(*args, **kwargs)
        except:
            self.exit_flag.set()
            raise
            
    def stop(self):
        self.exit_flag.set()
        
    def start(self):
        ''' Catch any super() invocations.
        Runs BEFORE threads are started.
        '''
        pass
        
    def on_start(self):
        ''' Catch any super() invocations.
        Runs AFTER threads are started.
        '''
        pass


class FileRecorder(ThreadMonster):
    def __init__(self, filename, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.filename = filename
        self._file_q = Queue()
        self.add_thread(task=self.dump, name='file_recorder', 
                        no_faster_than=.001)
        self._f = None
    
    def dump(self):
        ''' Appends a string to the supplied file and adds a newline.
        '''
        # If there's an item on the queue, grab it and execute; otherwise nvm
        try:
            obj = self._file_q.get_nowait()
        except Empty:
            return
            
        # Open, if it hasn't been opened yet.
        if not self._f:
            self._f = open(self.filename, 'a+')
        
        s = json.dumps(obj)
        self._f.write(s)
        self._f.write('\n')
        
    def __exit__(self, *args, **kwargs):
        # Close our file, then call super.
        if self._f:
            self._f.close()
        # Reset state, regardless (tiny performance hit; reliability assurance)
        self._f = None
        super().__exit__(*args, **kwargs)
            
    def schedule_object(self, obj):
        ''' Schedules an object to be recorded to the file. Threadsafe.
        '''
        self._file_q.put_nowait(obj)
        

class SerialListener(ThreadMonster):
    def __init__(self, port, baud, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sets (ex: self.COM5_ser) to be the serial connection
        self.connection = serial.Serial()
        self.connection.baudrate = baud
        self.connection.port = port
        self.connection.timeout = 0
        # Sets (ex: self.COM5_buffer) to be a slicedeque
        self.buffer = SliceDeque()
        self.add_thread(task=self.listen, name='serial_listener', 
                        no_faster_than=.001)
        
    def stop(self):
        self.connection.close()
        super().stop()
        
    def start(self):
        self.connection.open()
        super().start()
     
    def listen(self):
        '''  Listens on a connection using connection.read(), returning the
        first read byte. Assumes the connection.read() will wait for traffic
        (potentially with a timeout).
        '''
        bite = self.connection.read()
        # Make sure it actually returned something
        # This might be dangerous
        if not bite:
            return None
        else:
            self.buffer.append(bite)
                

class PacketDigester(ThreadMonster):
    def __init__(self, packet_generator, input_stream, swallow_trigger=500, 
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.input_stream = input_stream
        self.swallow_trigger = swallow_trigger
        self.packet_generator = packet_generator
        self._output_q = Queue()
        
        self.add_thread(task=self.parse, name='packet_digester', 
                        no_faster_than=.01)
        
    def parse(self):
        ''' Parses data in stream forever, placing the resulting objects in
        the q. Waits for the stream to buffer to stream_buffer bytes before
        parsing.
        '''
        if len(self.input_stream) > self.swallow_trigger:
            try:
                packet = self.packet_generator(self.input_stream)
                self._output_q.put_nowait(packet)
            # If the packet is too small, break out.
            except PacketSizeError:
                return
            # Catch bad checksums and delete the header. This
            # forces the stream to realign.
            except ChecksumMismatch:
                print(checksum_warning)
                del self.input_stream[0]
                return
            # except Full:
            
    def pop(self):
        ''' Returns and removes a packet. Threadsafe. Returns None if 
        no packet is available.
        '''
        try:
            return self._output_q.get_nowait()
        except Empty:
            return None
            
            
class SerialDigester(SerialListener, PacketDigester):
    ''' Glue class to generate packet objects from a serial port.
    '''
    def __init__(self, *args, **kwargs):
        super().__init__(input_stream=None, *args, **kwargs)
        # This glues together the seriallistener and packetdigester
        self.input_stream = self.buffer
        
        
class StatusServer(ThreadMonster):
    def __init__(self, port, state_vector, verbose=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.port = port
        self.state_vector = state_vector
        # self.handler = TestHandler
        if verbose:
            self.handler = RestfulDictHandler
        else:
            self.handler = QuietRestfulDictHandler
            
        self.server = ThreadedStatefulSocketServer(self.state_vector, 
            ('', port), self.handler)
        self._threads['status_server'] = \
                Thread(target=self.server.serve_forever, name='status_server', 
                       args=(), daemon=True)

    def stop(self):
        self.server.shutdown()
        super().stop()
    
    
class UAVMaster(ThreadMonster):
    def __init__(self, aimms_port, http_port, record_to_file=True, 
                 print_to_terminal=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.record = record_to_file
        self.print_to_terminal = print_to_terminal
        
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
                
        # Create a state dictionary
        self.state = {}
        
        # Create the various UAV components
        self.aimms = SerialDigester(port=aimms_port, baud=115200,
                                    packet_generator=AimmsPacket.from_stream)
        self.recorder = FileRecorder(filename=fname)
        # Link all of the exit flags so that one exit will induce all others
        self.aimms.exit_flag = self.exit_flag
        self.recorder.exit_flag = self.exit_flag
        # Add whatever is needed to the state dictionary
        self.state['aimms'] = OrderedDict()
        
        # Finally add the server
        self.server = StatusServer(http_port, state_vector=self.state, 
                                   verbose=print_to_terminal)
        
    def run(self):
        with self, self.aimms, self.recorder, self.server:
                while True:
                    with MinimumLoopDelay(.01):
                        # Get the packet from aimms and possibly record it
                        obj = self.aimms.pop()
                        if obj:
                            # Add secondary unix timestamp
                            obj.update({'timestamp': time.time()})
                            if self.record:
                                self.recorder.schedule_object(obj)
                            # Update state and print it
                            self.state['aimms'].update(obj)
                            self.state['aimms'].update({'_type': 'state'})
                            if self.print_to_terminal:
                                s = json.dumps(self.state['aimms'], indent=4)
                                print(s)
                
    def stop(self):
        self.aimms.stop()
        self.recorder.stop()
        super().stop()