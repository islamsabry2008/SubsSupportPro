# -*- coding: utf-8 -*-
'''
Created on Aug 2, 2014

@author: marko
'''
from __future__ import absolute_import
from __future__ import print_function

import sys
import json
import time
import traceback

try:
    import six
except Exception:
    six = None

stdout = None


class Messages(object):
    MESSAGE_CAPTCHA_CALLBACK = 1
    MESSAGE_UPDATE_CALLBACK = 2
    MESSAGE_DELAY_CALLBACK = 3
    MESSAGE_CANCELLED_SCRIPT = 4
    MESSAGE_FINISHED_SCRIPT = 5
    MESSAGE_ERROR_SCRIPT = 6
    MESSAGE_CHOOSE_FILE_CALLBACK = 7
    MESSAGE_OVERWRITE_CALLBACK = 8


def _json_safe(value):
    """Return a json.dumps-safe value on both Python 2 and Python 3."""
    try:
        string_types = six.string_types if six is not None else (str,)
        text_type = six.text_type if six is not None else str
        binary_type = six.binary_type if six is not None else bytes
    except Exception:
        string_types = (str,)
        text_type = str
        binary_type = bytes

    if value is None or isinstance(value, (bool, int, float)):
        return value

    # Python 2: keep unicode as unicode, decode byte strings where possible.
    if six is not None and six.PY2:
        if isinstance(value, text_type):
            return value
        if isinstance(value, binary_type):
            try:
                return value.decode('utf-8')
            except Exception:
                return value.decode('utf-8', 'ignore')
    else:
        if isinstance(value, binary_type):
            try:
                return value.decode('utf-8', 'ignore')
            except Exception:
                return str(value)
        if isinstance(value, text_type):
            return value

    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return dict((_json_safe(k), _json_safe(v)) for k, v in value.items())

    # Exceptions/custom objects are not JSON serializable. Send readable text.
    try:
        if six is not None and six.PY2:
            return text_type(value)
        return str(value)
    except Exception:
        return ""


def send(mtype, m):
    dump = json.dumps({'message': mtype, 'value': _json_safe(m)})
    dump = "%07d%s" % (len(dump) + 7, dump)
    stdout.write(dump)
    stdout.flush()


def recieve():
    return json.loads(sys.stdin.read(int(sys.stdin.read(7))))


def delayCB(seconds):
    send(Messages.MESSAGE_DELAY_CALLBACK, seconds)
    recieve()


def captchaCB(image):
    send(Messages.MESSAGE_CAPTCHA_CALLBACK, image)
    return recieve()


def messageCB(text):
    print('messageCB:', text)


def updateCB(*args):
    send(Messages.MESSAGE_UPDATE_CALLBACK, args)


def chooseFileCB(*args):
    send(Messages.MESSAGE_CHOOSE_FILE_CALLBACK, args)
    return recieve()


def overwriteFileCB(*args):
    send(Messages.MESSAGE_OVERWRITE_CALLBACK, args)
    return recieve()


def scriptError(e):
    try:
        from .seekers.seeker import SubtitlesErrors, BaseSubtitlesError
    except (ValueError, ImportError):
        from seekers.seeker import SubtitlesErrors, BaseSubtitlesError
    if isinstance(e, BaseSubtitlesError):
        send(Messages.MESSAGE_ERROR_SCRIPT, {'error_code': e.code, 'provider': e.provider})
    else:
        send(Messages.MESSAGE_ERROR_SCRIPT, {'error_code': SubtitlesErrors.UNKNOWN_ERROR, 'provider': ''})


def scriptFinished(subtitlesDict):
    send(Messages.MESSAGE_FINISHED_SCRIPT, subtitlesDict)


def scriptCancelled(subtitlesDict):
    send(Messages.MESSAGE_CANCELLED_SCRIPT, subtitlesDict)


def searchSubtitles(seeker, options):
    seekers = options.get('providers')
    title = options.get('title')
    filepath = options.get('filepath')
    langs = options.get('langs')
    year = options.get('year')
    tvshow = options.get('tvshow')
    season = options.get('season')
    episode = options.get('episode')
    timeout = options.get('timeout', 10)
    return seeker.getSubtitles(seekers, updateCB, title, filepath, langs, year, tvshow, season, episode, timeout)


def downloadSubtitles(seeker, options):
    overwriteFileCBTmp = None
    if options.get('settings').get('ask_overwrite'):
        overwriteFileCBTmp = overwriteFileCB

    return seeker.downloadSubtitle(
        options.get("selected_subtitle"),
        options.get("subtitles_dict"),
        chooseFileCB,
        options.get("path"),
        options.get("filename"),
        overwriteFileCBTmp,
        options.get("settings"))


def main():
    global stdout
    stdout = sys.stdout
    try:
        sys.stdout = open('/tmp/subssupportpro.log', 'w', 1)
    except TypeError:
        sys.stdout = open('/tmp/subssupportpro.log', 'w')
    sys.stderr = sys.stdout
    options = recieve()
    print('recieved options: %r' % options)
    try:
        sys.stdout.flush()
    except Exception:
        pass
    try:
        from .seek import SubsSeeker
    except (ValueError, ImportError):
        from seek import SubsSeeker
    seeker = SubsSeeker(options.get('download_path', '/tmp/'),
                        options.get('tmp_path', '/tmp/'),
                        captchaCB, delayCB, messageCB,
                        options.get('settings'))
    if options.get('search'):
        return searchSubtitles(seeker, options['search'])
    elif options.get('download'):
        return downloadSubtitles(seeker, options['download'])


if __name__ == '__main__':
    try:
        scriptFinished(main())
        stdout.close()
        sys.stdout.close()
        sys.exit(0)
    except KeyboardInterrupt:
        scriptCancelled({})
        stdout.close()
        sys.stdout.flush()
        sys.stdout.close()
        sys.exit(0)
    except Exception as e:
        traceback.print_exc()
        scriptError(e)
        stdout.close()
        sys.stdout.close()
        sys.exit(1)
