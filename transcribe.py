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
"""Google Cloud Speech API sample application using the REST API for async
batch processing."""

import argparse
import base64
import json
import time
import os
from googleapiclient import discovery
import httplib2
from oauth2client.client import GoogleCredentials

def get_authorised_http():
    # Application default credentials provided by env variable
    # GOOGLE_APPLICATION_CREDENTIALS
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials/semantics-exam-marking.json'
    credentials = GoogleCredentials.get_application_default().create_scoped(
        ['https://www.googleapis.com/auth/cloud-platform'])
    http = httplib2.Http()
    credentials.authorize(http)
    return http

def main(speech_file):
    """Transcribe the given audio file asynchronously.
    Args:
        speech_file: the name of the audio file.
    """

    #if speech_file.endswith('.amr'):
    #    amr_filename = speech_file
    #    wav_filename = amr_filename.replace('.amr', '.wav')
    #    os.system('/opt/local/bin/ffmpeg -i {} {}'.format(amr_filename, wav_filename))
    #    speech_file = wav_filename
    speech_file = 'gs://semantics-exam-marking.appspot.com/{}'.format(speech_file)

    # [START construct_request]
    #with open(speech_file, 'rb') as speech:
    #    # Base64 encode the binary audio file for inclusion in the request.
    #    speech_content = base64.b64encode(speech.read())

    http = get_authorised_http()
    service = discovery.build('speech', 'v1beta1', http=http)
    service_request = service.speech().asyncrecognize(
        body={
            'config': {
                # There are a bunch of config options you can specify. See
                # https://goo.gl/KPZn97 for the full list.
                'encoding': 'LINEAR16',  # raw 16-bit signed LE samples
                'sampleRate': 16000,  # 16 khz
                # See https://goo.gl/A9KJ1A for a list of supported languages.
                'languageCode': 'en-US',  # a BCP-47 language tag
                "speech_context": {
                    "phrases":["semantics","representation","representational","denotation","denotational","reference","referential"]
                }
            },
            'audio': {
                #'content': speech_content.decode('UTF-8')
                'uri': speech_file
            }
        })
    # [END construct_request]
    # [START send_request]
    response = service_request.execute()
    print(json.dumps(response))
    # [END send_request]

    name = response['name']

    # Construct a GetOperation request.
    service_request = service.operations().get(name=name)

    while True:
        # Give the server a few seconds to process.
        print('Waiting for server processing...')
        time.sleep(2)
        # Get the long running operation with response.
        response = service_request.execute()

        if 'done' in response and response['done']:
            break

    #print(json.dumps(response['response']['results']))

    #import pdb ; pdb.set_trace()

    for x in response['response']['results']:
        print x['alternatives'][0]['transcript']


# [START run_application]
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'speech_file', help='Full path of audio file to be recognized')
    args = parser.parse_args()
    main(args.speech_file)
