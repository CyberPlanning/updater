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

from errors import Error, DownloadError, ParamError, UpdateDatabaseError, UpdaterError
import urllib.request
from urllib.error import URLError
import datetime
import re
import sched
from icalendar import Calendar, vDatetime
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo.database import Database
from sys import exc_info
import json
from jsonschema import validate, ValidationError, SchemaError

PARAMS_FILENAME = "params.json"
PARAMS_SCHEMA_FILENAME = "params.schema.json"

LOG_INFO = 0
LOG_WARNING = 1
LOG_ERROR = 2

DEFAULT_FREQUENCY = None
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 27017
DEFAULT_DELIMITER = "\n"

PARSER_MODE_ENT = "ENT"
PARSER_MODE_HACK2G2 = "Hack2G2"


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


def get_params():
    """
    Create the object of the parameters used for the updater, in the file which
    path is given by filename.
    It also verifies using JSON Schema specs draft 4 (python implementation) if
    the json is valid.

    If an optional parameter isn't in the file, its default value
    is set. It's still advised to choose a value even if its the default.
    If a non-optional parameter isn't in the file, an error is raised.

    Refer to the params JSON schema (whose filename is given in
    PARAMS_SCHEMA_FILENAME) to build a valid params schema (whose filename is
    given in PARAMS_FILENAME).
    More info about JSON Schema : https://json-schema.org/

    :return: an object similar to the JSON pattern
    :raise errors.ParamError: when a parameter isn't present, isn't a correct type or isn't valid
    """

    # get the file JSON structure
    try:
        with open(PARAMS_FILENAME, 'r') as p_file:
            p = json.load(p_file)
    except SyntaxError as err:
        msg = "The path of the params file {} might not be valid.".format(PARAMS_FILENAME)
        log(msg, LOG_ERROR)
        raise ParamError(msg) from err
    except FileNotFoundError as err:
        msg = "The JSON params file {} was not found.".format(PARAMS_FILENAME)
        log(msg, LOG_ERROR)
        raise ParamError(msg) from err
    except json.decoder.JSONDecodeError as err:
        msg = "The JSON params file {} couldn't be decoded.".format(PARAMS_FILENAME)
        log(msg, LOG_ERROR)
        raise ParamError(msg) from err
    except OSError as err:
        msg = "Unknown system error while using the JSON params file {}.".format(PARAMS_FILENAME)
        log(msg, LOG_ERROR)
        raise ParamError(msg) from err

    # get the JSON schema used for validation
    try:
        with open(PARAMS_SCHEMA_FILENAME, 'r') as p_file:
            p_schema = json.load(p_file)
    except SyntaxError as err:
        msg = "The path of the JSON Schema params file {} might not be valid.".format(PARAMS_SCHEMA_FILENAME)
        log(msg, LOG_ERROR)
        raise ParamError(msg) from err
    except FileNotFoundError as err:
        msg = "The JSON Schema params file {} was not found.".format(PARAMS_SCHEMA_FILENAME)
        log(msg, LOG_ERROR)
        raise ParamError(msg) from err
    except json.decoder.JSONDecodeError as err:
        msg = "The JSON Schema params file {} coudln't be decoded.".format(PARAMS_SCHEMA_FILENAME)
        log(msg, LOG_ERROR)
        raise ParamError(msg) from err
    except OSError as err:
        msg = "Unknow system error while using the JSON params file {}.".format(PARAMS_SCHEMA_FILENAME)
        log(msg, LOG_ERROR)
        raise ParamError(msg) from err

    # validate the parameters
    try:
        validate(p, p_schema)
    except ValidationError as err:
        msg = "The parameters ({}) aren't valid according to the schema ({}).".format(PARAMS_FILENAME, PARAMS_SCHEMA_FILENAME)
        log(msg, LOG_ERROR)
        raise ParamError(msg) from err
    except SchemaError as err:
        msg = "The parameters schema {} itself is invalid.".format(PARAMS_SCHEMA_FILENAME)
        log(msg, LOG_ERROR)
        raise ParamError(msg) from err

    # we do not check the branch mode requirements...
    # maybe a restructuration is necessary ?

    msg = "{} valid according to the schema {}".format(PARAMS_FILENAME, PARAMS_SCHEMA_FILENAME)
    log(msg, LOG_INFO)

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
        self._classrooms = []
        self._teachers = []
        self._groups = []
        self._undetermined_description_items = []
        self._event_id = ""
        self._update_time = update_time

    def default_values(self):
        self._title = ""
        self._start_date = None
        self._end_date = None
        self._classrooms = []
        self._teachers = []
        self._groups = []
        self._undetermined_description_items = []
        self._event_id = ""

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
        self._start_date = vevent["DTSTART"].dt.replace(
            tzinfo=None)  # tzinfo=None to remove the UTC timezone, which is useless and source of conflict with PyMongo
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


