#!/usr/bin/env python
# coding: utf8
#
# Python 3 script : it feeds the Mongo database with current data get from the
# URLs given in the JSON file as parameters. It downloads an iCalendar file
# which is parsed to shape the database.

import urllib.request
import re
from icalendar import Calendar
from pymongo import MongoClient
import json


def format_data(calendar, planning_parser):
    ret = []
    vevents = calendar.walk("VEVENT")
    for vevent in vevents:
        planning_parser.parse(vevent)
        appointment = {
            "title": planning_parser.get_title(),
            "start_date": planning_parser.get_start_date(),
            "end_date": planning_parser.get_end_date(),
            "classrooms": planning_parser.get_classrooms(),
            "groups": planning_parser.get_groups(),
            "teachers": planning_parser.get_teachers(),
            "undetermined_description_items": planning_parser.get_undetermined_description_items(),
            "event_id": planning_parser.get_event_id()
        }
        ret.append(appointment)
    return ret


def parse_and_insert_database(data, db):
    pass


class CalendarParser:
    """
    A parser with a main method parse() used to get the attributes from an event in the Calendar.

    The get methods must be used after parsing.
    """

    def __init__(self, teachers_patterns, groups_patterns, description_delimiter):
        """
        Instanciate the object with different parameters.

        :param teachers_patterns: the string patterns used to identify a teacher
        :param groups_patterns: the string patterns used to identify a group
        :param description_delimiter: the delimiter used to split the items in the calendar's
        description field
        """

        self._teachers_patterns = teachers_patterns
        self._groups_patterns = groups_patterns
        self._delimiter = description_delimiter

        self._title = ""
        self._start_date = None
        self._end_date = None
        self._classrooms = ""
        self._teachers = []
        self._groups = []
        self._undetermined_description_items = []
        self._event_id = ""

    def parse(self, vevent):
        """Return None.

        This method parses the description given during instanciation and feeds the attributes as
        followed :
        - title : str
        - start_date : datetime
        - end_date : datetime
        - last_modified : datetime
        - classrooms : list of string
        - teachers : list of string
        - groups : list of string
        - undetermined_description_items : list of string
        - event_id : string
        """

        self._title = str(vevent["SUMMARY"])
        self._start_date = vevent["DTSTART"].dt
        self._end_date = vevent["DTEND"].dt
        self._classrooms = []
        for elem in vevent["LOCATION"].split(self._delimiter):
            if len(elem) != 0:
                self._classrooms.append(elem)
        self._teachers = []
        self._groups = []
        self._undetermined_description_items = []
        for elem in vevent["DESCRIPTION"].split(self._delimiter):
            found = False
            for pattern in self._teachers_patterns:
                if re.match(pattern, elem) is not None:
                    self._teachers.append(elem)
                    found = True
                    break
            if not found:
                for pattern in self._groups_patterns:
                    if re.match(pattern, elem) is not None:
                        self._groups.append(elem)
                        found = True
                        break
            if not found:
                self._undetermined_description_items.append(elem)
        self._event_id = str(vevent["UID"])

    def get_title(self):
        """Return the title string found in the event after parsing."""
        return self._title

    def get_start_date(self):
        """Return the starting date found in the event after parsing."""
        return self._start_date

    def get_end_date(self):
        """Return the ending date found in the event after parsing."""
        return self._end_date

    def get_classrooms(self):
        """Return the list of the classrooms found in the event after parsing."""
        return self._classrooms

    def get_groups(self):
        """Return the list of the groups found in the description field after parsing."""
        return self._groups

    def get_teachers(self):
        """Return the list of the teachers found in the description field after parsing."""
        return self._teachers

    def get_undetermined_description_items(self):
        """
        Return the list of the undetermined items found in the description field after
        parsing.
        """
        return self._undetermined_description_items

    def get_event_id(self):
        """
        Return the event id string found in the uid field after parsing.
        """
        return self._event_id


if __name__ == '__main__':
    PARAMS_FILENAME = "params.json"

    params_file = open(PARAMS_FILENAME, 'r')
    params = json.load(params_file)

    client = MongoClient()
    db_name = params["database"]["name"]
    db = client[db_name]

    for branch in params["branches"]:
        collec_name = db_name + "_" + branch["name"]
        print("Collection " + collec_name)
        data_list = []
        parser = CalendarParser(branch["teachers_patterns"], branch["groups_patterns"],
                                branch["delimiter"])
        for group in branch["groups"]:
            i = 1
            for address in group["addresses"]:
                print("Downloading address " + str(i) + " in group " + group["name"])
                ics_file = urllib.request.urlopen(address)
                cal = Calendar.from_ical(ics_file.read())
                print("Removing duplicate data of group " + group["name"])
                for item in format_data(cal, parser):
                    found = False
                    for data in data_list:
                        if item["event_id"] == data["event_id"]:
                            found = True
                            break
                    if found is False:
                        data_list.append(item)
                i += 1

        # parse_and_insert_database(data, db)

        print("Removing data list from collection " + collec_name)
        db[collec_name].delete_many({})
        print("Adding data to collection " + collec_name)
        db[collec_name].insert_many(data_list)
