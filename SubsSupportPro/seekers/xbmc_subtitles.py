# -*- coding: utf-8 -*-
'''
Created on Feb 10, 2014

@author: marko
'''
from __future__ import absolute_import
import os, re
import json
import time
import six
from .seeker import BaseSeeker
from .utilities import languageTranslate, allLang, toString

from . import _

class XBMCSubtitlesAdapter(BaseSeeker):
    module = None

    def __init__(self, tmp_path, download_path, settings=None, settings_provider=None, captcha_cb=None, delay_cb=None, message_cb=None):
        assert self.module is not None, 'you have to provide xbmc-subtitles module'
        logo = os.path.join(os.path.dirname(self.module.__file__), 'logo.png')
        BaseSeeker.__init__(self, tmp_path, download_path, settings, settings_provider, logo)
        self.module.captcha_cb = captcha_cb
        self.module.delay_cb = delay_cb
        self.module.message_cb = message_cb
        if len(self.supported_langs) == 1:
            self.lang1 = self.lang2 = self.lang3 = languageTranslate(self.supported_langs[0], 2, 0)
        elif len(self.supported_langs) == 2:
            self.lang1 = languageTranslate(self.supported_langs[0], 2, 0)
            self.lang2 = languageTranslate(self.supported_langs[1], 2, 0)
            self.lang3 = self.lang1
        else:
            self.lang1 = languageTranslate(self.supported_langs[0], 2, 0)
            self.lang2 = languageTranslate(self.supported_langs[1], 2, 0)
            self.lang3 = languageTranslate(self.supported_langs[2], 2, 0)

    def _search(self, title, filepath, langs, season, episode, tvshow, year):
        file_original_path = filepath and filepath or ""
        title = title and title or file_original_path
        season = season if season else 0
        episode = episode if episode else 0
        tvshow = tvshow if tvshow else ""
        year = year if year else ""
        if len(langs) > 3:
            self.log.info('more then three languages provided, only first three will be selected')
        if len(langs) == 0:
            self.log.info('no languages provided will use default ones')
            lang1 = self.lang1
            lang2 = self.lang2
            lang3 = self.lang3
        elif len(langs) == 1:
            lang1 = lang2 = lang3 = languageTranslate(langs[0], 2, 0)
        elif len(langs) == 2:
            lang1 = lang3 = languageTranslate(langs[0], 2, 0)
            lang2 = languageTranslate(langs[1], 2, 0)
        elif len(langs) == 3:
            lang1 = languageTranslate(langs[0], 2, 0)
            lang2 = languageTranslate(langs[1], 2, 0)
            lang3 = languageTranslate(langs[2], 2, 0)
        self.log.info('using langs %s %s %s' % (toString(lang1), toString(lang2), toString(lang3)))
        self.module.settings_provider = self.settings_provider
        subtitles_list, session_id, msg = self.module.search_subtitles(file_original_path, title, tvshow, year, season, episode, set_temp=False, rar=False, lang1=lang1, lang2=lang2, lang3=lang3, stack=None)
        return {'list': subtitles_list, 'session_id': session_id, 'msg': msg}

    def _download(self, subtitles, selected_subtitle, path=None):
        subtitles_list = subtitles['list']
        session_id = subtitles['session_id']
        pos = subtitles_list.index(selected_subtitle)
        zip_subs = os.path.join(toString(self.tmp_path), toString(selected_subtitle['filename']))
        tmp_sub_dir = toString(self.tmp_path)
        if path is not None:
            sub_folder = toString(path)
        else:
            sub_folder = toString(self.tmp_path)
        self.module.settings_provider = self.settings_provider
        compressed, language, filepath = self.module.download_subtitles(subtitles_list, pos, zip_subs, tmp_sub_dir, sub_folder, session_id)
        if compressed != False:
            if compressed == True or compressed == "":
                compressed = "zip"
            else:
                compressed = filepath
            if not os.path.isfile(filepath):
                filepath = zip_subs
        else:
            if filepath:
                filepath = os.path.join(six.ensure_str(sub_folder), filepath)
        return compressed, language, filepath

    def close(self):
        try:
            del self.module.captcha_cb
            del self.module.message_cb
            del self.module.delay_cb
            del self.module.settings_provider
        except Exception:
            pass

################# providers #################

try:
    from .LocalDrive import localdrive
except ImportError as e:
    localdrive = e

class LocalDriveSeeker(XBMCSubtitlesAdapter):
    module = localdrive
    if isinstance(module, Exception):
        error, module = module, None
    id = 'localdrive'
    provider_name = 'LocalDrive'
    supported_langs = allLang()
    default_settings = {'LocalSearchPath': {'label': _("Search Path"), 'type': 'text', 'default': "/media/hdd/subs", 'pos': 0} }

try:
    from .Wyzie import wyzie
except ImportError as e:
    wyzie = e

