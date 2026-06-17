# -*- coding: utf-8 -*-
from __future__ import absolute_import
from . import _
try:
    from .version import VER
except Exception:
    VER = "1.0.0"
from Components.ActionMap import ActionMap
from Components.Sources.List import List
from Components.PluginComponent import PluginDescriptor
from Components.config import config, ConfigSubsection, ConfigText, ConfigYesNo, ConfigSelection, ConfigNumber, ConfigFloat
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from twisted.web.client import getPage
from Screens.Console import Console
import six
import logging
import os
import json, re
from xml.etree import ElementTree as ET
from datetime import datetime
from Tools.Directories import fileExists
from .Tmdb_scraper import scrape_tmdb_movies, scrape_movie_details
from Components.MenuList import MenuList
from Components.Label import Label
from .e2_utils import isFullHD
from .subtitles import E2SubsSeeker, SubsProSearch, initGeneralProSettings, initSubsProSettings, \
    SubsProSetupGeneral, SubsProSearchSettings, SubsProSetupExternal, SubsProSetupEmbedded, \
    _apply_subssupportpro_theme
from .subtitlesdvb import SubsProSupportDVB, SubsProSetupDVBPlayer
from .subtitles import TMDBScraperProScreen
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

log = logging.getLogger("SubsSupportPro")

_SUBSKINS_PATH = "/usr/lib/enigma2/python/Plugins/Extensions/SubsSupportPro/subskins.xml"
_SUBSKINS_CACHE = None

def _apply_subssupportpro_version(skin_text):
    if not skin_text:
        return skin_text
    try:
        version_text = "SubsSupportPro %s" % VER
    except Exception:
        version_text = "SubsSupportPro 1.0.0"
    return skin_text.replace("SubsSupportPro __SUBSSUPPORTPRO_VERSION__", version_text).replace("SubsSupportPro 1.0.0", version_text)

def load_subskin(skin_id, default=None):
    global _SUBSKINS_CACHE
    if _SUBSKINS_CACHE is None:
        _SUBSKINS_CACHE = {}
        if os.path.exists(_SUBSKINS_PATH):
            root = ET.parse(_SUBSKINS_PATH).getroot()
            for node in root.findall("skin"):
                sid = node.get("id")
                # text inside CDATA becomes node.text
                _SUBSKINS_CACHE[sid] = (node.text or "").strip()
    return _apply_subssupportpro_version(_apply_subssupportpro_theme(_SUBSKINS_CACHE.get(skin_id, default)))

def openSubtitlesSearch(session, **kwargs):
    settings = initSubsProSettings().search
    eventList = []
    eventNow = session.screen["Event_Now"].getEvent()
    eventNext = session.screen["Event_Next"].getEvent()
    if eventNow:
        eventList.append(eventNow.getEventName())
    if eventNext:
        eventList.append(eventNext.getEventName())
    
    # If no events found, try to use the channel name as fallback
    if not eventList:
        try:
            from enigma import iPlayableService
            service = session.nav.getCurrentService()
            info = service and service.info()
            if info:
                channel_name = info.getName()
                if channel_name:
                    eventList.append(channel_name)
                    print('[SubsSupport] Using channel name as fallback: {}'.format(channel_name))
        except Exception as e:
            print('[SubsSupport] Error getting channel name: {}'.format(e))
    
    session.open(SubsProSearch, E2SubsSeeker(session, settings), settings, searchTitles=eventList, standAlone=True)


def openSubtitlesPlayer(session, **kwargs):
    SubsProSupportDVB(session)


def openSubsProSupportSettings(session, **kwargs):
    settings = initSubsProSettings()
    session.open(SubsProSupportSettings, settings, settings.search, settings.external, settings.embedded, config.plugins.subsSupportPro.dvb)

