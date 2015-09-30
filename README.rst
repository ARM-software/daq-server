DAQ Server
==========

This a server that provides remote access to a `National Instruments DAQ`_ (data
acquisition device) for power measurement.  National Instruments provide DAQ
drivers only for Windows and for very specific (old) Linux kernels. This package
allows DAQs to be usable from other operating systems. 

The idea is that the DAQ is connected to a machine running an OS for which
drivers are available; that machine is also running the server component of this
package. A program or a script running on a different OS can then use the client
part of this package to configure and collect measurements from that DAQ.


Installation
------------

::

        sudo -H pip install daqpower


Usage
-----

Please refer to `DAQ setup documentation <http://pythonhosted.org/wlauto/daq_device_setup.html>`_
for WA.

.. note:: This package was previously distributed as part of `ARM Workload
          Automation`_.


.. _National Instruments DAQ: http://www.ni.com/data-acquisition/
.. _ARM Workload Automation: https://github.com/ARM-software/workload-automation
