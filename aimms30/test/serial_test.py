import serial
baud = 57600
ser = serial.Serial('COM4', baud, timeout=5)

while True:
    line = ser.readline()
    if not line:
        break
    else:
        print(line)