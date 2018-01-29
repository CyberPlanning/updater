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

DEFAULT_FREQUENCY = None
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 27017
DEFAULT_DELIMITER = "\n"


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


def get_params(filename):
    """
    Create the object of the parameters used for the updater, in the file which
    path is given by filename.
    Also, the method checks if everything is in order.

    If an optional (facultatif) parameter isn't in the file, its default value
    is set. It's still advised to choose a value even if its the default.
    If a non-optional parameter isn't in the file, an error is raised.
    To make things clear : a node is always necessary in the file, even if it's
    only composed of optional elements.

    The JSON file is described in French below.

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
        "branches": les filières à suivre/mettre à jour, chacune ayant une collection dans la base de données du planning, donc les noms doivent être différents
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
                "delimiter": string (facultatif), le délimiteur de chaque champ dans le fichier iCalendar. Par défaut "\n".
                "groups": les groupes/classes de la filière, réparties par nom (dit affiliation)
                [
                    {
                        "name": string, le nom du groupe auquel chaque cours sera rattaché dans la base de données (affiliation), unique pour un groupe
                        "adresses": les URIs de téléchargement des fichiers iCalendar relatifs au cours
                        [
                            string
                        ]
                    }
                ]
            }
        ]
    }

    :param filename: the path of the JSON file containing the parameters
    :return: an object similar to the JSON pattern
    """

    # get the file JSON structure
    p = None
    try:
        with open(filename, 'r') as p_file:
            p = json.load(p_file)
    except SyntaxError as e:
        m = "The path of the params file {} might not be valid.".format(filename)
        log(m, LOG_ERROR)
        raise e
    except FileNotFoundError as e:
        m = "The JSON params file {} was not found.".format(filename)
        log(m, LOG_ERROR)
        raise e
    except json.decoder.JSONDecodeError as e:
        m = "The JSON params file {} couldn't be decoded.".format(filename)
        log(m, LOG_ERROR)
        raise e
    except OSError as e:
        m = "Unknown error while using the JSON params file {}.".format(filename)
        log(m, LOG_ERROR)
        raise e

    # UPDATER
    try:
        if type(p["updater"]) is not dict:
            m = "The \"updater\" node is not a dictionary in the JSON params file."
            log(m, LOG_ERROR)
            raise TypeError(m)
    except KeyError as e:
        m = "The \"updater\" node not found in the JSON params file."
        log(m, LOG_ERROR)
        raise e

    # UPDATER FREQUENCY
    try:
        if type(p["updater"]["frequency"]) is not int and p["updater"]["frequency"] is not None:
            m = "The \"frequency\" in the \"updater\" node is not an int or None."
            log(m, LOG_ERROR)
            raise TypeError(m)
        else:
            m = "The \"frequency\" is set to {} seconds.".format(p["updater"]["frequency"])
            log(m, LOG_INFO)
    except KeyError:
        m = "The \"frequency\" in the \"updater\" node was not found. Setting the default value {}.".format(DEFAULT_FREQUENCY)
        log(m, LOG_WARNING)
        p["updater"]["frequency"] = DEFAULT_FREQUENCY

    # DATABASE
    try:
        if type(p["database"]) is not dict:
            m = "The \"database\" node is not a dictionary in the JSON params file."
            log(m, LOG_ERROR)
            raise TypeError(m)
    except KeyError as e:
        m = "The \"database\" node not found in the JSON params file."
        log(m, LOG_ERROR)
        raise e

    # DATABASE NAME
    try:
        if type(p["database"]["name"]) is not str:
            m = "The \"name\" in the \"database\" node is not a str."
            log(m, LOG_ERROR)
            raise TypeError(m)
    except KeyError as e:
        m = "The \"name\" in the \"database\" node was not found."
        log(m, LOG_ERROR)
        raise e

    # DATABASE HOST
    try:
        if type(p["database"]["host"]) is not str:
            m = "The \"host\" in the \"database\" node is not a str."
            log(m, LOG_ERROR)
            raise TypeError(m)
        else:
            m = "The \"host\" is set to {}.".format(p["database"]["host"])
            log(m, LOG_INFO)
    except KeyError:
        m = "The \"host\" in the \"database\" node was not found. Setting the default value {}.".format(DEFAULT_HOST)
        log(m, LOG_WARNING)
        p["database"]["host"] = DEFAULT_HOST

    # DATABASE PORT
    try:
        if type(p["database"]["port"]) is not int:
            m = "The \"port\" in the \"database\" node is not an int."
            log(m, LOG_ERROR)
            raise TypeError(m)
        else:
            m = "The \"port\" is set to {}.".format(p["database"]["port"])
            log(m, LOG_INFO)
    except KeyError:
        m = "The \"port\" in the \"database\" node was not found. Setting the default value {}.".format(
            DEFAULT_HOST)
        log(m, LOG_WARNING)
        p["database"]["port"] = DEFAULT_HOST

    # BRANCHES
    try:
        if type(p["branches"]) is not list:
            m = "The \"branches\" node is not a dictionary in the JSON params file."
            log(m, LOG_ERROR)
            raise TypeError(m)
    except KeyError as e:
        m = "The \"branches\" node not found in the JSON params file."
        log(m, LOG_ERROR)
        raise e

    # BRANCHES NODES
    b_i = 0
    branch_names = []
    for b in p["branches"]:
        if type(b) is not dict:
            m = "The node at position {} in \"branches\" is not a dict.".format(b_i)
            log(m, LOG_ERROR)
            raise TypeError(m)

        # BRANCHES NODE NAME
        try:
            if type(b["name"]) is not str:
                m = "The \"name\" in the node at position {} in \"branches\" is not a str.".format(b_i)
                log(m, LOG_ERROR)
                raise TypeError(m)
            elif b["name"] in branch_names:
                m = "The \"name\" in the node at position {} in \"branches\" already exists !".format(b_i)
                log(m, LOG_ERROR)
                raise TypeError(m)
            branch_names.append(b["name"])
        except KeyError as e:
            m = "The \"name\" in the node at position {} in \"branches\" was not found.".format(b_i)
            log(m, LOG_ERROR)
            raise e

        # BRANCHES NODE TEACHERS_PATTERNS
        try:
            p_i = 0
            for pattern in b["teachers_patterns"]:
                if type(pattern) is not str:
                    m = "The element at position {} in \"teachers_patterns\" in the node at position {} in \"branches\" is not a str.".format(p_i, b_i)
                    log(m, LOG_ERROR)
                    raise TypeError(m)
                p_i += 1
        except KeyError as e:
            m = "The \"teachers_patterns\" in the node at position {} in \"branches\" was not found.".format(b_i)
            log(m, LOG_ERROR)
            raise e

        # BRANCHES NODE GROUPS_PATTERNS
        try:
            p_i = 0
            for pattern in b["groups_patterns"]:
                if type(pattern) is not str:
                    m = "The element at position {} in \"groups_patterns\" in the node at position {} in \"branches\" is not a str.".format(p_i, b_i)
                    log(m, LOG_ERROR)
                    raise TypeError(m)
        except KeyError as e:
            m = "The \"groups_patterns\" in the node at position {} in \"branches\" was not found.".format(b_i)
            log(m, LOG_ERROR)
            raise e

        # BRANCHES NODE DELIMITER
        try:
            if type(b["delimiter"]) is not str:
                m = "The \"delimiter\" in the node at position {} in \"branches\" is not str.".format(b_i)
                log(m, LOG_ERROR)
                raise TypeError(m)
        except KeyError as e:
            m = "The \"delimiter\" in the node at position {} in \"branches\" was not found. Setting the default value {}.".format(b_i, DEFAULT_DELIMITER)
            log(m, LOG_WARNING)
            b["delimiter"] = DEFAULT_DELIMITER

        # BRANCHES NODE GROUPS
        try:
            g_i = 0
            g_names = []
            for g in b["groups"]:
                if type(g) is not dict:
                    m = "The node at position {} in \"groups\" in the node at position {} in \"branches\" is not a dict.".format(g_i, b_i)
                    log(m, LOG_ERROR)
                    raise TypeError(m)

                # BRANCHES NODE GROUP NAME
                try:
                    if type(g["name"]) is not str:
                        m = "The \"name\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" is not a str".format(g_i, b_i)
                        log(m, LOG_ERROR)
                        raise TypeError(m)
                    if g["name"] in g_names:
                        m = "The \"name\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" already exists !".format(g_i, b_i)
                        log(m, LOG_ERROR)
                        raise TypeError(m)
                    g_names.append(g["name"])
                except KeyError as e:
                    m = "The \"name\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" was not found.".format(g_i, b_i)
                    log(m, LOG_ERROR)
                    raise e

                # BRANCHES NODE GROUP ADDRESSES
                try:
                    if type(g["addresses"]) is not list:
                        m = "The \"addresses\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" is not a list.".format(g_i, b_i)
                        log(m, LOG_ERROR)
                        raise TypeError(m)
                    for a in g["addresses"]:
                        if type(a) is not str:
                            m = "An element in \"addresses\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" is not a str.".format(g_i, b_i)
                            log(m, LOG_ERROR)
                            raise TypeError(m)
                        if not re.match("http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+", a):
                            m = "An element in \"addresses\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" does not match the URI regex.".format(g_i, b_i)
                            log(m, LOG_ERROR)
                            raise ValueError(m)
                except KeyError as e:
                    m = "The \"addresses\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" was not found.".format(g_i, b_i)
                    log(m, LOG_ERROR)
                    raise e

                g_i += 1
        except KeyError as e:
            m = "The \"groups\" list in the node at position {} in \"branches\" was not found.".format(b_i)
            log(m, LOG_ERROR)
            raise e

        b_i += 1

    return p


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
    PARAMS_FILENAME = "params.json"

    log("Starting to parse the {} file".format(PARAMS_FILENAME), LOG_INFO)
    params = get_params(PARAMS_FILENAME)
    log("The parameters were successfully set.", LOG_INFO)

    client = MongoClient(params["database"]["host"], params["database"]["port"])
    db_name = params["database"]["name"]
    db = client[db_name]

    for branch in params["branches"]:
        collec_name = db_name + "_" + branch["name"]
        log("Collection {}".format(collec_name), LOG_INFO)
        data_list = []
        parser = EventParser(branch["teachers_patterns"], branch["groups_patterns"],
                             branch["delimiter"])
        for group in branch["groups"]:
            i = 1
            for address in group["addresses"]:
                log("Downloading address in group {}".format(i, group["name"]), LOG_INFO)
                ics_file = urllib.request.urlopen(address)
                cal = Calendar.from_ical(ics_file.read())
                log("Removing duplicate data of group {}".format(group["name"]), LOG_INFO)
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