class Hack2G2EventParser(EventParser):
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
        self.default_values()
        try:
            self._title = str(vevent["SUMMARY"])
        except KeyError:
            pass

        try:
            dt = vevent["DTSTART"].dt
            if type(dt) is datetime.datetime:
                # removing info on timezone and adjust on UTC
                self._start_date = (dt - dt.utcoffset()).replace(tzinfo=None)
            elif type(dt) is datetime.date:
                self._start_date = datetime.datetime(dt.year, dt.month, dt.day, 0, 0, 0)
        except KeyError:
            pass

        try:
            dt = vevent["DTEND"].dt
            if type(dt) is datetime.datetime:
                self._end_date = (dt - dt.utcoffset()).replace(tzinfo=None)
            elif type(dt) is datetime.date:
                self._end_date = datetime.datetime(dt.year, dt.month, dt.day, 0, 0, 0)
        except KeyError:
            pass

        try:
            self._classrooms.append(str(vevent["LOCATION"]))
        except KeyError:
            pass

        # DESCRIPTION =
        # parfois "Par {teacher}" peut-être aussi "De {teacher}"
        # et éventuellement plusieurs "Par {teacher1}, {teacher2} et {teacher3}"
        try:
            desc = vevent["DESCRIPTION"]
            teachers_pattern = re.compile('([pP]ar|[dD]e|PAR|DE)[a-zA-Z0-9 \(\)\.-]+((,| et )[a-zA-Z0-9 \(\)\.-]+)*')
            matcher = re.match(teachers_pattern, desc)
            if matcher is not None:
                match = matcher.group()
                if (match.lower().startswith("par ")) and len(desc) > 4:
                    match = match[4:]
                elif match.lower().startswith("de ") and len(desc) > 3:
                    match = match[3:]
                t = match.split(",")
                for i in range(len(t) - 1):
                    self._teachers.append(t[i].strip())
                t = t[-1].split(" et ")
                for te in t:
                    self._teachers.append(te.strip())
        except KeyError:
            pass

        try:
            self._groups.append(str(vevent["CLASS"]))
        except KeyError:
            pass

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
        except PyMongoError as err:
            msg = "Error while updating collection {}".format(collection)
            raise UpdateDatabaseError(msg) from err

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
                except PyMongoError as err:
                    msg = "Error while pushing modifications in collection {}".format(
                        collection)
                    raise UpdateDatabaseError(msg) from err
            else:
                unchanged += 1
        else:
            new += 1

    return new, updated, unchanged


def garbage_collect(start_collec, garbage_collec, last_update):
    """
    Remove the events from the start_collec collection which do not have the
    same last_update as the current one.
    Previous events aren't taken into account.
    The removed events are put in the garbage_collec collection for log
    purposes.

    :param start_collec: the mongo collection from where the events are removed
    :param garbage_collec: the collection to put the removed events from the start_collec
    :param last_update: the last update of the events : if they weren't updated from this one, they are considered deleted
    :return: the number of events collected
    :raise errors.UpdateDatabaseError: when the bulk insert or the bulk remove raises a PyMongoError
    """
    collected = 0

    garbage = start_collec.find({
        "last_update": {"$lt": last_update},
        "end_date": {"$gte": datetime.datetime.now()}
    })
    if garbage.count() != 0:
        # Bulk operations can take a lot of memory, stay aware of this and, if something happen, see here https://stackoverflow.com/questions/27039083/mongodb-move-documents-from-one-collection-to-another-collection
        bulk_remove = start_collec.initialize_unordered_bulk_op()
        bulk_insert = garbage_collec.initialize_unordered_bulk_op()

        for g in garbage:
            collected += 1
            try:
                bulk_insert.insert(g)
            except PyMongoError as err:
                msg = "Error while inserting to collection {}".format(
                    garbage_collec)
                raise UpdateDatabaseError(msg) from err
            try:
                bulk_remove.find({"_id": g["_id"]}).remove_one()
            except PyMongoError as err:
                msg = "Error while removing from collection {}".format(
                    start_collec)
                raise UpdateDatabaseError(msg) from err

        bulk_insert.execute()
        bulk_remove.execute()

    return collected


