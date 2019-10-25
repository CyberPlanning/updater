# CPU

This script is part of the Cyberplanning project. It takes place as the backend updater for the Mongo database.

Let's call it **CPU**, for **CyberPlanning Updater**.

The goal is to update at a given frequence the database used by the API to provide the courses to the end-user.

## How it works

CPU is controlled by the parameters you set in `params.json` (see dedicated part below).

## `params.json`

This file's scope is defined in the *JSON schema* `params.schema.json`, with description of each node or 

Here is an example *JSON instance* for use in `params.json`:

```json
{
  "TODO": 0
}
```

## Database architecture

In the Mongo database, you can find two collections per branch:
- `planning_XXXX` as the set of events / courses existing of the branch
- `garbage_XXXX` as the set of events / courses which are not found (removed or event ID changed) anymore in further updates

A BSON document in a `planning_XXXX` or `garbage_XXXX` collection looks like:

```json
{
  "_id": ObjectId("0123456789abcdef01234567"),
  "event_id": "ADE60123456789abcdef0123456789abcdef01234",
  "affiliation" : [
    "11",
    "12"
  ],
  "classrooms" : [
    "V-TO-ENSIbs-D113,V-TO-ENSIbs-A104,V-TO-ENSIbs-A106"
  ],
  "end_date" : ISODate("2018-01-31T09:30:00Z"),
  "groups" : [
    "CYBER S4",
    "CYBER S5"
  ],
  "start_date" : ISODate("2018-01-31T07:30:00Z"),
  "teachers" : [
    "Chouquet G."
  ],
  "title" : "Challenge Cyber 3 pour Cyber 2",
  "undetermined_description_items" : [ ],
  "last_update" : ISODate("2018-01-31T23:56:35.838Z"),
  "old" : [
    {
      "undetermined_description_items" : [
        "",
        "(Exporté le:31/01/2018 21:31)"
      ],
      "updated" : ISODate("2018-01-31T20:34:57.261Z")
    }
  ]
}
```

- **\_id** is the normal identifier given by Mongo at the document creation
- **event_id** is an identifier to link

## Setting up CPU

### Using Docker



### Dependencies
```shell
apt-get install python-pip
python -m pip install --upgrade pip
python -m pip install icalendar
python -m pip install pymongo
```
