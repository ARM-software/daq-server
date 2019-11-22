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


# pylint: disable=E1101,W0613
from __future__ import division
import os
import sys
import argparse
import logging
import shutil
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta
try:
    from xmlrpc.server import SimpleXMLRPCServer
except ImportError:
    # In python2 it was packaged as SimpleXMLRPCServer
    from SimpleXMLRPCServer import SimpleXMLRPCServer


if __name__ == "__main__":  # for debugging
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from daqpower.log import start_logging
from daqpower.config import DeviceConfiguration
try:
    from daqpower.daq import DaqRunner, list_available_devices, CAN_ENUMERATE_DEVICES
    __import_error = None
except (ImportError, NotImplementedError) as e:
    # May be using debug mode.
    __import_error = e
    DaqRunner = None
    list_available_devices = lambda: ['Dev1']
    CAN_ENUMERATE_DEVICES = True


class ProtocolError(Exception):
    pass


class DummyDaqRunner(object):
    """Dummy stub used when running in debug mode."""

    num_rows = 200

    @property
    def number_of_ports(self):
        return self.config.number_of_ports

    def __init__(self, config, output_directory):
        self.logger = logging.getLogger('{}.{}'.format(__name__, self.__class__.__name__))
        self.logger.info('Creating runner with %s %s', config, output_directory)
        self.config = config
        self.output_directory = output_directory
        self.is_running = False

    def start(self):
        import csv, random
        self.logger.info('runner started')
        for i in range(self.config.number_of_ports):
            rows = [['power', 'voltage']] + [[random.gauss(1.0, 1.0), random.gauss(1.0, 0.1)]
                                             for _ in range(self.num_rows)]
            if sys.version_info[0] == 3:
                wfh = open(self.get_port_file_path(self.config.labels[i]), 'w', newline='')
            else:
                wfh = open(self.get_port_file_path(self.config.labels[i]), 'wb')

            try:
                writer = csv.writer(wfh)
                writer.writerows(rows)
            finally:
                wfh.close()

        self.is_running = True

    def stop(self):
        self.is_running = False
        self.logger.info('runner stopped')

    def get_port_file_path(self, port_id):
        if port_id not in self.config.labels:
            raise ValueError('Invalid port id: {}'.format(port_id))
        return os.path.join(self.output_directory, '{}.csv'.format(port_id))


class CleanupDirectoryThread(threading.Thread):
    """Cleanup old uncollected data files to recover disk space."""
    def __init__(self, base_output_directory, cleanup_period=24 * 60 * 60,
                 cleanup_after_days=5):
        super(CleanupDirectoryThread, self).__init__()
        self.logger = logging.getLogger('{}.{}'.format(__name__, self.__class__.__name__))
        self.daemon = True
        self.base_output_directory = base_output_directory
        self.cleanup_period = cleanup_period
        self.cleanup_threshold = timedelta(cleanup_after_days)
        self._stop_signal = threading.Event()

    def run(self):
        while not self._stop_signal.wait(timeout=self.cleanup_period):
            self.logger.info('Performing cleanup of the output directory...')
            current_time = datetime.now()
            base_directory = self.base_output_directory
            for entry in os.listdir(base_directory):
                entry_path = os.path.join(base_directory, entry)
                entry_ctime = datetime.fromtimestamp(os.path.getctime(entry_path))
                existence_time = current_time - entry_ctime
                if existence_time > self.cleanup_threshold:
                    self.logger.debug('Removing {} (existed for {})'.format(entry, existence_time))
                    shutil.rmtree(entry_path)
                else:
                    self.logger.debug('Keeping {} (existed for {})'.format(entry, existence_time))
            self.logger.debug('Cleanup complete.')

    def stop(self):
        self._stop_signal.set()
        self.join()


class OpenFileInfo(object):
    """Simple structure to track when each file was opened"""
    def __init__(self, port_file):
        self.port_file = port_file
        self.created = time.time()