def main(database, branches):
    """
    Make the update for every group in every branch :
    - Download the group iCalendars files from the URIs
    - Parse the files to order the information in a computable dictionary
    - Update the database according to the new, updated and deleted courses

    The branches parameter comes from the get_params function and must match
    the pattern.

    :param database: the database from the MongoClient object to update
    :param branches: list, the branches with information to make the update
    :return: None
    :raise TypeError: if db is not a Database
    :raise TypeError: if branches is not a list
    :raise DownloadError: when the download isn't valid (5 attempts by default are set)
    :raise UpdateDatabaseError: when a database update goes wrong
    """
    if type(database) is not Database:
        msg = "The PyMongo database given was not recognized."
        log(msg, LOG_ERROR)
        raise TypeError(msg)
    if type(branches) is not list:
        msg = "The parameter branches is not a list type. Does it really come from the get_params function ?"
        log(msg, LOG_ERROR)
        raise TypeError(msg)

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
            elif parser_params["mode"] == PARSER_MODE_HACK2G2:
                parser = Hack2G2EventParser(update_time)

            if parser is not None:
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
                            log(
                                "{} {} {} Downloading address in group {}".format(
                                    log_prefix, log_prefix_group,
                                    log_prefix_address,
                                    group["name"]))
                            try:
                                ics_file = urllib.request.urlopen(address)
                            except (URLError, ConnectionError) as err:
                                # bypass the 5 retries: it's a network error that probably won't be solved in a few seconds
                                msg = "{} Error requesting URI {}".format(
                                    log_prefix,
                                    address)
                                log(msg, LOG_ERROR)
                                raise DownloadError(msg) from err
                            ics = ics_file.read()

                            try:
                                cal = Calendar.from_ical(ics)
                                break
                            except ValueError:
                                attempts += 1
                                msg = "{} Failed to download a calendar file ({}/{})".format(
                                    log_prefix, attempts, max_attempts)
                                log(msg, LOG_WARNING)
                        if attempts == max_attempts:
                            msg = "{} Failed to download from the URI {}".format(
                                log_prefix, address)
                            log(msg, LOG_ERROR)
                            raise DownloadError(msg)

                        log("{} {} {} Removing duplicate events".format(
                            log_prefix, log_prefix_group, log_prefix_address))
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

            log("{} Updating new and modified events in {}".format(log_prefix, collec_name))
            new, updated, unchanged = update_database(data_list, db[collec_name])
            log("{} Update complete : {} newly created events, {} updated events, {} unchanged events".format(log_prefix, new, updated, unchanged))
            log("{} Collecting garbage events from {} and storing them in {}".format(log_prefix, collec_name, garbage_collec_name))
            collected = garbage_collect(db[collec_name], db[garbage_collec_name], update_time)
            log("{} Garbage collection complete : {} events collected".format(log_prefix, collected))
            log("{} There are {} events in {}".format(log_prefix, new + updated + unchanged, collec_name))
            log("{} There are {} events in {}".format(log_prefix, db[garbage_collec_name].count({}), garbage_collec_name))
            log("{} The updater ended successfully".format(log_prefix), LOG_INFO)
    except UpdateDatabaseError as err:
        msg = "Error while updating the database"
        log(msg, LOG_ERROR)
        raise err
    except DownloadError as err:
        msg = "Error while downloading the files"
        log(msg, LOG_ERROR)
        raise err
    except Exception as err:
        msg = "An unexpected error occurred in the updating process"
        log(msg, LOG_ERROR)
        raise Error(msg) from err


if __name__ == '__main__':
    log("Starting to parse the {} file".format(PARAMS_FILENAME))
    try:
        params = get_params()
    except ParamError as e:
        m = "An error occured, please check the parameters before launching the script again"
        log(m, LOG_ERROR)
        raise e
    log("The parameters were successfully set.")
    log("The updater frequency parameter is set to {} seconds.".format(
        params["updater"]["frequency"]))
    log("The database host parameter is set to {}.".format(
        params["database"]["host"]))
    log("The database port parameter is set to {}.".format(
        params["database"]["port"]))

    client = MongoClient(params["database"]["host"],
                         params["database"]["port"])

    db_name = params["database"]["name"]
    db = client[db_name]

    main(db, params["branches"])

    delay = params["updater"]["frequency"]
    if delay is not None:
        errors = 0
        while True:
            try:
                # the schedule delay starts only when the branch updates are finished
                log("Scheduling the next update (in {} seconds)...".format(
                    delay))
                s = sched.scheduler()
                s.enter(delay, 1, main, (db, params["branches"]))
                try:
                    s.run(blocking=True)
                except DownloadError as e:
                    m = "Couldn't download a file. Something seems wrong, maybe better luck next time ?"
                    log(m, LOG_WARNING)
                except UpdaterError as e:
                    errors += 1
                    m = "An error happened in this updater instance ({}/{} in a row)".format(
                        errors, params["updater"]["error_tolerance"])
                    log(m, LOG_WARNING)
                    if errors == params["updater"]["error_tolerance"]:
                        m = "Reached the maximum number of errors tolered in a row. The script will totally stop."
                        log(m, LOG_WARNING)
                        break
                else:
                    errors = 0
            except Exception as err:
                m = "A global error happened, that's bad ! The script is broken."
                log(m, LOG_ERROR)
                raise Error(m) from err
