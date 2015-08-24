import os
import serial
import time
baud = 115200
ser = serial.Serial('COM5', baud, timeout=30)

data = bytearray()
size = 10000

start = time.time()
for ii in range(size):
    line = ser.read()
    if not line:
        break
    else:
        data += line
end = time.time()

elapsed = end - start

fprefix = 'sample_data_'
fext = '.dat'
fsuffix = 1
fname = None

while not fname:
    testname = fprefix + str(fsuffix) + fext
    if os.path.isfile(testname):
        fsuffix += 1
    else:
        fname = testname
        
with open(fname, 'w+b') as f:
    f.write(data)
    
with open('sample_data.log', 'a+') as f:
    f.write(fname + ': ' + str(size) + ' bytes in ' + str(elapsed) + 
            ' seconds.\n')
    
print(str(size) + ' bytes in ' + str(elapsed) + ' seconds.')