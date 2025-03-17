#!/usr/bin/env python3

# Copyright (C) 2020 Canonical Ltd.

import nagios_plugin3


def load_alarm_list():
    """Load the cached status from disk, return it as a string"""
    alarm_list_path = "/var/lib/nagios/etcd-alarm-list.txt"

    with open(alarm_list_path, "r") as alarm_list_log:
        alarm_list = alarm_list_log.read()

    return alarm_list.strip()


def check_alarms():
    """Raise an error if the cached status contains any non-blank lines"""
    alarms = []
    alarm_list = load_alarm_list()
    for line in alarm_list.splitlines():
        line = line.strip()
        if line:
            alarms.append(line)
    if alarms:
        raise nagios_plugin3.CriticalError(" ".join(alarms))


def main():
    nagios_plugin3.try_check(check_alarms)
    print("OK - no active alarms")


if __name__ == "__main__":
    main()
