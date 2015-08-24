import sys
sys.path.append('../../')
import aimms30
from collections import deque

# Note: 7 is misaligned.
with open('putty.log', 'rb') as f:
    sample = f.read()
    
d = aimms30.utils.SliceDeque()
for bite in sample:
    d.append(bite.to_bytes(1, 'big'))
   
# This will align the stream.
while True:
    try:
        first = aimms30.Packet(d)
        break
    except aimms30.ParsingError:
        del d[0]
        
# Now, let's start dealing with it.
packets = deque()
# Process all packets in the buffer.
while True:
    try:
        packets.append(aimms30.Packet.from_stream(d))
    # Now, if we get a packet size error, we're at the end of the buffer.
    except aimms30.PacketSizeError:
        break
        
mets = [p for p in packets if p.packet_type == 'met']
states = [p for p in packets if p.packet_type == 'position']
        
packet_types = [p.packet_type for p in packets]
print('\n')
print('Met: ' + str(packet_types.count('met')))
print('Position: ' + str(packet_types.count('position')))
print('\n')

print('Met:')
for key, value in mets[len(mets) - 3].items():
    print('  ' + key + ': ' + str(value))
print('\n')
print('Position:')
for key, value in states[len(states) - 3].items():
    print('  ' + key + ': ' + str(value))