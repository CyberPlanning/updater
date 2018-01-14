#!/bin/python3
# coding: utf-8

import argparse
from icalendar import Calendar
import urllib.request
import sys

def parse_args():
    """Arguments parsing."""
    parser = argparse.ArgumentParser(description='Basic instruction parser')

    parser.add_argument('input',
                        type=str,
                        help='ICS file')

    args = parser.parse_args()

    return args

if __name__ == '__main__':

    # Arguments parsing
    args = parse_args()

    # Load config
    input_file = args.input

    cal = None
    if input_file.startswith('http'):
        ics_file = urllib.request.urlopen(input_file)
        cal = Calendar.from_ical(ics_file.read())
    else:
        with open(input_file, 'r') as ics_file:
            try:
                cal = Calendar.from_ical(ics_file.read())
            except ValueError as e:
                print("[!] Input file is not an ICalendar file")
                sys.exit(1)

    vevents = cal.walk("VEVENT")

    count = len(vevents)
    dates = [i["DTSTART"].dt for i in vevents]
    minDate = min(*dates)
    maxDate = max(*dates)

    print("Calendar %s" % input_file)
    print("Events count %d" % count)
    print("Events from %s" % minDate)
    print("Events to %s" % maxDate)
