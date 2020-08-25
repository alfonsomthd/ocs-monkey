#!/usr/bin/env python3
"""Starts the randomized workload generator."""

# pylint: disable=duplicate-code
# Above disable doesn't work, so below imports are non-alpha to avoid the
# warning
# https://github.com/PyCQA/pylint/issues/214
import logging
import argparse
import os
import random
import time

import event
import log_gather
import log_gather_ocs
import osio
import kube
import util

CLI_ARGS: argparse.Namespace
RUN_ID = random.randrange(999999999)

def set_health(healthy: bool) -> None:
    """Sets the state of the health indicator file."""
    filename = "/tmp/healthy_runner"
    if healthy:
        logging.info("creating health file: %s", filename)
        file = os.open(filename, os.O_CREAT | os.O_WRONLY)
        os.close(file)
    else:
        logging.info("deleting health file: %s", filename)
        os.unlink(filename)

def main() -> None:
    """Run the workload."""
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--log-dir",
                        default=os.getcwd(),
                        type=str,
                        help="Path to use for log files")
    parser.add_argument("-m", "--accessmode",
                        default="ReadWriteOnce",
                        type=str, choices=["ReadWriteOnce", "ReadWriteMany"],
                        help="StorageClassName for the workload's PVCs")
    parser.add_argument("-n", "--namespace",
                        default="ocs-monkey",
                        type=str,
                        help="Namespace to use for the workload")
    parser.add_argument("--oc",
                        default="oc",
                        type=str,
                        help="Path/executable for the oc command")
    parser.add_argument("--ocs-namespace",
                        default="openshift-storage",
                        type=str,
                        help="Namespace where the OCS components are running")
    parser.add_argument("-s", "--storageclass",
                        default="ocs-storagecluster-ceph-rbd",
                        type=str,
                        help="StorageClassName for the workload's PVCs")
    parser.add_argument("-z", "--sleep-on-error",
                        action="store_true",
                        help="On error, sleep forever instead of exit")
    parser.add_argument("--osio-interarrival",
                        default=20,
                        type=float,
                        help="OSIO workload mean interrarival time (s)")
    parser.add_argument("--osio-lifetime",
                        default=3600,
                        type=float,
                        help="OSIO workload mean lifetime (s)")
    parser.add_argument("--osio-active-time",
                        default=300,
                        type=float,
                        help="OSIO workload mean active period (s)")
    parser.add_argument("--osio-idle-time",
                        default=60,
                        type=float,
                        help="OSIO workload mean idle period (s)")
    parser.add_argument("--osio-kernel-slots",
                        default=3,
                        type=int,
                        help="OSIO workload slots for kernel untar")
    parser.add_argument("--osio-kernel-untar",
                        default=10,
                        type=float,
                        help="OSIO workload kernel untar rate (#/hr)")
    parser.add_argument("--osio-kernel-rm",
                        default=10,
                        type=float,
                        help="OSIO workload kernel rm rate (#/hr)")
    parser.add_argument("--osio-image",
                        default="quay.io/ocsci/osio-workload",
                        type=str,
                        help="Container image for OSIO worker pods")
    parser.add_argument("-t", "--runtime",
                        default=7200,
                        type=int,
                        help="Run time in seconds")
    global CLI_ARGS  # pylint: disable=global-statement
    CLI_ARGS = parser.parse_args()

    log_dir = os.path.join(CLI_ARGS.log_dir, f'ocs-monkey-{RUN_ID}')
    util.setup_logging(log_dir)

    logging.info("starting execution-- run id: %d", RUN_ID)
    logging.info("program arguments: %s", CLI_ARGS)
    logging.info("log directory: %s", log_dir)

    # register log collector(s)
    log_gather.add(log_gather_ocs.OcsMustGather(CLI_ARGS.oc))
    log_gather.add(log_gather_ocs.MustGather(CLI_ARGS.oc))
    log_gather.add(log_gather_ocs.OcsImageVersions(CLI_ARGS.oc,
                                                   CLI_ARGS.ocs_namespace))

    kube.create_namespace(CLI_ARGS.namespace, existing_ok=True)

    if CLI_ARGS.sleep_on_error:
        set_health(True)

    dispatch = event.Dispatcher()
    dispatch.add(*osio.resume(CLI_ARGS.namespace))
    dispatch.add(osio.start(namespace=CLI_ARGS.namespace,
                            storage_class=CLI_ARGS.storageclass,
                            access_mode=CLI_ARGS.accessmode,
                            interarrival=CLI_ARGS.osio_interarrival,
                            lifetime=CLI_ARGS.osio_lifetime,
                            active=CLI_ARGS.osio_active_time,
                            idle=CLI_ARGS.osio_idle_time,
                            kernel_slots=CLI_ARGS.osio_kernel_slots,
                            kernel_untar=CLI_ARGS.osio_kernel_untar,
                            kernel_rm=CLI_ARGS.osio_kernel_rm,
                            workload_image=CLI_ARGS.osio_image))
    try:
        dispatch.run(runtime=CLI_ARGS.runtime)
    except osio.UnhealthyDeployment:
        if CLI_ARGS.sleep_on_error:
            set_health(False)
        logging.info("starting log collection")
        log_gather.gather(log_dir)
        logging.error("Controller stopped due to detected error")
        while CLI_ARGS.sleep_on_error:
            time.sleep(9999)
        raise

if __name__ == '__main__':
    main()