class SubsProSupportSettings(Screen):
    if isFullHD:
        skin = load_subskin("SubsProSupportSettings_fhd")
    else:
        skin = load_subskin("SubsProSupportSettings_hd")

    def __init__(self, session, generalSettings, searchSettings, externalSettings, embeddedSettings, dvbSettings):
        try:
            self.skin = load_subskin("SubsProSupportSettings_fhd" if isFullHD() else "SubsProSupportSettings_hd", getattr(self, "skin", None))
        except Exception:
            pass
        Screen.__init__(self, session)
        self.generalSettings = generalSettings
        self.searchSettings = searchSettings
        self.externalSettings = externalSettings
        self.embeddedSettings = embeddedSettings
        self.dvbSettings = dvbSettings
        self.new_version = None
        self.new_description = None
        
        # Get backup path from config - with proper error handling
        try:
            self.settings_backup_path = self.generalSettings.settingsBackupPath.getValue()
            self.settings_backup_file = os.path.join(self.settings_backup_path, "settings_backup.json")
        except AttributeError:
            # Fallback to default path if setting is missing
            log.error("settingsBackupPath not found in generalSettings, using default")
            self.settings_backup_path = "/etc/enigma2/subssupportpro"
            self.settings_backup_file = os.path.join(self.settings_backup_path, "settings_backup.json")
            
        menu_items = [
            (_("General settings"), "general"),
            (_("External subtitles settings"), "external"),
            (_("Embedded subtitles settings"), "embedded"),
            (_("Search settings"), "search"),
            (_("DVB player settings"), "dvb"),
            (_("Backup settings"), "backup"),
            (_("Restore settings"), "restore")
        ]
        
        self["menuList"] = List(menu_items)
        self["update_status"] = Label("")
        self._setUpdateStatus(_("Checking for update..."))
        self["actionmap"] = ActionMap(["OkCancelActions", "DirectionActions"],
        {
            "up": self["menuList"].selectNext,
            "down": self["menuList"].selectPrevious,
            "ok": self.confirmSelection,
            "cancel": self.close,
        })
        self.onLayoutFinish.append(self.setWindowTitle)
        self.onFirstExecBegin.append(self.checkUpdates)

    def _setUpdateStatus(self, text):
        try:
            self["update_status"].setText(text)
        except Exception:
            pass

    def setWindowTitle(self):
        self.setup_title = _("SubsSupportPro settings")
        self.setTitle('{} v{}'.format(self.setup_title, VER))

    def confirmSelection(self):
        selection = self["menuList"].getCurrent()[1]
        if selection == "general":
            self.openGeneralSettings()
        elif selection == "external":
            self.openExternalSettings()
        elif selection == "embedded":
            self.openEmbeddedSettings()
        elif selection == "search":
            self.openSearchSettings()
        elif selection == "dvb":
            self.openDVBPlayerSettings()
        elif selection == "backup":
            self.backupSettings()
        elif selection == "restore":
            self.restoreSettings()  # Changed from _confirmRestore to restoreSettings

    def openGeneralSettings(self):
        self.session.open(SubsProSetupGeneral, self.generalSettings)

    def openSearchSettings(self):
        seeker = E2SubsSeeker(self.session, self.searchSettings, True)
        self.session.open(SubsProSearchSettings, self.searchSettings, seeker, True)

    def openExternalSettings(self):
        self.session.open(SubsProSetupExternal, self.externalSettings)

    def openEmbeddedSettings(self):
        self.session.open(SubsProSetupEmbedded, self.embeddedSettings)

    def openDVBPlayerSettings(self):
        self.session.open(SubsProSetupDVBPlayer, self.dvbSettings)

    def backupSettings(self):
        try:
            # Get the backup path from config
            backup_path = self.generalSettings.settingsBackupPath.getValue()
            backup_file = os.path.join(backup_path, "settings_backup.json")
            
            # Create backup directory if it doesn't exist
            if not os.path.exists(backup_path):
                os.makedirs(backup_path)
            
            # Verify we can write to the directory
            test_file = os.path.join(backup_path, "test.tmp")
            try:
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
            except IOError as e:
                raise Exception(_("Cannot write to backup directory: %s") % str(e))
            
            # Extract all subtitlesSupportPro settings
            settings_file = '/etc/enigma2/settings'
            if not fileExists(settings_file):
                raise Exception(_("Settings file not found"))
            
            # Extract all settings for our plugin
            with open(settings_file, 'r') as f, open(backup_file, 'w') as backup:
                for line in f:
                    if line.startswith('config.plugins.subtitlesSupportPro.'):
                        backup.write(line)
            
            # Verify backup was created
            if not fileExists(backup_file):
                raise Exception(_("Backup file creation failed"))
            if os.path.getsize(backup_file) == 0:
                raise Exception(_("Backup file is empty - no settings found"))
            
            self.session.open(MessageBox, _("Settings backup completed successfully!"), MessageBox.TYPE_INFO)
        except Exception as e:
            log.error("Backup failed: %s", str(e), exc_info=True)
            self.session.open(MessageBox, _("Backup failed!") + "\n" + str(e), MessageBox.TYPE_ERROR)

    def restoreSettings(self):
        backup_path = self.generalSettings.settingsBackupPath.getValue()
        backup_file = os.path.join(backup_path, "settings_backup.json")
        
        if not fileExists(backup_file):
            self.session.open(MessageBox, _("No backup file found at: %s") % backup_file, MessageBox.TYPE_ERROR)
            return
        
        message = _("Are you sure you want to restore settings from:\n%s\n\nEnigma2 will restart to apply changes.") % backup_file
        self.session.openWithCallback(self._performRestore, MessageBox, message, MessageBox.TYPE_YESNO)

    def _performRestore(self, answer):
        if not answer:
            return
        
        backup_path = self.generalSettings.settingsBackupPath.getValue()
        backup_file = os.path.join(backup_path, "settings_backup.json")
        
        try:
            if not fileExists(backup_file):
                self.session.open(MessageBox, _("Backup file no longer exists!"), MessageBox.TYPE_ERROR)
                return
            
            # Create a restore script
            restore_script = '#!/bin/sh\n    # Stop Enigma2\n    init 4\n    sleep 2\n\n    # Backup current settings\n    cp /etc/enigma2/settings /etc/enigma2/settings.bak\n\n    # Remove existing plugin settings\n    grep -v \'^config.plugins.subtitlesSupportPro.\' /etc/enigma2/settings > /tmp/settings.tmp\n\n    # Add our backed up settings\n    cat "{}" >> /tmp/settings.tmp\n\n    # Replace settings file\n    mv /tmp/settings.tmp /etc/enigma2/settings\n    rm -f /tmp/settings.tmp\n\n    # Restart Enigma2\n    sleep 1\n    init 3\n    '.format(backup_file)
            
            script_path = '/tmp/subssupport_restore.sh'
            with open(script_path, 'w') as f:
                f.write(restore_script)
            os.chmod(script_path, 0o755)
            
            # Execute the restore through Console
            self.session.open(
                Console,
                title=_("Restoring Settings..."),
                cmdlist=[script_path],
                closeOnSuccess=False
            )
            self.close()
            
        except Exception as e:
            log.error("Restore failed: %s", str(e), exc_info=True)
            self.session.open(MessageBox, _("Restore failed!") + "\n" + str(e), MessageBox.TYPE_ERROR)


    def checkUpdates(self):
        try:
            self._setUpdateStatus(_("Checking for update..."))
            url = b"https://raw.githubusercontent.com/popking159/SubsSupportPro/main/version.txt"
            getPage(url, timeout=10).addCallback(self.parseUpdateData).addErrback(self.updateError)
        except Exception as e:
            log.error("Update check error: %s", str(e))
            self._setUpdateStatus(_("Update check failed"))

    def updateError(self, error):
        log.error("Failed to check for updates: %s", str(error))
        self._setUpdateStatus(_("Update check failed"))

    def parseUpdateData(self, data):
        if six.PY3:
            data = data.decode("utf-8")
        else:
            data = data.encode("utf-8")
        
        if data:
            lines = data.split("\n")
            for line in lines:
                if line.startswith("version="):
                    self.new_version = line.split("'")[1] if "'" in line else line.split('"')[1]
                if line.startswith("description="):
                    self.new_description = line.split("'")[1] if "'" in line else line.split('"')[1]
                    break
        
        if self.new_version and self.new_version != VER:
            self._setUpdateStatus(_("Update available"))
            message = _("New version %s is available.\n\n%s\n\nDo you want to install now?") % (self.new_version, self.new_description)
            self.session.openWithCallback(
                self.installUpdate, 
                MessageBox, 
                message, 
                MessageBox.TYPE_YESNO,
                timeout=10
            )
        else:
            self._setUpdateStatus(_("Plugin up to date"))

    def installUpdate(self, answer=False):
        if answer:
            self._setUpdateStatus(_("Downloading update..."))
            cmd = 'wget -q "--no-check-certificate" https://github.com/popking159/SubsSupportPro/raw/main/subssupportpro-install.sh -O - | /bin/sh'
            self.session.open(Console, title=_("Installing update..."), cmdlist=[cmd], closeOnSuccess=False)


