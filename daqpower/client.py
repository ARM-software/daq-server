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
import xmlrpc.client


if __name__ == '__main__':  # for debugging
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from daqpower.log import start_logging
from daqpower.config import get_config_parser


__all__ = ['DaqClient']

class DaqClient(xmlrpc.client.ServerProxy):
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
            filename = os.path.join(output_directory, port_file)
            with open(filename, 'w') as fout:
                fout.write(self.pull(port_file))


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
