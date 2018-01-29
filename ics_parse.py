#!/usr/bin/env python
# coding: utf8
#
# Planning Updater, a Python 3 script.
# This updater updates the database according to different parameters, such as
# the frequency of the updates or the groups of a school branch.
# Technically, it feeds the Mongo database with current data get from the URIs
# given in the JSON file as parameters.
# It downloads iCalendar files, from the groups in the parameters, which is
# parsed to reshape the database (getting new courses or updated and removed
# ones).
# This script runs all by itself in a Docker container. It still relies on a
# valid Mongo database.

import urllib.request
import datetime
import re
from icalendar import Calendar
from pymongo import MongoClient
import json

LOG_INFO = 0
LOG_WARNING = 1
LOG_ERROR = 2


def log(msg, lvl=LOG_INFO):
    """
    Affiche un message dans l'entrée standard par la fonction print(), avec un
    formattage spécifique au niveau d'alerte donné (3 possibles).
    Aucune vérification n'est effectuée sur les arguments de cette méthode.

    Ex :
    [2018-01-29 19:07:38] [ERROR] Le fichier de paramètres n'existe pas.

    :param msg: string, la description du log
    :param lvl: LOG_INFO par défaut, le niveau d'alerte levé : info, warning ou error
    :return: None
    """
    alert = "INFO"
    if lvl == LOG_WARNING:
        alert = "WARNING"
    elif lvl == LOG_ERROR:
        alert = "ERROR"
    now = datetime.datetime.now()
    print("[{}] [{}] {}".format(
        datetime.datetime.strftime(now, "%Y-%m-%d %H:%M:%S"),
        alert,
        msg
    ))


def format_data(calendar, planning_parser):
    """
    Parse every event in the calendar string given in parameter with the parser
    also given in parameter and return a list with the events as formatted
    data.

    The calendar string must respect the iCalendar format in the first place.

    The data returned correspond to this example :
        [
            {
                "title": "Any title",
                "start_date": datetime.datetime(2017, 25, 09, 8, 15, 0, 0),
                "end_date": datetime.datetime(2017, 25, 09, 10, 15, 0, 0),
                "classrooms": ["Room 1", "Room b"],
                "groups": ["TD1", "TD2"],
                "teachers": ["Mr Smith"],
                "undetermined_description_items": ["Ms WÎεrd ϵncöding", "garbage"],
                "event_id": "ADE4567890123456d89012d456789012d456d89"
            },
            {
                ...
            },
            ...
        ]

    :param calendar: the iCalendar string to parse
    :param planning_parser: the parser to use (an instance of EventParser)
    :return: a list of events
    """
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


def update_database(event_list, collection):
    """
    Compare the list of events given in parameter (formatted like the
    format_data function) and the data in the database for every events.

    If the event found in the new calendar is different from the event in the
    database, then the latter is modified with the new data.

    :param event_list: the list of events to insert in the database
    :param collection: the collection (in the mongo database) to insert data
    :return: None
    """
    for event in event_list:
        collection.update_one(
            {"event_id": event["event_id"]},
            {
                "$set": event
            },
            upsert=True
        )


class EventParser:
    """
    A parser with a main method parse() used to get the attributes from an
    event in the Calendar.

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
    """
    Description des paramètres récupérés dans le fichier de paramètres JSON.

    {
        "updater": les paramètres généraux de l'updater
        {
            "frequency": int (facultatif), la fréquence en secondes de lancement du script. Pas de récurrence du script si absent.
        }
        "database": les paramètres généraux de la base de données mongo
        {
            "name": string, le nom de la db du planning dans mongo.
            "host": string (facultatif), le nom de l'hôte pour la base de données mongo. Par défaut "localhost".
            "port": int (facultatif), le port de la base de données sur l'hôte mongo. Par défaut 27017.
        }
        "branches": les filières à suivre/mettre à jour, chacune ayant une collection dans la base de données du planning
        [
            {
                "name": string, le nom de la collection de la filière dans la base de données
                "teachers_patterns": les expressions régulières permettant de détecter le nom d'un professeur dans la description complète du cours
                [
                    string
                ]
                "groups_patterns": les expressions régulières permettant de détecter le nom d'un groupe dans la description complète du cours
                [
                    string
                ]
                "delimiter": string, le délimiteur de chaque champ dans le fichier iCalendar
                "groups": les groupes/classes de la filière, réparties par nom (dit affiliation)
                [
                    {
                        "name": string, le nom du groupe auquel chaque cours sera rattaché dans la base de données (affiliation)
                        "adresses": les URIs de téléchargement des fichiers iCalendar relatifs au cours
                        [
                            string
                        ]
                    }
                ]
            }
        ]
    }
    
    """
    PARAMS_FILENAME = "params.json"

    with open(PARAMS_FILENAME, 'r') as params_file:
        params = json.load(params_file)

    # database informations
    host = 'localhost'
    if 'host' in params["database"]:
        host = params["database"]["host"]
    port = 27017
    if 'port' in params["database"]:
        port = params["database"]["port"]

    client = MongoClient(host, port)
    db_name = params["database"]["name"]
    db = client[db_name]

    for branch in params["branches"]:
        collec_name = db_name + "_" + branch["name"]
        print("Collection " + collec_name)
        data_list = []
        parser = EventParser(branch["teachers_patterns"], branch["groups_patterns"],
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
                            # adds the current group to the affiliations
                            data["affiliation"].append(group["name"])
                            found = True
                            break
                    if found is False:
                        item["affiliation"] = [group["name"]]
                        data_list.append(item)
                i += 1

        print("Updating data in collection " + collec_name)
        update_database(data_list, db[collec_name])
