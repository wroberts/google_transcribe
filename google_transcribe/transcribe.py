#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2016 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

'''
transcribe.py
(c) Will Roberts  29 October, 2016

Server process to manage speech transcription using the Google Cloud
Speech API.
'''

from __future__ import absolute_import, unicode_literals

import errno
import logging
import mimetypes
import os
import socket
import subprocess
import sys
import time

import click
import httplib2
from appdirs import AppDirs
from googleapiclient import discovery
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from oauth2client import client, tools
from oauth2client.file import Storage

from .datastore import PersistentDict

logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s',
                    stream=sys.stderr, level=logging.DEBUG)
logger = logging.getLogger(__name__)


# ============================================================
#  CONFIGURATION
# ============================================================

# The name of the folder on the user's Google Drive which will be
# monitored for audio recording files.
FOLDER_NAME = 'Exams'

# The name of the bucket on the Google Cloud Storage where WAV files
# are stored during transcription.
BUCKET = 'semantics-exam-marking.appspot.com'

# The name of the user agent to represent this app to Google Drive
USER_AGENT_NAME = 'Samarkand'

# ============================================================
#  AUTHORISATION
# ============================================================

APPLICATION_DIRS = AppDirs('google-transcribe', 'wkr', version='1.0')
APP_CONFIG_DIR = APPLICATION_DIRS.user_config_dir
APP_CACHE_DIR = APPLICATION_DIRS.user_cache_dir


def get_credentials_path(filename, check_file_exists=True):
    '''
    Gets the full path to a file stored in the credentials
    subdirectory of this application's configuration directory.
    '''
    path = os.path.join(APP_CONFIG_DIR, 'credentials')
    if not os.path.exists(path):
        logger.fatal('Could not find credentials directory')
        raise Exception('Could not find credentials directory')
    path = os.path.join(path, filename)
    if check_file_exists and not os.path.exists(path):
        logger.fatal('Could not find credentials file %s', filename)
        raise Exception('Could not find credentials file {}'.format(filename))
    return path


def get_drive_service():
    '''
    Returns an object used to interact with the Google Drive API.
    '''
    flow = client.flow_from_clientsecrets(
        get_credentials_path('secret.json'),
        'https://www.googleapis.com/auth/drive')
    flow.user_agent = USER_AGENT_NAME
    store = Storage(get_credentials_path('storage.dat', False))
    credentials = store.get()
    if not credentials or credentials.invalid:
        flags = tools.argparser.parse_args(args=[])
        credentials = tools.run_flow(flow, store, flags)
    http = credentials.authorize(httplib2.Http())
    service = discovery.build('drive', 'v3', http=http)
    return service


def get_service_acct_http():
    '''
    Returns an HTTP connection object which is authorised using this
    app's Google Service Account.
    '''
    # Application default credentials provided by env variable
    # GOOGLE_APPLICATION_CREDENTIALS
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = get_credentials_path(
        'semantics-exam-marking.json')
    credentials = (client.GoogleCredentials.get_application_default()
                   .create_scoped(
                       ['https://www.googleapis.com/auth/cloud-platform']))
    http = httplib2.Http()
    credentials.authorize(http)
    return http


def get_storage_service():
    '''
    Returns an object used to interact with the Google Cloud Storage
    API.
    '''
    http = get_service_acct_http()
    return discovery.build('storage', 'v1', http=http)


def get_speech_service():
    '''
    Returns an object used to interact with the Google Cloud Speech
    API.
    '''
    http = get_service_acct_http()
    service = discovery.build('speech', 'v1', http=http)
    return service


# ============================================================
#  GOOGLE DRIVE API
# ============================================================


def drive_get_folder_id(drive_service, folder_name):
    '''
    Finds the folder ID of the folder with the given name on the
    user's Google Drive.

    Arguments:
    - `drive_service`:
    - `folder_name`:
    '''
    results = drive_service.files().list(
        pageSize=100,
        q=("mimeType = 'application/vnd.google-apps.folder'"
           " and name='{}'").format(folder_name),
        spaces='drive',
        corpus='user',
        fields="files(id)").execute()
    if not results or 'files' not in results or not results['files']:
        return None
    return results['files'][0]['id']


