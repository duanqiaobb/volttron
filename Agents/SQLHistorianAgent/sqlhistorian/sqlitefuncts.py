# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:

# Copyright (c) 2013, Battelle Memorial Institute
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in
#    the documentation and/or other materials provided with the
#    distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and documentation
# are those of the authors and should not be interpreted as representing
# official policies, either expressed or implied, of the FreeBSD
# Project.
#
# This material was prepared as an account of work sponsored by an
# agency of the United States Government.  Neither the United States
# Government nor the United States Department of Energy, nor Battelle,
# nor any of their employees, nor any jurisdiction or organization that
# has cooperated in the development of these materials, makes any
# warranty, express or implied, or assumes any legal liability or
# responsibility for the accuracy, completeness, or usefulness or any
# information, apparatus, product, software, or process disclosed, or
# represents that its use would not infringe privately owned rights.
#
# Reference herein to any specific commercial product, process, or
# service by trade name, trademark, manufacturer, or otherwise does not
# necessarily constitute or imply its endorsement, recommendation, or
# favoring by the United States Government or any agency thereof, or
# Battelle Memorial Institute. The views and opinions of authors
# expressed herein do not necessarily state or reflect those of the
# United States Government or any agency thereof.
#
# PACIFIC NORTHWEST NATIONAL LABORATORY
# operated by BATTELLE for the UNITED STATES DEPARTMENT OF ENERGY
# under Contract DE-AC05-76RL01830
#}}}

import errno
import logging
import os
import sqlite3

from zmq.utils import jsonapi

from volttron.platform.agent import utils

utils.setup_logging()
_log = logging.getLogger(__name__)

class SqlLiteFuncts(object):

    def __init__(self, database,
                 detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES):

        if database == ':memory:':
            self.__database = database
        else:
            self.__database = os.path.expanduser(database)
            db_dir  = os.path.dirname(self.__database)

            #If the db does not exist create it
            # in case we are started before the historian.
            try:
                os.makedirs(db_dir)
            except OSError as exc:
                if exc.errno != errno.EEXIST or not os.path.isdir(db_dir):
                    raise
            try:
                self.__detect_types = eval(detect_types)
            except TypeError:
                self.__detect_types = detect_types

        self.conn = self.connect()
        self.execute('''CREATE TABLE IF NOT EXISTS data
                                (ts timestamp NOT NULL,
                                 topic_id INTEGER NOT NULL,
                                 value_string TEXT NOT NULL,
                                 UNIQUE(ts, topic_id))''',
                False)

        self.execute('''CREATE INDEX IF NOT EXISTS data_idx
                                ON data (ts ASC)''',
                False)

        self.execute('''CREATE TABLE IF NOT EXISTS topics
                                (topic_id INTEGER PRIMARY KEY,
                                 topic_name TEXT NOT NULL,
                                 UNIQUE(topic_name))''',
                True)


    def query(self, topic, start=None, end=None, skip=0,
                            count=None, order="FIRST_TO_LAST"):
        """This function should return the results of a query in the form:
        {"values": [(timestamp1, value1), (timestamp2, value2), ...],
         "metadata": {"key1": value1, "key2": value2, ...}}

         metadata is not required (The caller will normalize this to {} for you)
        """
        query = '''SELECT data.ts, data.value_string
                   FROM data, topics
                   {where}
                   {order_by}
                   {limit}
                   {offset}'''

        where_clauses = ["WHERE topics.topic_name = ?", "topics.topic_id = data.topic_id"]
        args = [topic]

        if start is not None:
            where_clauses.append("data.ts > ?")
            args.append(start)

        if end is not None:
            where_clauses.append("data.ts < ?")
            args.append(end)

        where_statement = ' AND '.join(where_clauses)

        order_by = 'ORDER BY data.ts ASC'
        if order == 'LAST_TO_FIRST':
            order_by = ' ORDER BY data.ts DESC'

        #can't have an offset without a limit
        # -1 = no limit and allows the user to
        # provied just an offset
        if count is None:
            count = -1

        limit_statement = 'LIMIT ?'
        args.append(count)

        offset_statement = ''
        if skip > 0:
            offset_statement = 'OFFSET ?'
            args.append(skip)

        _log.debug("About to do real_query")

        real_query = query.format(where=where_statement,
                                  limit=limit_statement,
                                  offset=offset_statement,
                                  order_by=order_by)

        print(real_query)
        print(args)

        c = connect()
        c.execute(real_query,args)
        values = [(ts.isoformat(), jsonapi.loads(value)) for ts, value in c]

        return {'values':values}

    def execute(self, query, commit=True):
        if not self.conn:
            self.conn = connect()
        self.conn.execute(query)
        if commit:
            self.conn.commit()

    def connect(self):
        if self.__database is None:
            raise AttributeError
        if self.__detect_types:
            return sqlite3.connect(self.__database,
                                   detect_types=self.__detect_types)
        return sqlite3.connect(self.__database)

    def insert_data(self, ts, topic_id, data, commit=True):
        if not self.conn:
            self.conn = self.connect()

        c = self.conn.cursor()
        c.execute('''INSERT OR REPLACE INTO data values(?, ?, ?)''',
                                  (ts,topic_id,jsonapi.dumps(data)))
        if commit:
            self.conn.commit()

    def insert_topic(self, topic, commit=True):
        if not self.conn:
            self.conn = self.connect()

        c = self.conn.cursor()
        c.execute('''INSERT INTO topics values (?,?)''', (None, topic))
        c.execute('''SELECT last_insert_rowid()''')
        row = c.fetchone()

        if commit:
            self.conn.commit()

        return row

    def insert_complete(self):
        self.conn.commit()

    def get_topic_map(self):
        if not self.conn:
            self.conn = self.connect()

        c = self.conn.cursor()
        c.execute("SELECT * FROM topics")
        tm = {}

        while True:
            results = c.fetchmany(1000)
            if not results:
                break
            for result in results:
                tm[result[1]] = result[0]

        return tm
