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

from errors import *
import urllib.request
from urllib.error import URLError
import datetime
import re
import sched
from icalendar import Calendar
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo.database import Database
from sys import exc_info
import json

LOG_INFO = 0
LOG_WARNING = 1
LOG_ERROR = 2

DEFAULT_FREQUENCY = None
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 27017
DEFAULT_DELIMITER = "\n"

PARSER_MODE_ENT = "ENT"
PARSER_MODE_NEXTCLOUD = "Nextcloud"


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
            "error_tolerance": int, le nombre d'erreurs tolérées à la suite : si n updates ont été lancées à la suite et chacune se terminait par une erreur, le script s'arrête. Échouer à télécharger un fichier ne compte pas comme une erreur mais ne réinitialise pas le compteur non plus
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
                "name": string, le nom attribué aux collections de la filière dans la base de données
                "teachers_patterns": les expressions régulières permettant de détecter le nom d'un professeur dans la description complète du cours
                [
                    string
                ]
                "groups_patterns": les expressions régulières permettant de détecter le nom d'un groupe dans la description complète du cours
                [
                    string
                ]
                "blacklist": les expressions régulières permettant de ne pas inclure les expressions, séparées par le délimiteur, correspondantes de la description
                [
                    string (facultatif)
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
    :raise errors.ParamError: when a parameter isn't present, isn't a correct type or isn't valid
    """

    # get the file JSON structure
    p = None
    try:
        with open(filename, 'r') as p_file:
            p = json.load(p_file)
    except SyntaxError as e:
        m = "The path of the params file {} might not be valid.".format(filename)
        log(m, LOG_ERROR)
        raise ParamError(m, e)
    except FileNotFoundError as e:
        m = "The JSON params file {} was not found.".format(filename)
        log(m, LOG_ERROR)
        raise ParamError(m, e)
    except json.decoder.JSONDecodeError as e:
        m = "The JSON params file {} couldn't be decoded.".format(filename)
        log(m, LOG_ERROR)
        raise ParamError(m, e)
    except OSError as e:
        m = "Unknown error while using the JSON params file {}.".format(filename)
        log(m, LOG_ERROR)
        raise ParamError(m, e)

    # UPDATER
    try:
        if type(p["updater"]) is not dict:
            m = "The \"updater\" node is not a dictionary in the JSON params file."
            log(m, LOG_ERROR)
            raise ParamError(m)
    except KeyError as e:
        m = "The \"updater\" node not found in the JSON params file."
        log(m, LOG_ERROR)
        raise ParamError(m, e)

    # UPDATER FREQUENCY
    try:
        if type(p["updater"]["frequency"]) is not int and p["updater"]["frequency"] is not None:
            m = "The \"frequency\" in the \"updater\" node is not an int or None."
            log(m, LOG_ERROR)
            raise ParamError(m)
    except KeyError:
        m = "The \"frequency\" in the \"updater\" node was not found. Setting the default value {}.".format(DEFAULT_FREQUENCY)
        log(m, LOG_WARNING)
        p["updater"]["frequency"] = DEFAULT_FREQUENCY

    # UPDATER ERROR_TOLERANCE
    try:
        if type(p["updater"]["error_tolerance"]) is not int:
            m = "The \"error_tolerance\" in the \"updater\" node is not an int."
            log(m, LOG_ERROR)
            raise ParamError(m)
        if p["updater"]["error_tolerance"] < 0:
            m = "The \"error_tolerance\" in the \"updater\" node is not positive or zero."
            log(m, LOG_ERROR)
            raise ParamError(m)
    except KeyError as e:
        m = "The\"error_tolerance\" in the \"updater\" node was not found."
        log(m, LOG_ERROR)
        raise ParamError(m, e)

    # DATABASE
    try:
        if type(p["database"]) is not dict:
            m = "The \"database\" node is not a dictionary in the JSON params file."
            log(m, LOG_ERROR)
            raise ParamError(m)
    except KeyError as e:
        m = "The \"database\" node not found in the JSON params file."
        log(m, LOG_ERROR)
        raise ParamError(m, e)

    # DATABASE NAME
    try:
        if type(p["database"]["name"]) is not str:
            m = "The \"name\" in the \"database\" node is not a str."
            log(m, LOG_ERROR)
            raise ParamError(m)
    except KeyError as e:
        m = "The \"name\" in the \"database\" node was not found."
        log(m, LOG_ERROR)
        raise ParamError(m, e)

    # DATABASE HOST
    try:
        if type(p["database"]["host"]) is not str:
            m = "The \"host\" in the \"database\" node is not a str."
            log(m, LOG_ERROR)
            raise ParamError(m)
    except KeyError:
        m = "The \"host\" in the \"database\" node was not found. Setting the default value {}.".format(DEFAULT_HOST)
        log(m, LOG_WARNING)
        p["database"]["host"] = DEFAULT_HOST

    # DATABASE PORT
    try:
        if type(p["database"]["port"]) is not int:
            m = "The \"port\" in the \"database\" node is not an int."
            log(m, LOG_ERROR)
            raise ParamError(m)
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
            raise ParamError(m)
    except KeyError as e:
        m = "The \"branches\" node not found in the JSON params file."
        log(m, LOG_ERROR)
        raise ParamError(m, e)

    # BRANCHES NODES
    b_i = 0
    branch_names = []
    for b in p["branches"]:
        if type(b) is not dict:
            m = "The node at position {} in \"branches\" is not a dict.".format(b_i)
            log(m, LOG_ERROR)
            raise ParamError(m)

        # BRANCHES NODE NAME
        try:
            if type(b["name"]) is not str:
                m = "The \"name\" in the node at position {} in \"branches\" is not a str.".format(b_i)
                log(m, LOG_ERROR)
                raise ParamError(m)
            elif b["name"] in branch_names:
                m = "The \"name\" in the node at position {} in \"branches\" already exists !".format(b_i)
                log(m, LOG_ERROR)
                raise ParamError(m)
            branch_names.append(b["name"])
        except KeyError as e:
            m = "The \"name\" in the node at position {} in \"branches\" was not found.".format(b_i)
            log(m, LOG_ERROR)
            raise ParamError(m, e)

        # BRANCHES NODE TEACHERS_PATTERNS
        try:
            p_i = 0
            for pattern in b["teachers_patterns"]:
                if type(pattern) is not str:
                    m = "The element at position {} in \"teachers_patterns\" in the node at position {} in \"branches\" is not a str.".format(p_i, b_i)
                    log(m, LOG_ERROR)
                    raise ParamError(m)
                p_i += 1
        except KeyError as e:
            m = "The \"teachers_patterns\" in the node at position {} in \"branches\" was not found.".format(b_i)
            log(m, LOG_ERROR)
            raise ParamError(m, e)

        # BRANCHES NODE GROUPS_PATTERNS
        try:
            p_i = 0
            for pattern in b["groups_patterns"]:
                if type(pattern) is not str:
                    m = "The element at position {} in \"groups_patterns\" in the node at position {} in \"branches\" is not a str.".format(p_i, b_i)
                    log(m, LOG_ERROR)
                    raise ParamError(m)
        except KeyError as e:
            m = "The \"groups_patterns\" in the node at position {} in \"branches\" was not found.".format(b_i)
            log(m, LOG_ERROR)
            raise ParamError(m, e)

        # BRANCHES NODE BLACKLIST
        try:
            p_i = 0
            for blacklisted in b["blacklist"]:
                if type(blacklisted) is not str:
                    m = "The element at position {} in \"blacklist\" in the node at position {} in \"branches\" is not a str.".format(p_i, b_i)
                    log(m, LOG_ERROR)
                    raise ParamError(m)
        except KeyError as e:
            m = "The \"blacklist\" in the node at position {} in \"branches\" was not found.".format(b_i)
            log(m, LOG_ERROR)
            raise ParamError(m, e)

        # BRANCHES NODE DELIMITER
        try:
            if type(b["delimiter"]) is not str:
                m = "The \"delimiter\" in the node at position {} in \"branches\" is not str.".format(b_i)
                log(m, LOG_ERROR)
                raise ParamError(m)
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
                    raise ParamError(m)

                # BRANCHES NODE GROUP NAME
                try:
                    if type(g["name"]) is not str:
                        m = "The \"name\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" is not a str".format(g_i, b_i)
                        log(m, LOG_ERROR)
                        raise ParamError(m)
                    if g["name"] in g_names:
                        m = "The \"name\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" already exists !".format(g_i, b_i)
                        log(m, LOG_ERROR)
                        raise ParamError(m)
                    g_names.append(g["name"])
                except KeyError as e:
                    m = "The \"name\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" was not found.".format(g_i, b_i)
                    log(m, LOG_ERROR)
                    raise ParamError(m, e)

                # BRANCHES NODE GROUP ADDRESSES
                try:
                    if type(g["addresses"]) is not list:
                        m = "The \"addresses\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" is not a list.".format(g_i, b_i)
                        log(m, LOG_ERROR)
                        raise ParamError(m)
                    for a in g["addresses"]:
                        if type(a) is not str:
                            m = "An element in \"addresses\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" is not a str.".format(g_i, b_i)
                            log(m, LOG_ERROR)
                            raise ParamError(m)
                        if not re.match("http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+", a):
                            m = "An element in \"addresses\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" does not match the URI regex.".format(g_i, b_i)
                            log(m, LOG_ERROR)
                            raise ParamError(m)
                except KeyError as e:
                    m = "The \"addresses\" in the node at position {} in \"groups\" in the node at position {} in \"branches\" was not found.".format(g_i, b_i)
                    log(m, LOG_ERROR)
                    raise ParamError(m, e)

                g_i += 1
        except KeyError as e:
            m = "The \"groups\" list in the node at position {} in \"branches\" was not found.".format(b_i)
            log(m, LOG_ERROR)
            raise ParamError(m, e)

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
                "event_id": "ADE4567890123456d89012d456789012d456d89",
                "last_update": datetime.datetime(2017, 25, 08, 23, 40, 02)
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
            "event_id": planning_parser.get_event_id(),
            "last_update": planning_parser.get_update_time()
        }
        ret.append(appointment)
    return ret


class EventParser:
    """
    The parent parser for specific parsers. Simply defines the methods init and
    parse, and the attributes it needs to return after parsing.
    """

    def __init__(self, update_time):
        """
        Creates the final attributes and applies default values for them before
        parsing.

        :param update_time: the datetime of the current updating process, will be set as new values to last_update in every event
        """
        self._title = ""
        self._start_date = None
        self._end_date = None
        self._classrooms = ""
        self._teachers = []
        self._groups = []
        self._undetermined_description_items = []
        self._event_id = ""
        self._update_time = update_time

    def parse(self, vevent):
        raise NotImplementedError("Method parse must be implemented !")

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

    def get_update_time(self):
        """
        Return the datetime of the current updating process.
        """
        return self._update_time


class ENTEventParser(EventParser):
    """
    A parser with a main method parse() used to get the attributes from an
    event in the Calendar.

    The get methods must be used after parsing.
    """

    def __init__(self, blacklist, teachers_patterns, groups_patterns,
                 description_delimiter, update_time):
        """
        Instanciate the object with different parameters.

        :param blacklist: the string patterns used to blacklist items not desired
        :param teachers_patterns: the string patterns used to identify a teacher
        :param groups_patterns: the string patterns used to identify a group
        :param description_delimiter: the delimiter used to split the items in the calendar's description field
        :param update_time: the datetime of the current updating process, will be set as new values to last_update in every event
        """
        super().__init__(update_time)

        self._blacklist = blacklist
        self._teachers_patterns = teachers_patterns
        self._groups_patterns = groups_patterns
        self._delimiter = description_delimiter

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
        self._start_date = vevent["DTSTART"].dt.replace(tzinfo=None)  # tzinfo=None to remove the UTC timezone, which is useless and source of conflict with PyMongo
        self._end_date = vevent["DTEND"].dt.replace(tzinfo=None)
        self._classrooms = []
        for elem in vevent["LOCATION"].split(self._delimiter):
            if len(elem) != 0:
                self._classrooms.append(elem)
        self._teachers = []
        self._groups = []
        self._undetermined_description_items = []
        for elem in vevent["DESCRIPTION"].split(self._delimiter):
            if elem != "":
                found = False
                for pattern in self._blacklist:
                    if re.match(pattern, elem) is not None:
                        found = True
                        break
                if not found:
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


class NextcloudEventParser(EventParser):
    """
    A parser to integrate iCalendar format from Nextcloud planning.
    """
    def __init__(self, update_time):
        """
        See EventParser.

        :param update_time: see EventParser
        """
        super().__init__(update_time)

    def parse(self, vevent):
        """
        Parses the events according to Nextcloud iCalendar format.

        :param vevent: the vevent to parse from the iCalendar file
        """
        self._title = vevent["SUMMARY"]
        self._start_date = vevent["DTSTART"]
        self._end_date = vevent["DTEND"]
        self._classrooms = vevent["LOCATION"]

        # DESCRIPTION =
        # parfois "Par {teacher}" peut-être aussi "De {teacher}"
        # et éventuellement plusieurs "Par {teacher1}, {teacher2} et {teacher3}"
        desc = vevent["DESCRIPTION"]
        if desc.startswith("Par ") and len(desc) > 4:
            desc = desc[4:]
        t = desc.split(",")
        for i in range(len(t) - 1):
            self._teachers.append(t[i].strip())
        t = t[-1].split(" et ")
        for te in t:
            self._teachers.append(te.strip())

        self._teachers.append(vevent["DESCRIPTION"])

        self._groups.append(vevent["CLASS"])
        self._undetermined_description_items = []
        self._event_id = str(vevent["UID"])


def get_modifications(old, new, attributes):
    """
    Create a dictionary containing the old values when they are different from
    the new ones at given attributes.
    Does not consider other attributes than the array given in parameter.

    :param old: a dictionary containing the old values
    :param new: a dictionary containing the new values
    :param attributes: the attributes to check between new and old
    :return: a dict containing the old values when different from new ones at given attributes
    """
    ret = {}
    for a in attributes:
        if old[a] != new[a]:
            ret[a] = old[a]
    return ret


def update_database(event_list, collection):
    """
    Compare the list of events given in parameter (formatted like the
    format_data function) with the data in the database collection given in
    parameter for every event.

    If the event found in the new calendar is different from the event in the
    database, then the latter is modified with the new data.
    The old data is still saved in the document in the "old" parameter, which
    contains the old parameters which were found as modified at the time
    "updated".

    :param event_list: the list of events to insert in the database
    :param collection: the collection (in the mongo database) to insert data
    :return: a tuple containing (number of new events, number of updated events, number of unchanged events), note the deleted events aren't counted here
    :raise errors.UpdateDatabaseError: when the updates raised a PyMongoError
    """
    new = 0
    updated = 0
    unchanged = 0
    for event in event_list:
        try:
            old_ev = collection.find_and_modify(
                query={"event_id": event["event_id"]},
                update={
                    "$set": event
                },
                upsert=True
            )
        except PyMongoError as e:
            m = "Error while updating collection {}".format(collection)
            raise UpdateDatabaseError(m, e)

        if old_ev is not None:
            # put the modifications in the "old" array
            modifications = get_modifications(old_ev, event, [
                "title",
                "start_date",
                "end_date",
                "classrooms",
                "teachers",
                "groups",
                "undetermined_description_items"
            ])
            if len(modifications) != 0:
                updated += 1
                modifications["updated"] = event["last_update"]
                try:
                    collection.update_one(
                        {"_id": old_ev["_id"]},
                        {
                            "$push": {
                                "old": modifications
                            }
                        }
                    )
                except PyMongoError as e:
                    m = "Error while pushing modifications in collection {}".format(collection)
                    raise UpdateDatabaseError(m, e)
            else:
                unchanged += 1
        else:
            new += 1

    return new, updated, unchanged


def garbage_collect(start_collec, garbage_collec, last_update):
    """
    Remove the events from the start_collec collection which do not have the
    same last_update as the current one.
    The removed events are put in the garbage_collec collection for log
    purposes.

    :param start_collec: the mongo collection from where the events are removed
    :param garbage_collec: the collection to put the removed events from the start_collec
    :param last_update: the last update of the events : if they weren't updated from this one, they are considered deleted
    :return: the number of events collected
    :raise errors.UpdateDatabaseError: when the bulk insert or the bulk remove raises a PyMongoError
    """
    collected = 0

    garbage = start_collec.find({"last_update": {"$lt": last_update}})
    if garbage.count() != 0:
        # Bulk operations can take a lot of memory, stay aware of this and, if something happen, see here https://stackoverflow.com/questions/27039083/mongodb-move-documents-from-one-collection-to-another-collection
        bulk_remove = start_collec.initialize_unordered_bulk_op()
        bulk_insert = garbage_collec.initialize_unordered_bulk_op()

        for g in garbage:
            collected += 1
            try:
                bulk_insert.insert(g)
            except PyMongoError as e:
                m = "Error while inserting to collection {}".format(garbage_collec)
                raise UpdateDatabaseError(m, e)
            try:
                bulk_remove.find({"_id": g["_id"]}).remove_one()
            except PyMongoError as e:
                m = "Error while removing from collection {}".format(start_collec)
                raise UpdateDatabaseError(m, e)

        bulk_insert.execute()
        bulk_remove.execute()

    return collected


def main(db, branches):
    """
    Make the update for every group in every branch :
    - Download the group iCalendars files from the URIs
    - Parse the files to order the information in a computable dictionary
    - Update the database according to the new, updated and deleted courses

    The branches parameter comes from the get_params function and must match
    the pattern.

    :param db: the database from the MongoClient object to update
    :param branches: list, the branches with information to make the update
    :return: None
    :raise TypeError: if db is not a Database
    :raise TypeError: if branches is not a list
    :raise DownloadError: when the download isn't valid (5 attempts by default are set)
    :raise UpdateDatabaseError: when a database update goes wrong
    """
    if type(db) is not Database:
        m = "The PyMongo database given was not recognized."
        log(m, LOG_ERROR)
        raise TypeError(m)
    if type(branches) is not list:
        m = "The parameter branches is not a list type. Does it really come from the get_params function ?"
        log(m, LOG_ERROR)
        raise TypeError(m)

    try:
        update_time = datetime.datetime.now()
        for branch in branches:
            collec_name = "planning_" + branch["name"]
            garbage_collec_name = "garbage_" + branch["name"]
            log_prefix = "[{}]".format(branch["name"])
            log("{} Starting the update for the branch {} (mode {})".format(log_prefix, branch["name"], branch["parser"]["mode"]))
            data_list = []

            parser = None
            parser_params = branch["parser"]
            if parser_params["mode"] == PARSER_MODE_ENT:
                parser = ENTEventParser(parser_params["blacklist"], parser_params["teachers_patterns"], parser_params["groups_patterns"], parser_params["delimiter"], update_time)
            elif parser_params["mode"] == PARSER_MODE_NEXTCLOUD:
                parser = NextcloudEventParser(update_time)

            nb_groups = len(branch["groups"])
            k = 1
            for group in branch["groups"]:
                log_prefix_group = "[{}/{}]".format(k, nb_groups)
                i = 1
                nb_addresses = len(group["addresses"])
                for address in group["addresses"]:
                    log_prefix_address = "[{}/{}]".format(i, nb_addresses)
                    cal = None
                    attempts = 0
                    max_attempts = 5
                    while attempts < max_attempts:
                        log("{} {} {} Downloading address in group {}".format(
                            log_prefix, log_prefix_group, log_prefix_address,
                            group["name"]))
                        try:
                            ics_file = urllib.request.urlopen(address)
                        except URLError as e:
                            m = "{} Error requesting URI {}".format(log_prefix,
                                                                    address)
                            log(m, LOG_ERROR)
                            raise DownloadError(m, e)
                        ics = ics_file.read()

                        try:
                            cal = Calendar.from_ical(ics)
                            break
                        except ValueError as e:
                            attempts += 1
                            m = "{} Failed to download a calendar file ({}/{})".format(log_prefix, attempts, max_attempts)
                            log(m, LOG_WARNING)
                    if attempts == max_attempts:
                        m = "{} Failed to download from the URI {}".format(log_prefix, address)
                        log(m, LOG_ERROR)
                        raise DownloadError(m)

                    log("{} {} {} Removing duplicate events".format(log_prefix, log_prefix_group, log_prefix_address))
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
                k += 1

            print(data_list)

            # log("{} Updating new and modified events in {}".format(log_prefix, collec_name))
            # new, updated, unchanged = update_database(data_list, db[collec_name])
            # log("{} Update complete : {} newly created events, {} updated events, {} unchanged events".format(log_prefix, new, updated, unchanged))
            # log("{} Collecting garbage events from {} and storing them in {}".format(log_prefix, collec_name, garbage_collec_name))
            # collected = garbage_collect(db[collec_name], db[garbage_collec_name], update_time)
            # log("{} Garbage collection complete : {} events collected".format(log_prefix, collected))
            # log("{} There are {} events in {}".format(log_prefix, new + updated + unchanged, collec_name))
            # log("{} There are {} events in {}".format(log_prefix, db[garbage_collec_name].count({}), garbage_collec_name))
            # log("{} The updater ended successfully".format(log_prefix), LOG_INFO)
    except UpdateDatabaseError as e:
        m = "Error while updating the database"
        log(m, LOG_ERROR)
        raise e
    except DownloadError as e:
        m = "Error while downloading the files"
        log(m, LOG_ERROR)
        raise e
    except:
        m = "An unexpected error occured in the updating process"
        log(m, LOG_ERROR)
        raise exc_info()[1]


if __name__ == '__main__':
    PARAMS_FILENAME = "params.json"

    log("Starting to parse the {} file".format(PARAMS_FILENAME))
    try:
        params = get_params(PARAMS_FILENAME)
    except ParamError as e:
        m = "An error occured, please check the parameters before launching the script again"
        log(m, LOG_ERROR)
        raise e
    log("The parameters were successfully set.")
    log("The updater frequency parameter is set to {} seconds.".format(params["updater"]["frequency"]))
    log("The database host parameter is set to {}.".format(params["database"]["host"]))
    log("The database port parameter is set to {}.".format(params["database"]["port"]))

    client = MongoClient(params["database"]["host"], params["database"]["port"])

    db_name = params["database"]["name"]
    db = client[db_name]

    main(db, params["branches"])

    delay = params["updater"]["frequency"]
    if delay is not None:
        errors = 0
        while True:
            try:
                # the schedule delay starts only when the branch updates are finished
                log("Scheduling the next update (in {} seconds)...".format(delay))
                s = sched.scheduler()
                s.enter(delay, 1, main, (db, params["branches"]))
                try:
                    s.run(blocking=True)
                except DownloadError as e:
                    m = "Couldn't download a file. Something seems wrong, maybe better luck next time ?"
                    log(m, LOG_WARNING)
                except UpdaterError as e:
                    errors += 1
                    m = "An error happened in this updater instance ({}/{} in a row)".format(errors, params["updater"]["error_tolerance"])
                    log(m, LOG_WARNING)
                    if errors == params["updater"]["error_tolerance"]:
                        m = "Reached the maximum number of errors tolered in a row. The script will totally stop."
                        log(m, LOG_WARNING)
                        break
                else:
                    errors = 0
            except:
                m = "A global error happened, that's bad ! The script is broken."
                log(m, LOG_ERROR)
                raise exc_info()[1]
