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

from apiclient.http import MediaIoBaseDownload
from googleapiclient import discovery
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage
import httplib2
import json

# persistance
def store_data(json_filename, data):
    with open(json_filename, 'w') as output_file:
        output_file.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

def load_data(json_filename):
    with open(json_filename, 'r') as input_file:
        return json.loads(input_file.read().decode('utf-8'))

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
    folder_id = get_folder_id(service, 'Exams')
    if folder_id is None:
        print 'ERROR: could not find Google Drive folder "Exams"'
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
    with open(output_filename, 'w') as output_file:
        downloader = MediaIoBaseDownload(output_file, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            if verbose:
                print "Download %d%%." % int(status.progress() * 100)

#download_file(service, results['files'][0]['id'], os.path.join('amr_files', results['files'][0]['name']), True)

# [START run_application]
if __name__ == '__main__':
    main()
