# CPU

This script is part of the Cyberplanning project. It takes place as the backend updater for the Mongo database.

Let's call it **CPU**, for **CyberPlanning Updater**.

The goal is to update at a given frequence the database used by the API to provide the courses to the end-user.

Although Cyberplanning was first designed as a planning for students at first, this updater and the database are not restricted to such a use case. The semantics for these imply to split the courses or other events into a branch, inside of which they will have different affiliations to link them to our defined groups. Read more about it in the **Database architecture** section, or in **Configuration**.

## How it works

CPU has different states according to its configuration (see dedicated part below).

![Alt text](./docs/img/cpu-states.svg)
<img src="./docs/img/cpu-states.svg">

[Mermaid View](https://mermaidjs.github.io/mermaid-live-editor/#/view/eyJjb2RlIjoic3RhdGVEaWFncmFtXG5bKl0gLS0-IEJyYW5jaFxuc3RhdGUgQnJhbmNoIHtcblsqXSAtLT4gRG93bmxvYWRpbmdcbkRvd25sb2FkaW5nIC0tPiBEb3dubG9hZGluZyA6IEZhaWx1cmVcbkRvd25sb2FkaW5nIC0tPiBbKl0gOiBUb28gbWFueSBmYWlsdXJlc1xuRG93bmxvYWRpbmcgLS0-IFBhcnNpbmcgOiBTdWNjZXNzXG5QYXJzaW5nIC0tPiBVcGRhdGluZ1xuVXBkYXRpbmcgLS0-IFsqXVxufVxuQnJhbmNoIC0tPiBCcmFuY2g6IE5leHQgYnJhbmNoXG5CcmFuY2ggLS0-IElkbGU6IE5vIG1vcmUgYnJhbmNoXG5JZGxlIC0tPiBCcmFuY2g6IERlbGF5IiwibWVybWFpZCI6eyJ0aGVtZSI6ImRlZmF1bHQifX0)

- **Downloading**: downloads the given URLs for every groups in the current branch. After a certain amount of failed attempts, it hibernates in idle mode. In case of success, it goes through parsing.
- **Parsing**: parses the iCal previously downloaded. It has custom modes adapted to our needs and situation, read more in the dedicated part below. Parsing also format the events for every groups according to the database for the next part, updating.
- **Updating**: updates the database for the current branch, differenciating unchanged events, new events, updated events and deleted events.
- **Idle**: waits a certain amount of time for the next update.

### About Parsing

The iCal format is used differently by different services and people creating events. The issue is that some of these don't use the standard way to describe their events. That's why we defined 2 modes adapted to our current needs for Cyberplanning:

- **ENT**: our school planning. The provider is ADE, and the people creating and modifying their events are multiple (school administratives, teachers, ...).
- **Hack2G2**: an association planning. The provider is Nextcloud, and one person is creating and modifying their own events (the head or secretary).

In ENT mode, the provider ADE gives teachers and groups in the "DESCRIPTION" field of the iCal format, for every events. So the parsing of such event must be based on regular expressions, to identify our own database fields "teachers", "groups" and "undetermined_description_items".

In Hack2G2 mode, the provider Nextloud also uses the iCal "DESCRIPTION" field for participants (our "teachers"), but uses the iCal field "CLASS" for our "groups" database field. The parsing is more standard for groups, but teachers still need regular expression parsing according to the habits of the person updating their events.

See more about Regex configuration in the **Configuration** section.

If you are willing to re-use this updater and database, these modes are most likely not appropriate for your needs and a new `EventParser`-inheriting class must be written.

## Configuration

Parameters can be set in `params.json`. This file's scope is defined in the *JSON schema* `params.schema.json`, with a description for each node or element. It needs to be created first as we do not provide a ready-to-go file in this repo.

Still, here is an example *JSON instance* to base your `params.json` file:

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

```js
{
  "_id": ObjectId("0123456789abcdef01234567"),
  "event_id": "ADE60123456789abcdef0123456789abcdef01234",
  "affiliation" : [
    "21",
    "22"
  ],
  "classrooms" : [
    "V-TO-ENSIbs-A001,V-TO-ENSIbs-A002"
  ],
  "end_date" : ISODate("2018-01-31T09:30:00Z"),
  "groups" : [
    "CYBER S3",
    "CYBER S4"
  ],
  "start_date" : ISODate("2018-01-31T07:30:00Z"),
  "teachers" : [
    "McAfee J."
  ],
  "title" : "CTF challenge",
  "undetermined_description_items" : [ ],
  "last_update" : ISODate("2018-01-31T23:56:35.838Z"),
  "old" : [
    {
      "undetermined_description_items" : [
        "xYZ"
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