class WyzieSeeker(XBMCSubtitlesAdapter):
    id = 'wyzie'
    module = wyzie
    if isinstance(module, Exception):
        error, module = module, None
    provider_name = 'Wyzie Subs'
    supported_langs = allLang()
    default_settings = {
        'Wyzie_API_KEY': {'label': "API_KEY", 'type': 'password', 'default': '', 'pos': 0}
    }
    movie_search = True
    tvshow_search = True

    def test_credentials(self):
        from twisted.internet import defer, threads

        def _api_test():
            api_key = self.settings_provider.getSetting("Wyzie_API_KEY")
            return self.module.test_api_key(api_key)

        deferred = defer.Deferred()
        d = threads.deferToThread(_api_test)
        d.addCallback(deferred.callback)
        d.addErrback(deferred.errback)
        return deferred

    def show_message(self, session, message, is_error=False):
        from Screens.MessageBox import MessageBox
        session.open(
            MessageBox,
            message,
            MessageBox.TYPE_ERROR if is_error else MessageBox.TYPE_INFO,
            timeout=10
        )

    def _search(self, title, filepath, langs, season, episode, tvshow, year):
        api_key = self.settings_provider.getSetting("Wyzie_API_KEY")
        if not api_key:
            return {
                'list': [],
                'session_id': "",
                'msg': _("Wyzie requires an API key")
            }
        return super(WyzieSeeker, self)._search(
            title, filepath, langs, season, episode, tvshow, year
        )

try:
    from .Subf2m import subf2m
except ImportError as e:
    subf2m = e

class Subf2mSeeker(XBMCSubtitlesAdapter):
    id = 'subf2m'
    module = subf2m
    if isinstance(module, Exception):
        error, module = module, None
    provider_name = 'Subf2m'
    supported_langs = allLang()
    default_settings = {}

try:
    from .Subsource import subsource
except ImportError as e:
    subsource = e
    
class SubsourceSeeker(XBMCSubtitlesAdapter):
    id = 'subsource'
    module = subsource
    if isinstance(module, Exception):
        error, module = module, None
    provider_name = 'Subsource'
    supported_langs = allLang()
    default_settings = {
        'SubSource_API_KEY': {'label': "API_KEY", 'type': 'text', 'default': '', 'pos': 2}
    }

    def test_credentials(self):
        """Test SubSource API key"""
        from twisted.internet import defer, threads
        import requests

        def _api_test():
            api_key = self.settings_provider.getSetting("SubSource_API_KEY")
            
            if not api_key:
                raise Exception(_("API key is required"))

            url = "https://api.subsource.net/api/v1/movies/78044"
            headers = {"X-API-Key": api_key}

            try:
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                if not data.get('success'):
                    raise Exception(_("API error: %s") % data.get('message', 'Unknown error'))
                
                return _("SubSource API key is valid and working")
            except Exception as e:
                raise Exception(_("API error"))

        deferred = defer.Deferred()
        d = threads.deferToThread(_api_test)
        d.addCallback(deferred.callback)
        d.addErrback(deferred.errback)
        return deferred

    def show_message(self, session, message, is_error=False):
        """Universal message display method"""
        from Screens.MessageBox import MessageBox
        try:
            session.open(
                MessageBox,
                message,
                MessageBox.TYPE_ERROR if is_error else MessageBox.TYPE_INFO,
                timeout=10
            )
        except Exception as e:
            print("Failed to show message:", str(e))

    def _search(self, title, filepath, langs, season, episode, tvshow, year):
        """Override search to include API key check"""
        api_key = self.settings_provider.getSetting("SubSource_API_KEY")
        
        if not api_key:
            return {
                'list': [],
                'session_id': "",
                'msg': _("SubSource_API_KEY requires an API key")
            }
            
        return super(SubsourceSeeker, self)._search(
            title, filepath, langs, season, episode, tvshow, year
        )

try:
    from .OpenSubtitles2 import opensubtitles2
except ImportError as e:
    opensubtitles2 = e

