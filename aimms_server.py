import argparse
import aimms30

parser = argparse.ArgumentParser()
parser.add_argument('serial', help='Which serial port to use.')
parser.add_argument('http', type=int, help='Which http port to use.')
parser.add_argument('-l', '--log', help='Log data to file.', action='store_true')
parser.add_argument('-d', '--debug', help='Show realtime data in console.',
                    action='store_true')

args = parser.parse_args()

aimms = aimms30.UAVMaster(aimms_port = args.serial,
                          http_port = args.http,
                          record_to_file = args.log,
                          print_to_terminal = args.debug)
aimms.run()