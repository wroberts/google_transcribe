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

from googleapiclient import discovery
from oauth2client.client import GoogleCredentials
import argparse
import httplib2
import os
import time

def get_service_acct_authorised_http():
    '''
    Returns an HTTP connection object which is authorised using this
    app's Google Service Account.
    '''
    # Application default credentials provided by env variable
    # GOOGLE_APPLICATION_CREDENTIALS
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials/semantics-exam-marking.json'
    credentials = GoogleCredentials.get_application_default().create_scoped(
        ['https://www.googleapis.com/auth/cloud-platform'])
    http = httplib2.Http()
    credentials.authorize(http)
    return http

def get_speech_service():
    '''
    Returns an object used to interact with the Google Cloud Speech API.
    '''
    http = get_service_acct_authorised_http()
    service = discovery.build('speech', 'v1beta1', http=http)
    return service

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
    speech_file = 'gs://{}/{}'.format(bucket, filename)
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
