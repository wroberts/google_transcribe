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

"""
Google Cloud Speech API sample application using the REST API for
async batch processing.
"""

import argparse
import os
import subprocess
import time
from apiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from googleapiclient import discovery
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage
import httplib2

# ============================================================
#  AUTHORISATION
# ============================================================

def get_drive_service():
    '''
    Returns an object used to interact with the Google Drive API.
    '''
    flow = client.flow_from_clientsecrets(
        'credentials/samarkand_secret.json',
        'https://www.googleapis.com/auth/drive.readonly')
    flow.user_agent = 'Samarkand'
    store = Storage('credentials/storage.dat')
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
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials/semantics-exam-marking.json'
    credentials = client.GoogleCredentials.get_application_default().create_scoped(
        ['https://www.googleapis.com/auth/cloud-platform'])
    http = httplib2.Http()
    credentials.authorize(http)
    return http

def get_cloud_storage_service():
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
    service = discovery.build('speech', 'v1beta1', http=http)
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
        q="mimeType = 'application/vnd.google-apps.folder' and name='{}'".format(folder_name),
        spaces='drive',
        corpus='user',
        fields="files(id)").execute()
    if not results or not 'files' in results or not results['files']:
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
    results = drive_service.files().list(
        pageSize=100,
        orderBy='modifiedTime desc',
        q="'{}' in parents".format(folder_id),
        spaces='drive',
        corpus='user',
        fields="nextPageToken, files(id, mimeType, modifiedTime, name)").execute()
    return results

def drive_download_file(drive_service, file_id, output_filename, verbose = False):
    '''
    Downloads the file with the given file ID on the user's Google
    Drive to the local file with the path `output_filename`.

    Arguments:
    - `drive_service`:
    - `file_id`:
    - `output_filename`:
    - `verbose`:
    '''
    request = drive_service.files().get_media(fileId = file_id)
    with open(output_filename, 'wb') as output_file:
        downloader = MediaIoBaseDownload(output_file, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            if verbose:
                print "Download %d%%." % int(status.progress() * 100)

# ============================================================
#  GOOGLE CLOUD STORAGE API
# ============================================================

# https://cloud.google.com/storage/docs/json_api/v1/json-api-python-samples
def cloud_upload_object(cloud_service, bucket, filename):
    '''
    Uploads a file from the local drive to the Google Cloud Storage.

    Arguments:
    - `cloud_service`:
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
        req = cloud_service.objects().insert(
            bucket=bucket, body=body,
            # You can also just set media_body=filename, but for the sake of
            # demonstration, pass in the more generic file handle, which could
            # very well be a StringIO or similar.
            media_body=MediaIoBaseUpload(input_file, 'application/octet-stream'))
        resp = req.execute()

    return resp

# https://cloud.google.com/storage/docs/json_api/v1/json-api-python-samples
def cloud_delete_object(cloud_service, bucket, filename):
    '''
    Deletes a file from the Google Cloud Storage.

    Arguments:
    - `cloud_service`:
    - `bucket`:
    - `filename`:
    '''
    req = cloud_service.objects().delete(bucket=bucket, object=os.path.basename(filename))
    resp = req.execute()

    return resp

# ============================================================
#  GOOGLE CLOUD SPEECH API
# ============================================================

def submit_transcription_request(speech_service, bucket, filename, phrases = None):
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
            'sampleRate': 16000,  # 16 khz
            # See https://goo.gl/A9KJ1A for a list of supported languages.
            'languageCode': 'en-US',  # a BCP-47 language tag
        },
        'audio': {
            'uri': speech_file
        }
    }
    if phrases is not None:
        body['config']['speech_context'] = {}
        body['config']['speech_context']['phrases'] = phrases
    service_request = speech_service.speech().asyncrecognize(body=body)
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

def local_amr_path(filename):
    '''
    Returns the path on the local drive where AMR files are downloaded to.

    Arguments:
    - `filename`: the basename of an AMR file
    '''
    return os.path.join('amr_files', os.path.basename(filename))

def local_wav_path(filename):
    '''
    Returns the path on the local drive where WAV files are stored.

    Arguments:
    - `filename`: the basename of an AMR file
    '''
    return os.path.join('wav_files',
                        os.path.basename(filename).replace('.amr', '.wav'))

def local_trimmed_wav_path(filename):
    '''
    Returns the path on the local drive where trimmed WAV files are stored.

    Arguments:
    - `filename`: the basename of an AMR file
    '''
    return os.path.join('trimmed_wav_files',
                        os.path.basename(filename).replace('.amr', '.wav'))

FFMPEG = subprocess.check_output(['which', 'ffmpeg']).strip()
def convert_amr_to_wav(amr_filename, wav_filename):
    '''
    Converts an AMR file into a WAV file using ffmpeg.

    Arguments:
    - `amr_filename`:
    - `wav_filename`:
    '''
    subprocess.call([FFMPEG, '-i', amr_filename, wav_filename])

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
    subprocess.call([SOX, input_wav_filename, output_wav_filename,
                     'silence', '-l',
                     '1', ignore_bursts_secs, silence_threshold,
                     '-1', minimum_silence_secs, silence_threshold])

# ============================================================
#  NOTES
# ============================================================

#drive_download_file(service, results['files'][0]['id'], local_amr_path(results['files'][0]['name']), True)
#convert_amr_to_wav(local_amr_path(results['files'][0]['name']), local_wav_path(results['files'][0]['name']))
#trim_silence(local_wav_path(results['files'][0]['name']), local_trimmed_wav_path(results['files'][0]['name']))

#filename= 'amr_files/report3.amr'
#bucket = 'semantics-exam-marking.appspot.com'
#response = cloud_upload_object(cloud_service, bucket, filename)
#os.stat(filename).st_size == int(response['size'])

# interpret timestamps on file objects:
#
# import iso8601
# dt = iso8601.parse_date(rs['files'][2]['modifiedTime'])
# import pytz
# datetime.datetime.now(tz=pytz.utc) > dt

# service = get_drive_service()
# folder_name = 'Exams'
# folder_id = get_folder_id(service, folder_name)
# if folder_id is None:
#     print 'ERROR: could not find Google Drive folder "{}"'.format(folder_name)
#     return
# results = list_most_recent_files(drive_service, folder_id)

# ============================================================
#  MAIN FUNCTION
# ============================================================

def main(bucket, filename):
    """Transcribe the given audio file asynchronously.
    Args:
        filename: the name of the audio file.
    """

    service = get_speech_service()
    phrases = ["semantics"," representation", "representational", "denotation",
               "denotational", "reference", "referential"]
    response = submit_transcription_request(service, bucket, filename, phrases = phrases)
    #print(json.dumps(response))
    name = response['name']

    while True:
        # Give the server a few seconds to process.
        print('Waiting for server processing...')
        time.sleep(2)
        # Get the long running operation with response.
        response = poll_transcription_results(service, name)

        if 'done' in response and response['done']:
            break

    for x in response['response']['results']:
        print x['alternatives'][0]['transcript']

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'speech_file', help='Full path of audio file to be recognized')
    args = parser.parse_args()
    main('semantics-exam-marking.appspot.com', args.speech_file)
