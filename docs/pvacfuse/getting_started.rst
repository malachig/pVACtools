.. image:: ../images/pVACfuse_logo_trans-bg_sm_v4b.png
    :align: right
    :alt: pVACfuse logo

Getting Started
---------------

pVACfuse provides a set of example data to show the expected input and output files. You can download the data set by running the ``pvacfuse download_example_data`` :ref:`command <pvacfuse_example_data>`.

The example data output can be reproduced by running the following command:

.. code-block:: none

   pvacfuse run \
   <example_data_dir>/fusions.bedpe.annot \
   Test \
   HLA-A*29:02 \
   NetMHC \
   <output_dir> \
   -e 9 \
   --top-score-metric=lowest --keep-tmp-files

A detailed description of all command options can be found on the :ref:`Usage <pvacfuse_run>` page.