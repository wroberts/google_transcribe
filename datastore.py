#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
datastore.py
(c) Will Roberts  28 October, 2016

A dict-like object which is a persistent data store, backed by a
JSON-formatted file.
'''

import json

def store_data(json_filename, data):
    '''
    Writes the Python structure in `data` into a JSON file with path
    `json_filename`.

    Arguments:
    - `json_filename`:
    - `data`:
    '''
    with open(json_filename, 'w') as output_file:
        json_data = json.dumps(data, sort_keys=True, indent=4, ensure_ascii=False)
        output_file.write(json_data.encode('utf-8'))

def load_data(json_filename):
    '''
    Loads a Python data structure from the JSON file `json_filename`
    and returns it.

    Arguments:
    - `json_filename`:
    '''
    with open(json_filename, 'r') as input_file:
        return json.loads(input_file.read().decode('utf-8'))

class PersistentDict(dict):
    '''
    A persistent data store, backed by a JSON-formatted file.
    '''

    def __init__(self, filename):
        '''
        Constructor.

        Arguments:
        - `filename`:
        '''
        self._filename = filename
        try:
            data = load_data(filename)
        except IOError:
            data = {}
        super(PersistentDict, self).__init__(data)

    def __delitem__(self, key):
        super(PersistentDict, self).__delitem__(key)
        store_data(self._filename, self)

    def __setitem__(self, key, value):
        super(PersistentDict, self).__setitem__(key, value)
        store_data(self._filename, self)
