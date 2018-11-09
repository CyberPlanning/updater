#!/usr/bin/python3
# coding: utf-8
import argparse
from enum import Enum
from datetime import datetime
from typing import List
from bson import ObjectId

from pymongo import MongoClient


PLANNING_CUSTOM = "planning_custom"
GARBAGE_CUSTOM = "garbage_custom"


class Color(Enum):
    RED = '\033[31m'
    GRN = '\033[32m'
    RST = '\033[0m'


def parse_args():
    """Arguments parsing."""
    parser = argparse.ArgumentParser(description='Manage custom events in data base')

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--add',
                       action='store_true',
                       help='Add event')
    group.add_argument('--update',
                       action='store_true',
                       help='Update event')
    group.add_argument('--remove',
                       action='store_true',
                       help='Remove event')
    group.add_argument('--list',
                       action='store_true',
                       help='List all events')
    
    parser.add_argument('-v',
                        '--verbose',
                        help='Verbose mode',
                        action='count',
                        default=0
                        )

    parser.add_argument('--mongo-host',
                        type=str,
                        default='localhost',
                        help='Mongo host, default: localhost',
                        )

    parser.add_argument('--mongo-port',
                        type=int,
                        default=27017,
                        help='Mongo port, default: 27017',
                        )


    parser.add_argument('--filter',
                        type=str,
                        help='Filter list result',
                        )

    parser.add_argument('--title',
                        type=str,
                        help='Event title',
                        )

    parser.add_argument('--id',
                        type=str,
                        help='Event id',
                        )


    args = parser.parse_args()

    return args

def prompt_event():
    event_fields = {
        'title': str,
        'description': str,
        'locations': List,
        'stakeholders': List,
        'start_date': datetime,
        'end_date': datetime,
    }

    event = {}

    for f, t in event_fields.items():

        for _ in range(3):
            value = input("%s :" % f)

            if t == datetime:
                if value == "":
                    value = datetime.now()
                else:
                    try:
                        value = datetime.strptime(value, "%Y-%m-%dT%H:%M")
                    except ValueError:
                        print("[!] Bad date use pattern %Y-%m-%dT%H:%M")
                        continue
            elif t == List:
                value = value.split(';')

            event[f] = value
            break

    return event

def find_events(title=None, id=None):
    if title:
        return db[PLANNING_CUSTOM].find({'title': title})

    elif id:
        return db[PLANNING_CUSTOM].find({'_id': ObjectId(id)})



if __name__ == '__main__':

    parser = parse_args()

    print(parser)

    mongo = MongoClient(parser.mongo_host, parser.mongo_port)
    db = mongo.planning

    if parser.list:

        cursor = db[PLANNING_CUSTOM].find()
        print('[*] Events:')
        for event in cursor:
            print(' - %s\n' % event)


    elif parser.add:
        event = find_events(title=parser.title, id=parser.id)
        if event:
            print('[!] event : %s' % event)

        # ask event
        event = prompt_event()
        print('[!] event: %s' % event)

        db[PLANNING_CUSTOM].insert_one(event)

    elif parser.remove:
        if not parser.title and not parser.id:
            print("[!] Remove need a title or an id")
            exit(1)

        events = find_events(title=parser.title, id=parser.id)

        for event in events:
            confirm = input('Remove %s (%s) [y/N]: ' % (event['_id'], event['title'])).lower()
            if confirm == 'y':
                db[GARBAGE_CUSTOM].insert_one(event)
                db[PLANNING_CUSTOM].delete_one({'_id': event['_id']})

                print("[!] Removed")

    elif parser.update:
            raise NotImplementedError()
