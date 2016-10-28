#!/usr/bin/env python
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

from apiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from googleapiclient import discovery
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage
import httplib2
import os
import subprocess

# interpret timestamps on file objects:
#
# import iso8601
# dt = iso8601.parse_date(rs['files'][2]['modifiedTime'])
# import pytz
# datetime.datetime.now(tz=pytz.utc) > dt

def get_drive_service():
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

def get_folder_id(drive_service, folder_name):
    results = drive_service.files().list(
        pageSize=100,
        q="mimeType = 'application/vnd.google-apps.folder' and name='{}'".format(folder_name),
        spaces='drive',
        corpus='user',
        fields="files(id)").execute()
    if not results or not 'files' in results or not results['files']:
        return None
    return results['files'][0]['id']

def main():
    """Transcribe the given audio file asynchronously.
    Args:
        speech_file: the name of the audio file.
    """
    service = get_drive_service()
    folder_name = 'Exams'
    folder_id = get_folder_id(service, folder_name)
    if folder_id is None:
        print 'ERROR: could not find Google Drive folder "{}"'.format(folder_name)
        return
    results = service.files().list(
        pageSize=100,
        orderBy='modifiedTime desc',
        q="'{}' in parents".format(folder_id),
        spaces='drive',
        corpus='user',
        fields="nextPageToken, files(id, mimeType, modifiedTime, name)").execute()

def download_file(drive_service, file_id, output_filename, verbose = False):
    request = drive_service.files().get_media(fileId = file_id)
    with open(output_filename, 'wb') as output_file:
        downloader = MediaIoBaseDownload(output_file, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            if verbose:
                print "Download %d%%." % int(status.progress() * 100)

def run_command(args):
    return subprocess.call(args)

def local_amr_path(filename):
    return os.path.join('amr_files', filename)

def local_wav_path(filename):
    return os.path.join('wav_files', filename.replace('.amr', '.wav'))

#download_file(service, results['files'][0]['id'], local_amr_path(results['files'][0]['name']), True)
FFMPEG = subprocess.check_output(['which', 'ffmpeg']).strip()
#run_command([FFMPEG, '-i', local_amr_path(results['files'][0]['name']), local_wav_path(results['files'][0]['name'])])
SOX = subprocess.check_output(['which', 'sox']).strip()
# sox trim-silence.wav trim-silence-out.wav silence -l 1 0.1 0.1% -1 2.0 0.1%

def get_cloud_storage_service():
    http = get_service_acct_authorised_http()
    return discovery.build('storage', 'v1', http=http)

# https://cloud.google.com/storage/docs/json_api/v1/json-api-python-samples
def cloud_upload_object(bucket, filename):
    service = get_cloud_storage_service()

    # This is the request body as specified:
    # http://g.co/cloud/storage/docs/json_api/v1/objects/insert#request
    body = {
        'name': os.path.basename(filename),
    }

    # Now insert them into the specified bucket as a media insertion.
    # http://g.co/dv/resources/api-libraries/documentation/storage/v1/python/latest/storage_v1.objects.html#insert
    with open(filename, 'rb') as input_file:
        req = service.objects().insert(
            bucket=bucket, body=body,
            # You can also just set media_body=filename, but for the sake of
            # demonstration, pass in the more generic file handle, which could
            # very well be a StringIO or similar.
            media_body=MediaIoBaseUpload(input_file, 'application/octet-stream'))
        resp = req.execute()
        
    return resp

# https://cloud.google.com/storage/docs/json_api/v1/json-api-python-samples
def cloud_delete_object(bucket, filename):
    service = get_cloud_storage_service()

    req = service.objects().delete(bucket=bucket, object=filename)
    resp = req.execute()

    return resp

filename= 'amr_files/report3.amr'
bucket = 'semantics-exam-marking.appspot.com'
os.stat(filename).st_size == int(resp['size'])


# [START run_application]
if __name__ == '__main__':
    main()