class OpenSubtitles2Seeker(XBMCSubtitlesAdapter):
    module = opensubtitles2
    if isinstance(module, Exception):
        error, module = module, None
    
    id = 'opensubtitles2'
    provider_name = 'OpenSubtitles'
    supported_langs = allLang()
    default_settings = {
        'OpenSubtitles_username': {'label': "USERNAME", 'type': 'text', 'default': "", 'pos': 0},
        'OpenSubtitles_password': {'label': "PASSWORD", 'type': 'password', 'default': "", 'pos': 1},
        'OpenSubtitles_API_KEY': {'label': "API_KEY", 'type': 'text', 'default': '', 'pos': 2}
    }

    def test_credentials(self):
        """Test OpenSubtitles.com credentials"""
        from twisted.internet import defer, threads
        import requests
        import json

        def _api_login():
            username = self.settings_provider.getSetting("OpenSubtitles_username")
            password = self.settings_provider.getSetting("OpenSubtitles_password")
            api_key = self.settings_provider.getSetting("OpenSubtitles_API_KEY")

            if not username or not password:
                raise Exception(_("Username and password are required"))

            url = "https://api.opensubtitles.com/api/v1/login"
            headers = {
                "Accept": "application/json",
                "Api-Key": api_key,
                "User-Agent": "SubsSupport/1.0"
            }
            payload = {
                "username": username,
                "password": password
            }

            try:
                response = requests.post(url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                raise Exception(_("API error: %s") % str(e))

        deferred = defer.Deferred()
        d = threads.deferToThread(_api_login)
        d.addCallback(deferred.callback)
        d.addErrback(deferred.errback)
        return deferred

    def show_message(self, session, message, is_error=False):
        """Universal message display method"""
        from Screens.MessageBox import MessageBox
        try:
            session.open(
                MessageBox,
                message,
                MessageBox.TYPE_ERROR if is_error else MessageBox.TYPE_INFO,
                timeout=10
            )
        except Exception as e:
            print("Failed to show message:", str(e))

    def _search(self, title, filepath, langs, season, episode, tvshow, year):
        """Override search to include credential check"""
        username = self.settings_provider.getSetting("OpenSubtitles_username")
        password = self.settings_provider.getSetting("OpenSubtitles_password")
        
        if not username or not password:
            return {
                'list': [],
                'session_id': "",
                'msg': _("OpenSubtitles.com requires username and password")
            }
            
        return super(OpenSubtitles2Seeker, self)._search(
            title, filepath, langs, season, episode, tvshow, year
        )

try:
    from .Subdl import subdl
except ImportError as e:
    subdl = e

class SubdlSeeker(XBMCSubtitlesAdapter):
    module = subdl
    if isinstance(module, Exception):
        error, module = module, None

    id = 'subdl.com'
    provider_name = 'Subdl'
    supported_langs = [
        "en", "fr", "hu", "cs", "pl", "sk", "pt", "pt-br", "es", "el", "ar", "sq", 
        "hy", "ay", "bs", "bg", "ca", "zh", "hr", "da", "nl", "eo", "et", "fi", 
        "gl", "ka", "de", "he", "hi", "is", "id", "it", "ja", "kk", "ko", "lv", 
        "lt", "lb", "mk", "ms", "no", "oc", "fa", "ro", "ru", "sr", "sl", "sv", 
        "th", "tr", "uk", "vi"
    ]
    default_settings = {
        'Subdl_API_KEY': {'label': "API_KEY", 'type': 'text', 'default': '', 'pos': 2}
    }

    def test_credentials(self):
        """Test Subdl.com API key"""
        from twisted.internet import defer, threads
        import requests

        def _api_test():
            api_key = self.settings_provider.getSetting("Subdl_API_KEY")
            
            if not api_key:
                raise Exception(_("API key is required"))

            url = "https://api.subdl.com/api/v1/subtitles"
            params = {
                "api_key": api_key,
                "film_name": "Inception",
                "type": "movie",
                "languages": "EN"
            }

            try:
                response = requests.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                if not data.get('status'):
                    raise Exception(_("API error: %s") % data.get('message', 'Unknown error'))
                
                return _("Subdl API key is valid and working")
            except Exception as e:
                raise Exception(_("API error: %s") % str(e))

        deferred = defer.Deferred()
        d = threads.deferToThread(_api_test)
        d.addCallback(deferred.callback)
        d.addErrback(deferred.errback)
        return deferred

    def show_message(self, session, message, is_error=False):
        """Universal message display method"""
        from Screens.MessageBox import MessageBox
        try:
            session.open(
                MessageBox,
                message,
                MessageBox.TYPE_ERROR if is_error else MessageBox.TYPE_INFO,
                timeout=10
            )
        except Exception as e:
            print("Failed to show message:", str(e))

    def _search(self, title, filepath, langs, season, episode, tvshow, year):
        """Override search to include API key check"""
        api_key = self.settings_provider.getSetting("Subdl_API_KEY")
        
        if not api_key:
            return {
                'list': [],
                'session_id': "",
                'msg': _("Subdl.com requires an API key")
            }
            
        return super(SubdlSeeker, self)._search(
            title, filepath, langs, season, episode, tvshow, year
        )

try:
    from .Novalermora import novalermora
except ImportError as e:
    novalermora = e 
    
class NovalermoraSeeker(XBMCSubtitlesAdapter):
    module = novalermora
    if isinstance(module, Exception):
        error, module = module, None
    id = 'novalermora'
    provider_name = 'Novalermora'
    supported_langs = ['ar']
    default_settings = {}
    movie_search = True
    tvshow_search = True  

try:
    from .Subtitlesmora import subtitlesmora
except ImportError as e:
    subtitlesmora = e 
    
class SubtitlesmoraSeeker(XBMCSubtitlesAdapter):
    module = subtitlesmora
    if isinstance(module, Exception):
        error, module = module, None
    id = 'archive.org'
    provider_name = 'Subtitlesmora'
    supported_langs = ['ar']
    default_settings = {}
    movie_search = True
    tvshow_search = True  