def drive_list_most_recent_files(drive_service, folder_id):
    '''
    Lists the most recent files in the given folder of the user's
    Google Drive.

    Arguments:
    - `drive_service`:
    - `folder_id`:
    '''
    # https://developers.google.com/drive/v3/web/search-parameters
    results = drive_service.files().list(
        pageSize=100,
        orderBy='modifiedTime desc',
        q="'{}' in parents and mimeType contains 'audio/'".format(folder_id),
        spaces='drive',
        corpus='user',
        fields=("nextPageToken, files(id, mimeType, modifiedTime, "
                "name, parents)")).execute()
    return results


# https://developers.google.com/drive/v3/web/about-sdk
# https://developers.google.com/drive/v3/web/manage-downloads
# https://developers.google.com/drive/v3/web/about-auth
def drive_download_file(drive_service, file_id, output_filename,
                        verbose=False):
    '''
    Downloads the file with the given file ID on the user's Google
    Drive to the local file with the path `output_filename`.

    Arguments:
    - `drive_service`:
    - `file_id`:
    - `output_filename`:
    - `verbose`:
    '''
    request = drive_service.files().get_media(fileId=file_id)
    with open(output_filename, 'wb') as output_file:
        downloader = MediaIoBaseDownload(output_file, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            if verbose:
                logger.info("Download %d%%.", int(status.progress() * 100))


# http://stackoverflow.com/q/20922944/1062499
# https://developers.google.com/drive/v3/web/manage-uploads
# https://developers.google.com/drive/v3/reference/files/create
def drive_upload_file(drive_service, input_filename, parent_folder_ids,
                      mimetype=None):
    '''
    Uploads a file from the local disk (stored at `input_filename`) to
    the user's Google Drive, placing it in the directories indicated
    with `parent_folder_ids`.

    Arguments:
    - `drive_service`:
    - `input_filename`:
    - `parent_folder_ids`: a list of Google Drive folder IDs, where
      the file will be stored
    - `mimetype`:
    '''
    if mimetype is None:
        mimetype, _enc = mimetypes.guess_type(input_filename)
    body = {
        'name': os.path.basename(input_filename),
        'parents': parent_folder_ids,
    }
    if mimetype is not None:
        body['mimeType'] = mimetype

    with open(input_filename, 'rb') as input_file:
        req = drive_service.files().create(
            body=body,
            media_body=MediaIoBaseUpload(input_file, mimetype))
        response = req.execute()
    return response


# ============================================================
#  GOOGLE CLOUD STORAGE API
# ============================================================


# https://cloud.google.com/storage/docs/json_api/v1/json-api-python-samples
def storage_upload_object(storage_service, bucket, filename):
    '''
    Uploads a file from the local drive to the Google Cloud Storage.

    Arguments:
    - `storage_service`:
    - `bucket`:
    - `filename`:
    '''
    # This is the request body as specified:
    # http://g.co/cloud/storage/docs/json_api/v1/objects/insert#request
    body = {
        'name': os.path.basename(filename),
    }

    # Now insert them into the specified bucket as a media insertion.
    # http://g.co/dv/resources/api-libraries/documentation/storage/v1/python/latest/storage_v1.objects.html#insert
    with open(filename, 'rb') as input_file:
        req = storage_service.objects().insert(
            bucket=bucket, body=body,
            # You can also just set media_body=filename, but for the sake of
            # demonstration, pass in the more generic file handle, which could
            # very well be a StringIO or similar.
            media_body=MediaIoBaseUpload(input_file,
                                         'application/octet-stream'))
        resp = req.execute()

    return resp


# https://cloud.google.com/storage/docs/json_api/v1/json-api-python-samples
def storage_delete_object(storage_service, bucket, filename):
    '''
    Deletes a file from the Google Cloud Storage.

    Arguments:
    - `storage_service`:
    - `bucket`:
    - `filename`:
    '''
    req = storage_service.objects().delete(bucket=bucket,
                                           object=os.path.basename(filename))
    resp = req.execute()

    return resp


# ============================================================
#  GOOGLE CLOUD SPEECH API
# ============================================================


def submit_transcription_request(speech_service, bucket, filename,
                                 phrases=None):
    '''
    Submits a job to the Google Cloud Speech API for asynchronous
    speech transcription.

    Arguments:
    - `speech_service`:
    - `bucket`:
    - `filename`: the (basename) of the audio file on Google cloud
      storage to recognise
    - `phrases`: if specified, a list of words or phrases which Google
      should respect in the given audio data
    '''
    speech_file = 'gs://{}/{}'.format(bucket, os.path.basename(filename))
    body = {
        'config': {
            # There are a bunch of config options you can specify. See
            # https://goo.gl/KPZn97 for the full list.
            'encoding': 'LINEAR16',  # raw 16-bit signed LE samples
            'sampleRateHertz': 16000,  # 16 khz
            # See https://goo.gl/A9KJ1A for a list of supported languages.
            'languageCode': 'en-US',  # a BCP-47 language tag
        },
        'audio': {
            'uri': speech_file
        }
    }
    if phrases is not None:
        body['config']['speech_contexts'] = {}
        body['config']['speech_contexts']['phrases'] = phrases
    service_request = speech_service.speech().longrunningrecognize(body=body)
    response = service_request.execute()
    return response


def poll_transcription_results(speech_service, name):
    '''
    Polls the Google speech recognition service to determine the state
    of a given speech recognition job.

    Arguments:
    - `speech_service`:
    - `name`: the ID of the speech recognition job
    '''
    # Construct a GetOperation request.
    service_request = speech_service.operations().get(name=name)
    return service_request.execute()


# ============================================================
#  LOCAL FILE MANAGEMENT AND SUBPROCESSING
# ============================================================


def mkdir_p(path):
    '''
    Functionality similar to mkdir -p.
    '''
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def local_input_file_path(filename):
    '''
    Returns the path on the local drive where audio recording files
    are downloaded to.

    Arguments:
    - `filename`: the filename of an audio recording file; this file
      may be in a variety of formats (e.g., AMR, WAV, M4A, etc.)
    '''
    path = os.path.join(APP_CACHE_DIR, 'amr_files')
    mkdir_p(path)
    return os.path.join(path, os.path.basename(filename))


def local_wav_path(filename):
    '''
    Returns the path on the local drive where WAV files are stored.

    Arguments:
    - `filename`: the filename of the audio recording file
    '''
    path = os.path.join(APP_CACHE_DIR, 'wav_files')
    mkdir_p(path)
    return os.path.join(path,
                        os.path.splitext(os.path.basename(filename))[0] +
                        '.wav')


def local_trimmed_wav_path(filename):
    '''
    Returns the path on the local drive where trimmed WAV files are
    stored.

    Arguments:
    - `filename`: the filename of the audio recording file
    '''
    path = os.path.join(APP_CACHE_DIR, 'trimmed_wav_files')
    mkdir_p(path)
    return os.path.join(path,
                        os.path.splitext(os.path.basename(filename))[0] +
                        '.wav')


def local_transcription_path(filename):
    '''
    Returns the path on the local drive where transcribed TXT files
    are stored.

    Arguments:
    - `filename`: the filename of the audio recording file
    '''
    path = os.path.join(APP_CACHE_DIR, 'transcriptions')
    mkdir_p(path)
    return os.path.join(path,
                        os.path.splitext(os.path.basename(filename))[0] +
                        '.txt')


FFMPEG = subprocess.check_output(['which', 'ffmpeg']).strip()


def convert_input_to_wav(input_filename, wav_filename):
    '''
    Converts an audio recording file into a WAV file using ffmpeg.
    The original audio recording file may be in a variety of formats
    (e.g., AMR, WAV, M4A, etc.).  Ffmpeg is used to convert between
    these possible input formats and PCM16 WAV files, which are used
    by this program internally.

    Arguments:
    - `input_filename`:
    - `wav_filename`:
    '''
    subprocess.call([FFMPEG, '-i', input_filename, wav_filename])


SOX = subprocess.check_output(['which', 'sox']).strip()


def trim_silence(input_wav_filename, output_wav_filename):
    '''
    Trims silence from a WAV file using sox.

    Arguments:
    - `input_wav_filename`:
    - `output_wav_filename`:
    '''
    silence_threshold = '0.1%'
    ignore_bursts_secs = '0.1'
    minimum_silence_secs = '2.0'
    # http://unix.stackexchange.com/questions/293376/remove-silence-from-audio-files-while-leaving-gaps
    subprocess.call([SOX, input_wav_filename, output_wav_filename,
                     'silence', '-l',
                     '1', ignore_bursts_secs, silence_threshold,
                     '-1', minimum_silence_secs, silence_threshold])


# ============================================================
#  PROGRAM LOGIC
# ============================================================


class LoopAction(object):
    '''An action which runs in the polling loop.'''

    def __init__(self, pstorage, services, poll_loop):
        '''Constructor.'''
        self.pstorage = pstorage
        self.services = services
        self.poll_loop = poll_loop
        self.next_tick_time = time.time() - 1

    def __str__(self):
        return '<LoopAction>'

    def tick(self):
        '''Tick method'''
        pass

    def should_tick(self):
        '''
        Predicate function to see if this poll loop action should run now.
        '''
        return self.next_tick_time < time.time()

    def set_next_tick(self, wait_time_secs):
        '''
        Set the next tick time to be `wait_time_secs` in the future.
        '''
        self.next_tick_time = time.time() + wait_time_secs

    def identity(self, job_id):
        '''Identity predicate: returns True if this job is `job_id`.'''
        return False


# interpret timestamps on file objects:
#
# import iso8601
# dt = iso8601.parse_date(rs['files'][2]['modifiedTime'])
# import pytz
# datetime.datetime.now(tz=pytz.utc) > dt


class DriveMonitorAction(LoopAction):
    '''Monitor the Google Drive folder and create new jobs.'''

    def __init__(self, pstorage, services, poll_loop, folder_name):
        '''Constructor.'''
        super(DriveMonitorAction, self).__init__(pstorage, services, poll_loop)
        self.folder_name = folder_name
        self.folder_id = None

    def __str__(self):
        return '<DriveMonitor folder={}>'.format(self.folder_name)

    def tick(self):
        '''Tick method'''
        if not self.should_tick():
            return False
        self.set_next_tick(30)  # 30 seconds between checking drive
        # cache the folder ID
        if self.folder_id is None:
            self.folder_id = drive_get_folder_id(self.services['drive'],
                                                 self.folder_name)
        if self.folder_id is None:
            logger.fatal('Could not find Google Drive folder "%s"',
                         self.folder_name)
            raise Exception(
                'ERROR: could not find Google Drive folder "{}"'.format(
                    self.folder_name))
        # refresh the list of files in the google drive
        logger.info('Checking Google Drive ...')
        try:
            results = drive_list_most_recent_files(self.services['drive'],
                                                   self.folder_id)
        except socket.error:
            logger.warning('socket.error')
            results = {}
        if 'files' not in results:
            return False
        # update the persistent storage
        self.pstorage['drive_files'] = results['files']
        # create new jobs
        if 'jobs' not in self.pstorage:
            self.pstorage['jobs'] = {}
        num_created = 0
        for dfile in self.pstorage['drive_files']:
            if dfile['name'] not in self.pstorage['jobs']:
                job = TranscriptionJobAction(self.pstorage, self.services,
                                             self.poll_loop,
                                             dfile['name'])
                if job.initialised:
                    self.poll_loop.append(job)
                    num_created += 1
        if num_created:
            logger.info('Drive Monitor created %d new jobs', num_created)
        # done
        return False


class TranscriptionJobAction(LoopAction):
    '''Monitor the Google Drive folder and create new jobs.'''

    def __init__(self, pstorage, services, poll_loop, job_name):
        '''Constructor.'''
        super(TranscriptionJobAction, self).__init__(pstorage, services,
                                                     poll_loop)
        self.job_name = job_name
        if 'jobs' not in self.pstorage:
            self.pstorage['jobs'] = {}
        self.initialised = True
        # check for a job record in the pstorage
        if self.job_name in self.pstorage['jobs']:
            self.job_record = self.pstorage['jobs'][self.job_name]
        else:
            logger.info('Initialising job %s', self.job_name)
            idx = [i for i, dfile in enumerate(pstorage['drive_files'])
                   if dfile['name'] == self.job_name]
            if not idx:
                logger.error(
                    'Could not retrieve Google Drive file ID for file "%s"',
                    self.job_name)
                self.initialised = False
                return
            idx = idx[0]
            self.job_record = {
                'storage_id': 'unknown',
                'state': 'uploaded',
                'drive_id': pstorage['drive_files'][idx]['id'],
                'drive_parents': pstorage['drive_files'][idx]['parents'],
            }
            self.pstorage['jobs'][self.job_name] = self.job_record
            self.pstorage.save()

    def __str__(self):
        return '<Transcribe name={} state={}>'.format(self.job_name,
                                                      self.job_record['state'])

    def identity(self, job_id):
        '''Identity predicate: returns True if this job is `job_id`.'''
        return job_id == self.job_name

    def tick(self):
        '''Tick method'''
        if not self.should_tick():
            return False
        current_state = self.job_record['state']
        state_idx = [i for i, (x, _y) in enumerate(TRANSCRIPTION_JOB_STATES)
                     if x == current_state]
        if not state_idx:
            logger.error('Cannot interpret TranscriptionJob state %s',
                         current_state)
            return False
        state_idx = state_idx[0]
        state_action = TRANSCRIPTION_JOB_STATES[state_idx][1]
        if state_idx < len(TRANSCRIPTION_JOB_STATES) - 1:
            next_state = TRANSCRIPTION_JOB_STATES[state_idx + 1][0]
        else:
            next_state = current_state
        if state_action is not None:
            return state_action(self, next_state)
        return False

    def download(self, next_state):
        '''
        State machine action to download the original audio recording file
        for this job.
        '''
        logger.info('Downloading %s', str(self))
        drive_download_file(self.services['drive'],
                            self.job_record['drive_id'],
                            local_input_file_path(self.job_name), True)
        time.sleep(0.5)
        # TODO: check that operation succeeded
        self.job_record['state'] = next_state
        self.pstorage.save()
        return True

    def transcode_to_wav(self, next_state):
        '''
        State machine action to convert an original audio recording file
        to a WAV file.  Audio recordings may be input to this program
        in a variety of audio formats (e.g., AMR, WAV).  This step
        ensures that they are in WAV format for future processing
        steps.
        '''
        logger.info('Transcoding to wav %s', str(self))
        convert_input_to_wav(local_input_file_path(self.job_name),
                             local_wav_path(self.job_name))
        # TODO: check that operation succeeded
        self.job_record['state'] = next_state
        self.pstorage.save()
        return True

    def trim_wav(self, next_state):
        '''
        State machine action to trim silence from a WAV file.
        '''
        logger.info('Trimming wav %s', str(self))
        trim_silence(local_wav_path(self.job_name),
                     local_trimmed_wav_path(self.job_name))
        # TODO: check that operation succeeded
        self.job_record['state'] = next_state
        self.pstorage.save()
        return True

    def upload_to_cloud(self, next_state):
        '''
        State machine action to upload a WAV file to Google Cloud Storage.
        '''
        logger.info('Uploading to cloud storage %s', str(self))
        filename = local_trimmed_wav_path(self.job_name)
        try:
            response = storage_upload_object(self.services['storage'], BUCKET,
                                             filename=filename)
        except socket.error:
            logger.warning('socket.error')
            response = None
        time.sleep(0.5)
        if response:
            if os.stat(filename).st_size == int(response['size']):
                self.job_record['state'] = next_state
                self.pstorage.save()
                return True
        self.set_next_tick(5)
        return False

    def submit_to_speech_api(self, next_state):
        '''
        State machine action to submit a speech recognition request to the
        Google Cloud Speech API.
        '''
        logger.info('Submitting to speech API %s', str(self))
        filename = local_trimmed_wav_path(self.job_name)
        phrases = ["semantics", "representation", "representational",
                   "denotation",
                   "denotational", "reference", "referential"]
        try:
            response = submit_transcription_request(self.services['speech'],
                                                    BUCKET,
                                                    filename, phrases=phrases)
            time.sleep(0.5)
        except socket.error:
            logger.warning('socket.error')
            response = None
        self.set_next_tick(15)
        if response is not None and 'name' in response:
            self.job_record['storage_id'] = response['name']
            self.job_record['state'] = next_state
            self.pstorage.save()
            return False
        return False

    def poll_speech_api(self, next_state):
        '''
        State machine action to check to see if the Google Cloud Speech
        API has finished transcribing this job.
        '''
        try:
            response = poll_transcription_results(
                self.services['speech'], self.job_record['storage_id'])
            time.sleep(0.5)
        except socket.error:
            logger.warning('socket.error')
            response = {}
        if 'done' in response and response['done']:
            logger.info('Speech API finished %s', str(self))
            local_path = local_transcription_path(self.job_name)
            with open(local_path, 'w') as output_file:
                for result in response['response']['results']:
                    output_file.write(result['alternatives'][0]['transcript'] +
                                      "\n")
            self.job_record['state'] = next_state
            self.pstorage.save()
            return True
        self.set_next_tick(10)
        return False

    def save_transcription(self, next_state):
        '''
        State machine action to upload the transcription in TXT file
        format to the user's Google Drive.
        '''
        logger.info('Uploading transcription to google drive %s', str(self))
        filename = local_transcription_path(self.job_name)
        try:
            response = drive_upload_file(self.services['drive'], filename,
                                         self.job_record['drive_parents'],
                                         'text/plain')
            time.sleep(0.5)
        except socket.error:
            logger.warning('socket.error')
            response = {}
        if 'id' in response:
            self.job_record['state'] = next_state
            self.pstorage.save()
            return True
        self.set_next_tick(10)
        return False

    def clean_cloud(self, next_state):
        '''
        Delete a WAV file from the Google Cloud Storage.
        '''
        logger.info('Deleting from cloud %s', str(self))
        filename = local_trimmed_wav_path(self.job_name)
        try:
            storage_delete_object(self.services['storage'], BUCKET, filename)
        except socket.error:
            logger.warning('socket.error')
            return True
        time.sleep(0.5)
        # response seems to be always empty
        self.job_record['state'] = next_state
        self.pstorage.save()
        return True

    def destruct(self, next_state):
        '''
        State machine action to clean up this job and remove it from the
        poll loop.
        '''
        # empty, skip to done
        self.job_record['state'] = next_state
        self.pstorage.save()
        # remove self from poll loop
        idxs = [i for (i, j) in enumerate(self.poll_loop)
                if j.identity(self.job_name)]
        for idx in reversed(idxs):
            logger.info('Removing poll loop action: %s',
                        str(self.poll_loop[idx]))
            del self.poll_loop[idx]
        self.set_next_tick(30)
        return False


# Structure to document the order of states in a
# TranscriptionJobAction, and indicate the transition actions between
# them
TRANSCRIPTION_JOB_STATES = [
    ('uploaded', TranscriptionJobAction.download),
    ('downloaded', TranscriptionJobAction.transcode_to_wav),
    ('wav', TranscriptionJobAction.trim_wav),
    ('trimmed', TranscriptionJobAction.upload_to_cloud),
    ('stored', TranscriptionJobAction.submit_to_speech_api),
    ('submitted', TranscriptionJobAction.poll_speech_api),
    ('transcribed', TranscriptionJobAction.save_transcription),
    ('saved', TranscriptionJobAction.clean_cloud),
    ('cleaned', TranscriptionJobAction.destruct),
    ('done', None),
]


@click.command()
def main():
    '''
    Google Speech Transcription Service.

    This program is constructed like a daemon; it runs in a loop,
    checking the user's Google Drive folder, and transcribing any
    audio files which appear there.
    '''
    # load the persistent storage object
    mkdir_p(APP_CONFIG_DIR)
    pstorage = PersistentDict(os.path.join(APP_CONFIG_DIR, 'pstorage.json'))

    # create services
    services = {'drive': get_drive_service(),
                'storage': get_storage_service(),
                'speech': get_speech_service()}

    # construct the polling loop:
    poll_loop = []
    # google drive monitor
    poll_loop.append(DriveMonitorAction(pstorage, services, poll_loop,
                                        FOLDER_NAME))
    if 'jobs' not in pstorage:
        pstorage['jobs'] = {}
    # any (unfinished) jobs
    poll_loop.extend([TranscriptionJobAction(pstorage, services, poll_loop,
                                             job_name)
                      for job_name in pstorage['jobs'].keys()])

    # polling loop:
    while True:
        # tick all the jobs in the loop (jobs manage their own timing
        # independently)
        for job in poll_loop:
            while job.tick():
                pass
        # wait
        time.sleep(1)


if __name__ == '__main__':
    main()
