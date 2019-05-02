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

From PyPI::

        sudo -H pip install daqpower

The latest developement version from GitHub::

    git clone git@github.com:ARM-software/daq-server.git daq-server
    cd daq-server
    sudo -H python setup.py install


Usage
-----

Please refer to `DAQ Server Guide <https://daq-server.readthedocs.io/en/latest/>`_.

License
-------

This package is distributed under `Apache v2.0 License <http://www.apache.org/licenses/LICENSE-2.0>`_.


Feedback, Contrubutions and Support
-----------------------------------

- Please use the GitHub Issue Tracker associated with this repository for
  feedback.
- ARM licensees may contact ARM directly via their partner managers.
- We welcome code contributions via GitHub Pull requests. Please try to
  stick to the style in the rest of the code for your contributions.


.. note:: This package was previously distributed as part of `ARM Workload
          Automation`_.

.. _National Instruments DAQ: http://www.ni.com/data-acquisition/
.. _ARM Workload Automation: https://github.com/ARM-software/workload-automation
