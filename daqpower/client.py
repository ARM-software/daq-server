#    Copyright 2014-2015 ARM Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


# pylint: disable=E1101,E1103
import os
import logging
import sys
try:
    from xmlrpc.client import ServerProxy
except ImportError:
    # In python2 it was called xmlrpclib
    from xmlrpclib import ServerProxy


if __name__ == '__main__':  # for debugging
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from daqpower.log import start_logging
from daqpower.config import get_config_parser


__all__ = ['DaqClient']

class FileReceiver(object):
    """Context manager to receive a port file using the daq server's open/read/close protocol"""
    def __init__(self, daq_client, remote_file):
        self.daq_client = daq_client
        self.remote_file = remote_file
        self.port_descriptor = None

    def __enter__(self):
        self.port_descriptor = self.daq_client.open_port_file(self.remote_file)
        return self

    def __exit__(self, exc_type, value, traceback):
        self.daq_client.close_port_file(self.port_descriptor)

    def read(self, size):
        """Read size bytes from the file"""
        return self.daq_client.read_port_file(self.port_descriptor, size)


# Multiple inheritance with object is needed for python2, as ServerProxy is not
# a new-style class and inheritance with super() doesn't work out of the box.
class DaqClient(ServerProxy, object):
    """Interface with the remote DAQ server"""
    def __init__(self, host, port):
        self.logger = logging.getLogger('{}.{}'.format(__name__, self.__class__.__name__))
        server_uri = 'http://{}:{}'.format(host, port)
        super(DaqClient, self).__init__(server_uri)

    def get_data(self, output_directory):
        """Get all the port files after capturing"""
        port_files = self.list_port_files()
        if port_files == []:
            self.logger.warning('No ports were returned')
        for port_file in port_files:
            output_fname = os.path.join(output_directory, port_file)
            self.pull(port_file, output_fname)

    def pull(self, remote_file, local_file):
        """
        Download a remote port file from the server. You can use list_port_files() to get a list
        of valid remote_files
        """
        with FileReceiver(self, remote_file) as fin:
            with open(local_file, 'w') as fout:
                while True:
                    chunk = fin.read(1048576)
                    if not chunk:
                        break
                    fout.write(chunk)


def run_send_command():
    """Main entry point when running as a script -- should not be invoked form another module."""
    parser = get_config_parser()
    parser.add_argument('command')
    parser.add_argument('arguments', nargs='*')
    parser.add_argument('-o', '--output-directory', metavar='DIR', default='.',
                        help='Directory used to output data files (defaults to the current directory).')
    parser.add_argument('--verbose', help='Produce verobose output.', action='store_true',
                        default=False)
    args = parser.parse_args()
    if not args.device_config.labels:
        args.device_config.labels = ['PORT_{}'.format(i) for i in range(len(args.device_config.resistor_values))]

    if args.verbose:
        start_logging('DEBUG')
    else:
        start_logging('INFO', fmt='%(levelname)-8s %(message)s')

    daq_client = DaqClient(args.host, args.port)

    if args.command == 'configure':
        args.device_config.validate()
        result = daq_client.configure(args.device_config)
    elif args.command == 'get_data':
        daq_client.get_data(output_directory=args.output_directory)
        result = None
    else:
        result = daq_client.__getattr__(args.command)(*args.arguments)

    if result is None:
        print('Ok')
    else:
        print(result)


if __name__ == '__main__':
    run_send_command()