class OpenFileTracker(object):
    """Track open file descriptors and close them if the transfer times out"""
    def __init__(self):
        self.logger = logging.getLogger('{}.{}'.format(__name__, self.__class__.__name__))
        self.opened_files = {}
        self.lock = threading.Lock()
        # Maximum transfer lifetime in seconds
        max_transfer_lifetime = 30 * 60
        self.terminate_timeout_thread = threading.Event()

        self.timeout_thread = threading.Thread(target=self.pulse,
                                               name='OpenFileTracker',
                                               args=(max_transfer_lifetime,))
        self.timeout_thread.daemon = True
        self.timeout_thread.start()

    def open(self, filename):
        """
        Open file and track when we did it. Return a descriptor to be used
        for reading and closing
        """
        port_file = open(filename)
        file_info = OpenFileInfo(port_file)
        port_descriptor = uuid.uuid4().hex
        with self.lock:
            self.opened_files[port_descriptor] = file_info

        return port_descriptor

    def read(self, descriptor, size):
        """Read from a file previously opened by self.open()"""
        try:
            with self.lock:
                port_file = self.opened_files[descriptor].port_file
                return port_file.read(size)
        except KeyError:
            raise ProtocolError('Unknown port descriptor {}'.format(descriptor))


    def close(self, descriptor):
        """Close a file previously opened by self.open()"""
        try:
            with self.lock:
                port_file = self.opened_files[descriptor].port_file
                port_file.close()
                del self.opened_files[descriptor]
        except KeyError:
            raise ProtocolError('Unknown port descriptor {}'.format(descriptor))

    def terminate(self):
        """Tear down this tracker and close all remaining open files"""
        self.logger.debug('Terminating timeout thread')
        self.terminate_timeout_thread.set()
        self.timeout_thread.join()
        for opened_file in self.opened_files.values():
            opened_file.port_file.close()

    def pulse(self, max_transfer_lifetime):
        """Close down any file tranfer sessions that have been open for too long."""
        poll_period = max_transfer_lifetime / 2
        while not self.terminate_timeout_thread.wait(timeout=poll_period):
            self.logger.debug('Checkig for timeout file transfers')
            current_time = time.time()
            expire_before = current_time - max_transfer_lifetime

            with self.lock:
                # Iterate over a copy of the self.opened_files to be able to
                # remove from the dictionary if needed
                for descriptor, opened_file in list(self.opened_files.items()):
                    if opened_file.created < expire_before:
                        self.logger.info('Transfer for file %s timed out',
                                         opened_file.port_file.name)
                        opened_file.port_file.close()
                        del self.opened_files[descriptor]