def Plugins(**kwargs):
    from enigma import getDesktop
    screenwidth = getDesktop(0).size().width()
    if screenwidth and screenwidth == 1920:
        iconSET = 'img/ss_set_FHD.png'
        iconDWN = 'img/ss_dwn_FHD.png'
        iconPLY = 'img/ss_ply_FHD.png'
    else:
        iconSET = 'img/ss_set_HD.png'
        iconDWN = 'img/ss_dwn_HD.png'
        iconPLY = 'img/ss_ply_HD.png'

    return [
        PluginDescriptor(name=_('SubsSupportPro settings'), icon=iconSET, description=_('Change SubsSupportPro settings'), where=PluginDescriptor.WHERE_PLUGINMENU, fnc=openSubsProSupportSettings),
        PluginDescriptor(name=_('SubsSupportPro downloader'), icon=iconDWN, description=_('Download subtitles for your videos'), where=PluginDescriptor.WHERE_PLUGINMENU, fnc=openSubtitlesSearch),
        PluginDescriptor(name=_('SubsSupportPro DVB player'), icon=iconPLY, description=_('watch DVB broadcast with subtitles'), where=PluginDescriptor.WHERE_PLUGINMENU, fnc=openSubtitlesPlayer),
        PluginDescriptor(name=_('SubsSupportPro settings'), where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=openSubsProSupportSettings),
        PluginDescriptor(name=_('SubsSupportPro downloader'), where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=openSubtitlesSearch),
        PluginDescriptor(name=_('SubsSupportPro DVB player'), where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=openSubtitlesPlayer)
    ]