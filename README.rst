=====================================
 Google Speech Transcription Service
=====================================

Setup
=====

google-transcribe needs to be able to find two files containing
credentials information to allow the use of the Google Cloud services.
These are stored in a platform-specific directory, and you should be
careful of permissions, so as not to make it too easy for these to be
stolen.

On Mac OS X, create the directory like this::

    mkdir -p ~/Library/Application\ Support/google-transcribe/1.0/credentials/
    chmod 700 ~/Library/Application\ Support/google-transcribe/1.0/credentials/

On Linux::

    mkdir -p ~/.config/google-transcribe/1.0/credentials/
    chmod 700 ~/.config/google-transcribe/1.0/credentials/

Two credentials files are needed: an OAuth 2.0 client ID, which should
be stored as ``secret.json``, and a Google Cloud Service account key,
which shoud be stored as ``semantics-exam-marking.json``.  Ideally,
``chmod`` these files to be ``600``.

- `Setting up OAuth 2.0`_
- `Set up a service account`_

.. _Setting up OAuth 2.0 : https://support.google.com/cloud/answer/6158849?hl=en
.. _Set up a service account : https://cloud.google.com/natural-language/docs/common/auth#set_up_a_service_account