class DaqServer(object):
    """Interface between a DaqRunner and a remote client"""
    def __init__(self, base_output_directory):
        self.logger = logging.getLogger('{}.{}'.format(__name__, self.__class__.__name__))
        self.base_output_directory = os.path.abspath(base_output_directory)
        if os.path.isdir(self.base_output_directory):
            self.logger.info('Using output directory: %s', self.base_output_directory)
        else:
            self.logger.info('Creating new output directory: %s', self.base_output_directory)
            os.makedirs(self.base_output_directory)
        self.cleanup_directory_thread = CleanupDirectoryThread(self.base_output_directory)
        self.cleanup_directory_thread.start()
        self.runner = None
        self.opened_files = None
        self.output_directory = None
        self.labels = None

    def configure(self, config_kwargs):
        """Configure the DAQ"""
        if self.runner:
            message = 'Configuring a new session before previous session has been terminated.'
            self.logger.warning(message)
            if self.runner.is_running:
                self.runner.stop()
        config = DeviceConfiguration(**config_kwargs)
        config.validate()
        self.output_directory = self._create_output_directory()
        self.labels = config.labels
        self.logger.info('Writing port files to %s', self.output_directory)
        self.opened_files = OpenFileTracker()
        self.runner = DaqRunner(config, self.output_directory)

    def start(self):
        """Start capturing. configure() must have been called before"""
        self.logger.info('Start capturing')
        if self.runner:
            if not self.runner.is_running:
                self.runner.start()
            else:
                message = 'Calling start() before stop() has been called. Data up to this point will be lost.'
                self.logger.warning(message)
                self.runner.stop()
                self.runner.start()
        else:
            raise ProtocolError('Start called before a session has been configured.')

    def stop(self):
        """Stop capturing"""
        self.logger.info('Stop capturing')
        if self.runner:
            if self.runner.is_running:
                self.runner.stop()
            else:
                self.logger.warning('Attempting to stop() before start() was invoked.')
                self.runner.stop()
        else:
            raise ProtocolError('Stop called before a session has been configured.')

    def list_devices(self):  # pylint: disable=no-self-use
        """List all devices attached to the DAQ if it supports enumeration"""
        if not CAN_ENUMERATE_DEVICES:
            raise TypeError('Server does not support DAQ device enumeration')
        return list_available_devices()

    def list_ports(self):
        """
        List all the ports for the configured DAQ. You need to call
        configure() before being able to list ports
        """
        return self.labels

    def list_port_files(self):
        """List port files after a capturing session."""
        if not self.runner:
            raise ProtocolError('Attempting to list port files before session has been configured.')
        ports_with_files = []
        for port_id in self.labels:
            path = self._get_port_file_path(port_id)
            if os.path.isfile(path):
                ports_with_files.append(port_id)
        return ports_with_files

    def open_port_file(self, port_id):
        """
        Start transfer of a port file.  You can get a list of valid port_id by
        calling list_port_files.  The returned string is a descriptor that can
        be used with read_port_file() and close_port_file()

        """
        filename = self._get_port_file_path(port_id)
        try:
            return self.opened_files.open(filename)
        except FileNotFoundError:
            raise ValueError('File for port {} does not exist.'.format(port_id))
        except AttributeError:
            if not self.opened_files:
                raise ProtocolError('open_port_file called on an unconfigured session')
            raise

    def read_port_file(self, port_descriptor, size):
        """
        Read from a port file after it has been opened with open_port_file().
        size is the amount of bytes you want to read
        """
        if not self.opened_files:
            raise ProtocolError('read_port_file called on an unconfigured session')
        return self.opened_files.read(port_descriptor, size)

    def close_port_file(self, port_descriptor):
        """
        Close a port file opened by open_port_file(). After calling this, any
        call to read_port_file() for this port_descriptor will fail.
        """
        if not self.opened_files:
            raise ProtocolError('close_port_file called on an unconfigured session')
        self.opened_files.close(port_descriptor)

    def _get_port_file_path(self, port_id):
        if not self.runner:
            raise ProtocolError('Attepting to get port file path before session has been configured.')
        return self.runner.get_port_file_path(port_id)

    def close(self):
        """Close a session, stopping the DAQ and removing all temporary files"""
        if not self.runner:
            message = 'Attempting to close session before it has been configured.'
            self.logger.warning(message)
            return
        if self.runner.is_running:
            message = 'Terminating session before runner has been stopped.'
            self.logger.warning(message)
            self.runner.stop()
        self.runner = None
        self.opened_files.terminate()
        self.opened_files = None
        if self.output_directory and os.path.isdir(self.output_directory):
            shutil.rmtree(self.output_directory)
            self.output_directory = None
        self.logger.info('Session terminated.')

    def _create_output_directory(self):
        basename = datetime.now().strftime('%Y-%m-%d_%H%M%S%f')
        dirname = os.path.join(self.base_output_directory, basename)
        os.makedirs(dirname)
        return dirname

    def __del__(self):
        if self.runner:
            self.runner.stop()

    def __str__(self):
        return '({})'.format(self.base_output_directory)

    __repr__ = __str__


def run_server():
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--directory', help='Working directory', metavar='DIR',
                        default='daq_server_tmpfiles')
    parser.add_argument('-p', '--port', help='port the server will listen on.',
                        metavar='PORT', default=45677, type=int)
    parser.add_argument('-c', '--cleanup-after', type=int, default=5, metavar='DAYS',
                        help="""
                        Sever will perodically clean up data files that are older than the number of
                        days specfied by this parameter.
                        """)
    parser.add_argument('--cleanup-period', type=int, default=1, metavar='DAYS',
                        help='Specifies how ofte the server will attempt to clean up old files.')
    parser.add_argument('--debug', help='Run in debug mode (no DAQ connected).',
                        action='store_true', default=False)
    parser.add_argument('--verbose', help='Produce verobose output.', action='store_true',
                        default=False)
    args = parser.parse_args()

    if args.debug:
        global DaqRunner  # pylint: disable=W0603
        DaqRunner = DummyDaqRunner
    else:
        if not DaqRunner:
            raise __import_error  # pylint: disable=raising-bad-type
    if args.verbose or args.debug:
        start_logging('DEBUG',
                      '%(asctime)s %(name)-30s %(levelname)-7s: %(message)s')
    else:
        start_logging('INFO')

    # days to seconds
    cleanup_period = args.cleanup_period * 24 * 60 * 60

    daq_server = DaqServer(args.directory)
    logger = logging.getLogger(__name__)

    server = SimpleXMLRPCServer(('', args.port), allow_none=True)
    server.register_instance(daq_server)

    try:
        hostname = socket.gethostbyname(socket.gethostname())
    except socket.gaierror:
        hostname = 'localhost'
    logger.info('Listening on %s:%d', hostname, args.port)

    server.serve_forever()

if __name__ == "__main__":
    run_server()
