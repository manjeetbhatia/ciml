# Copyright 2018 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import datetime
import io
import os

import pandas
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from subunit2sql.db import api

now = datetime.datetime.utcnow()


def _parse_dstat_date(date_str):
    split_date_time = date_str.split(' ')
    monthday = split_date_time[0].split('-')
    time_pieces = split_date_time[1].split(':')
    return datetime.datetime(now.year, int(monthday[1]), int(monthday[0]),
                             int(time_pieces[0]),
                             int(time_pieces[1]), int(time_pieces[2]))


def _get_dstat_file(artifact_link, run_uuid=None):
    paths = ['controller/logs/dstat-csv_log.txt.gz',
             'controller/logs/dstat-csv_log.txt',
             'logs/dstat-csv_log.txt',
             'logs/dstat-csv_log.txt.gz']
    # TODO(andreaf) We may want this configurable if case we build multiple
    # datasets
    local_path= ['dataset']
    # TODO(andreaf) This needs to be fixed because when we come different routes
    # we will need to lookup the file from file system or not, and behave
    # differently:
    # - MQTT: new file, file should not be there
    # - DB: file may be there or not
    # - Stable dataset: file must be there
    local_store = os.pathsep.join([os.path.realpath(__file__), os.path.pardir,
                                   local_path])
    for path in paths:
        url = artifact_link + '/' + path
        resp = requests.get(url)
        if resp.status_code == 404:
            continue
        f = io.StringIO(resp.text)
        out = pandas.read_csv(f, skiprows=6).set_index('time')
        out.index = [_parse_dstat_date(x) for x in out.index]
        out.index = pandas.DatetimeIndex(out.index)
        return out
    else:
        return None

def _get_result_for_run(run, session):
    run_uuid = run.uuid
    result = {}
    dstat = _get_dstat_file(run.artifacts, run.uuid)
    if dstat is None:
        return None
    test_runs = api.get_test_runs_by_run_id(run.uuid, session=session)
    session.close()
    tests = []
    for test_run in test_runs:
        test = {'status': test_run.status}
        start_time = test_run.start_time
        start_time = start_time.replace(
            microsecond=test_run.start_time_microsecond)
        stop_time = test_run.stop_time
        stop_time = stop_time.replace(
            microsecond=test_run.stop_time_microsecond)
        test['start_time'] = start_time
        test['stop_time'] = stop_time
        tests.append(test)
    if run.fails > 0 or run.passes == 0:
        result['status'] = 'Success'
    else:
        result['status'] = 'Fail'
    result['artifact'] = run.artifacts
    result['tests'] = tests
    result['dstat'] = dstat
    return result

def get_subunit_results(build_uuid, db_uri):
    engine = create_engine(db_uri)
    Session = sessionmaker(bind=engine)
    session = Session()
    runs = api.get_runs_by_key_value('build_uuid', build_uuid, session=session)
    results = []
    for run in runs:
        # Check if we are interested in this build at all
        meta = api.get_run_metadata(run.uuid, session=session)
        build_names = [x.value for x in meta if x.key == 'build_name']
        if len(build_names) >= 1:
            build_name = build_names[0]
        else:
            continue
        # NOTE(mtreinish): Only be concerned with single node to start
        if 'multinode' in build_name:
            continue
        result = _get_result_for_run(run, session)
        if result:
            results.append(result)
    return results

def get_subunit_results_for_run(run, db_uri):
    engine = create_engine(db_uri)
    Session = sessionmaker(bind=engine)
    session = Session()
    return [_get_result_for_run(run, session)]

def get_runs_by_name(db_uri, build_name='tempest-full'):
    engine = create_engine(db_uri)
    Session = sessionmaker(bind=engine)
    session = Session()
    runs = api.get_runs_by_key_value('build_name', build_name, session=session)
    return runs
