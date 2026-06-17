# -*- coding: utf-8 -*-
'''
Created on Sep 16, 2014

@author: marko
'''
from __future__ import absolute_import
from __future__ import print_function
import time
import time
import os, json          # <- added for delay persistence
from . import _
from Components.ActionMap import HelpableActionMap
from Components.Label import Label
from Components.config import ConfigSubsection, getConfigListEntry
from Components.config import ConfigText, ConfigNothing
from Components.config import config, ConfigOnOff, ConfigInteger, ConfigSubsection
from Components.ConfigList import ConfigListScreen
from Components.config import configfile
from Components.ConfigList import ConfigListScreen
from Screens.HelpMenu import HelpableScreen
from .compat import MessageBox, eConnectCallback
from Screens.MinuteInput import MinuteInput
from Screens.Screen import Screen
from Components.ActionMap import ActionMap
from Components.MenuList import MenuList
from .e2_utils import getFps, fps_float, BaseProMenuScreen, isFullHD, getDesktopSize
from enigma import eTimer, getDesktop
from .parsers.baseparser import ParseError
from .process import LoadError, DecodeError, ParserNotFoundError
from skin import parseColor
from .subtitles import SubsProChooser, initSubsProSettings, SubsScreen, \
    SubsLoader, PARSERS, ALL_LANGUAGES_ENCODINGS, ENCODINGS, \
    warningMessage, _apply_subssupportpro_theme
from enigma import eListboxPythonMultiContent, gFont, RT_HALIGN_LEFT
from Components.MultiContent import MultiContentEntryText
from Components.Sources.StaticText import StaticText
from .utils import toString, toUnicode

config.plugins.subsSupportPro = ConfigSubsection()
config.plugins.subsSupportPro.dvb = ConfigSubsection()
config.plugins.subsSupportPro.dvb.autoSync = ConfigOnOff(default=True)
config.plugins.subsSupportPro.dvb.fpsDriftEnable = ConfigOnOff(default=False)

config.plugins.subsSupportPro.dvb.fpsRatio_23_976 = ConfigText(default="1.0000", fixed_size=False)
config.plugins.subsSupportPro.dvb.fpsRatio_24_000 = ConfigText(default="1.0000", fixed_size=False)
config.plugins.subsSupportPro.dvb.fpsRatio_25_000 = ConfigText(default="1.0000", fixed_size=False)
config.plugins.subsSupportPro.dvb.fpsRatio_29_970 = ConfigText(default="1.0000", fixed_size=False)
config.plugins.subsSupportPro.dvb.fpsRatio_30_000 = ConfigText(default="1.0000", fixed_size=False)
config.plugins.subsSupportPro.dvb.fpsRatio_50_000 = ConfigText(default="1.0000", fixed_size=False)
config.plugins.subsSupportPro.dvb.fpsRatio_59_940 = ConfigText(default="1.0000", fixed_size=False)


class SubsProSetupDVBPlayer(BaseProMenuScreen):
    def __init__(self, session, dvbSettings):
        BaseProMenuScreen.__init__(self, session, _("DVB player settings"))
        self.dvbSettings = dvbSettings

    def buildMenu(self):
        lst = []
        lst.append(getConfigListEntry(_("Auto sync to current event"), self.dvbSettings.autoSync))
        lst.append(getConfigListEntry(" ", ConfigNothing()))

        lst.append(getConfigListEntry(
            _("Try to correct FPS drift with FPS ratio"),
            config.plugins.subsSupportPro.dvb.fpsDriftEnable
        ))

        if config.plugins.subsSupportPro.dvb.fpsDriftEnable.value:
            lst.append(getConfigListEntry(
                _("Subtitles late: Decrease Ratio. Subtitles rush: Increase Ratio"),
                ConfigNothing()
            ))
            lst.append(getConfigListEntry(_("Override Ratio for 23.976 (Standard is 1.0000)"),
                                          config.plugins.subsSupportPro.dvb.fpsRatio_23_976))
            lst.append(getConfigListEntry(_("Override Ratio for 24.000 (Standard is 1.0000)"),
                                          config.plugins.subsSupportPro.dvb.fpsRatio_24_000))
            lst.append(getConfigListEntry(_("Override Ratio for 25.000 (Standard is 1.0000)"),
                                          config.plugins.subsSupportPro.dvb.fpsRatio_25_000))
            lst.append(getConfigListEntry(_("Override Ratio for 29.970 (Standard is 1.0000)"),
                                          config.plugins.subsSupportPro.dvb.fpsRatio_29_970))
            lst.append(getConfigListEntry(_("Override Ratio for 30.000 (Standard is 1.0000)"),
                                          config.plugins.subsSupportPro.dvb.fpsRatio_30_000))
            lst.append(getConfigListEntry(_("Override Ratio for 50.000 (Standard is 1.0000)"),
                                          config.plugins.subsSupportPro.dvb.fpsRatio_50_000))
            lst.append(getConfigListEntry(_("Override Ratio for 59.940 (Standard is 1.0000)"),
                                          config.plugins.subsSupportPro.dvb.fpsRatio_59_940))

        self["config"].setList(lst)

    def _rebuildIfToggle(self):
        cur = self["config"].getCurrent()
        if not cur:
            return
        cfg = cur[1]
        if cfg is config.plugins.subsSupportPro.dvb.fpsDriftEnable:
            self.buildMenu()

    def keyLeft(self):
        ConfigListScreen.keyLeft(self)
        self._rebuildIfToggle()

    def keyRight(self):
        ConfigListScreen.keyRight(self)
        self._rebuildIfToggle()

    def keyOK(self):
        # some images toggle booleans on OK
        try:
            ConfigListScreen.keyOK(self)
        except Exception:
            pass
        self._rebuildIfToggle()

class SubsProSupportDVB(object):
    def __init__(self, session):
        self.session = session
        self.subsProSettings = initSubsProSettings()
        session.openWithCallback(self.subsChooserCB, SubsProChooser, self.subsProSettings, searchSupport=True, historySupport=True, titleList=self.getTitleList())

    def getTitleList(self):
        eventList = []
        eventNow = self.session.screen["Event_Now"].getEvent()
        eventNext = self.session.screen["Event_Next"].getEvent()
        if eventNow:
            eventList.append(eventNow.getEventName())
        if eventNext:
            eventList.append(eventNext.getEventName())
        
        # If no events found, try to use the channel name as fallback
        if not eventList:
            try:
                service = self.session.nav.getCurrentService()
                info = service and service.info()
                if info:
                    channel_name = info.getName()
                    if channel_name:
                        eventList.append(channel_name)
                        print('[SubsProSupportDVB] Using channel name as fallback: {}'.format(channel_name))
            except Exception as e:
                print('[SubsProSupportDVB] Error getting channel name: {}'.format(e))
        
        return eventList

    def subsChooserCB(self, subfile=None, embeddedSubtitle=None, forceReload=False):
        if subfile is not None:
            subsLoader = SubsLoader(PARSERS, ALL_LANGUAGES_ENCODINGS + ENCODINGS[self.subsProSettings.encodingsGroup.getValue()])
            try:
                subsList, subsEnc = subsLoader.load(subfile, fps=getFps(self.session))
            except LoadError:
                warningMessage(self.session, _("Cannot load subtitles. Invalid path"))
            except DecodeError:
                warningMessage(self.session, _("Cannot decode subtitles. Try another encoding group"))
            except ParserNotFoundError:
                warningMessage(self.session, _("Cannot parse subtitles. Not supported subtitles format"))
            except ParseError:
                warningMessage(self.session, _("Cannot parse subtitles. Invalid subtitles format"))
            else:
                self.subsScreen = self.session.instantiateDialog(SubsScreen, self.subsProSettings.external)
                subsEngine = SubsEngineDVB(self.session, self.subsProSettings.engine, self.subsScreen)
                subsEngine.setSubsList(subsList)
                self.session.openWithCallback(
                    self.subsControllerCB,
                    SubsProControllerDVB,
                    subsEngine,
                    config.plugins.subsSupportPro.dvb.autoSync.value,
                    False,
                    None,
                    self.subsProSettings.external
                )
        else:
            print('[SubsProSupportDVB] no subtitles selected, exit')

    def subsControllerCB(self):
        self.session.deleteDialog(self.subsScreen)

# UI revision v3: picker shows 10 complete rows; controller panel shifted down by 50px.

class SubtitleProPicker(Screen):
    """
    Responsive subtitle-line picker with aligned columns and fixed-height rows.

    eListboxPythonMultiContent supports only one item height for the complete
    list.  Using a different height for each subtitle row causes misaligned
    columns and clipped entries, because the last processed row silently wins.
    This screen therefore uses one resolution-aware row height and displays up
    to two text lines per subtitle entry.
    """

    def __init__(self, session, subsList, currentIndex):
        self.subsList = subsList or []
        try:
            self.currentIndex = int(currentIndex)
        except Exception:
            self.currentIndex = 0

        self._configure_layout()
        Screen.__init__(self, session)

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "SubtitleProPickerActions"],
            {
                "ok": self.selectSubtitle,
                "green": self.selectSubtitle,
                "cancel": self.close,
                "red": self.close,
                "firstSubtitle": self.firstSubtitle,
                "lastSubtitle": self.lastSubtitle,
            },
            -1
        )

        self["subList"] = MenuList(
            [], enableWrapAround=True, content=eListboxPythonMultiContent
        )
        self["subList"].l.setItemHeight(self.row_height)
        self["subList"].l.setFont(0, gFont("Regular", self.row_font_size))

        self["key_red"] = StaticText(_("Cancel"))
        self["key_green"] = StaticText(_("Select"))

        self.updateSubtitleList()
        self.onLayoutFinish.append(self.setInitialSelection)

    def _configure_layout(self):
        """Build a conservative picker layout for SD, HD and Full-HD skins."""
        desktop = getDesktop(0).size()
        desktop_width = desktop.width()
        desktop_height = desktop.height()

        if desktop_width >= 1920:
            screen_width = min(1540, desktop_width - 120)
            screen_height = min(900, desktop_height - 100)
            self.row_height = 78
            self.row_font_size = 26
            header_font_size = 27
            instruction_font_size = 24
            footer_font_size = 26
            header_height = 42
            instruction_height = 38
            footer_height = 48
        elif desktop_width >= 1280:
            screen_width = min(1120, desktop_width - 80)
            screen_height = min(650, desktop_height - 60)
            self.row_height = 68
            self.row_font_size = 22
            header_font_size = 23
            instruction_font_size = 21
            footer_font_size = 22
            header_height = 38
            instruction_height = 34
            footer_height = 42
        else:
            screen_width = min(700, desktop_width - 20)
            screen_height = min(540, desktop_height - 20)
            self.row_height = 58
            self.row_font_size = 18
            header_font_size = 19
            instruction_font_size = 17
            footer_font_size = 18
            header_height = 34
            instruction_height = 30
            footer_height = 38

        # Premium 1720x980 picker layout.
        # 10 visible rows, each row can display up to 2 subtitle lines.
        visible_rows = 10
        screen_width = 1720
        screen_height = 980
        padding = 50

        instruction_y = 115
        instruction_height = 35

        header_y = 155
        header_height = 32

        list_y = 193
        self.row_height = 70
        self.row_font_size = 21

        header_font_size = 24
        instruction_font_size = 24
        footer_font_size = 28
        footer_height = 50
        footer_y = 898

        list_height = self.row_height * visible_rows
        list_width = 1620

        self.number_width = 130
        self.time_width = 340
        self.subtitle_width = 1150

        self.number_x = 0
        self.time_x = self.number_width
        self.subtitle_x = self.number_width + self.time_width

        self.skin = """
            <screen name="SubtitleProPicker" position="center,center" size="%(screen_width)d,%(screen_height)d" title="Select Current Subtitle Line" zPosition="10" flags="wfNoBorder" backgroundColor="#ff000000">
                <eLabel position="0,0" size="1720,980" backgroundColor="#061425" zPosition="-5" cornerRadius="20" />
                <eLabel position="20,20" size="1680,940" backgroundColor="#0a1b2d" zPosition="-4" cornerRadius="14" />
                <eLabel position="30,30" size="1660,68" backgroundColor="#8e5245" zPosition="-3" cornerRadius="20" borderWidth="1" borderColor="#27408b" />
                <eLabel position="30,108" size="1660,2" backgroundColor="#5d37d9" zPosition="-3" />

                <eLabel name="" position="40,40" size="1640,48" zPosition="5" text="Select Current Subtitle Line" backgroundColor="#8e5245" font="Regular;34" valign="center" halign="left" foregroundColor="#eaf3ff" />

                <eLabel position="%(padding)d,%(instruction_y)d" size="%(list_width)d,%(instruction_height)d" font="Regular;%(instruction_font_size)d" valign="center" halign="center" foregroundColor="#eaf3ff" backgroundColor="#061425" text="Press OK to select subtitle line" cornerRadius="10" />

                <eLabel position="%(padding)d,%(header_y)d" size="%(number_width)d,%(header_height)d" font="Regular;%(header_font_size)d" valign="center" halign="left" foregroundColor="#d6e4f7" backgroundColor="#081a31" text="No." />
                <eLabel position="%(time_header_x)d,%(header_y)d" size="%(time_width)d,%(header_height)d" font="Regular;%(header_font_size)d" valign="center" halign="left" foregroundColor="#d6e4f7" backgroundColor="#081a31" text="Time" />
                <eLabel position="%(subtitle_header_x)d,%(header_y)d" size="%(subtitle_width)d,%(header_height)d" font="Regular;%(header_font_size)d" valign="center" halign="left" foregroundColor="#d6e4f7" backgroundColor="#081a31" text="Subtitle" />

                <widget name="subList" position="%(padding)d,%(list_y)d" size="%(list_width)d,%(list_height)d" scrollbarMode="showAlways" scrollbarWidth="10" itemHeight="70" itemCornerRadius="12" itemCornerRadiusSelected="12" backgroundColorSelected="#45818e" backgroundColor="#061425" />

                <widget source="key_red" render="Label" position="104,%(footer_y)d" size="250,50" valign="center" halign="left" zPosition="2" font="Regular;28" transparent="1" foregroundColor="white" backgroundColor="#a93247" />
                <widget source="key_green" render="Label" position="424,%(footer_y)d" size="250,50" valign="center" halign="left" zPosition="2" font="Regular;28" transparent="1" foregroundColor="white" backgroundColor="#1aa96b" />

                <eLabel name="" position="50,%(footer_y)d" size="52,52" cornerRadius="26" backgroundColor="#999999" zPosition="-1" />
                <eLabel name="" position="370,%(footer_y)d" size="52,52" cornerRadius="26" backgroundColor="#999999" zPosition="-1" />

                <eLabel name="" position="50,%(footer_y)d" size="50,50" cornerRadius="25" backgroundColor="#a93247" zPosition="1" />
                <eLabel name="" position="370,%(footer_y)d" size="50,50" cornerRadius="25" backgroundColor="#1aa96b" zPosition="1" />
            </screen>
        """ % {
            "screen_width": screen_width,
            "screen_height": screen_height,
            "padding": padding,
            "instruction_y": instruction_y,
            "instruction_height": instruction_height,
            "instruction_font_size": instruction_font_size,
            "header_y": header_y,
            "header_height": header_height,
            "header_font_size": header_font_size,
            "number_width": self.number_width,
            "time_width": self.time_width,
            "subtitle_width": self.subtitle_width,
            "time_header_x": padding + self.time_x,
            "subtitle_header_x": padding + self.subtitle_x,
            "list_y": list_y,
            "list_width": list_width,
            "list_height": list_height,
            "footer_y": footer_y,
        }
        self.skin = _apply_subssupportpro_theme(self.skin)

    def firstSubtitle(self):
        """Jump to the first subtitle."""
        if self.subsList:
            self["subList"].moveToIndex(0)

    def lastSubtitle(self):
        """Jump to the final subtitle."""
        if self.subsList:
            self["subList"].moveToIndex(len(self.subsList) - 1)

    def selectSubtitle(self):
        """Return the highlighted subtitle index to the controller."""
        index = self["subList"].getSelectedIndex()
        if 0 <= index < len(self.subsList):
            self.close(index)

    def _picker_text(self, value):
        """Return Enigma2 Python 2 list-widget safe text."""
        try:
            return toString(value)
        except Exception:
            return ""

    def _picker_unicode(self, value):
        """Return unicode text for internal cleanup/splitting."""
        try:
            return toUnicode(value)
        except Exception:
            try:
                return unicode(value)
            except Exception:
                return u""

    def updateSubtitleList(self):
        """Populate the picker with aligned fixed-height multi-content rows."""
        menu_items = []
        vertical_padding = 6
        single_line_y = max(0, int((self.row_height - self.row_font_size) / 2))

        for subtitle in self.subsList:
            try:
                caption_number = "%d" % (int(subtitle.get("index", 0)) + 1)
            except Exception:
                caption_number = "?"

            timestamp = self.format_time(subtitle.get("start", 0))
            subtitle_text = self.clean_display_text(subtitle.get("text") or "")
            display_text = self._limit_display_lines(subtitle_text, max_lines=2)
            caption_number = self._picker_text(caption_number)
            timestamp = self._picker_text(timestamp)
            display_text = self._picker_text(display_text)

            row = [
                subtitle,
                MultiContentEntryText(
                    pos=(self.number_x + 6, single_line_y),
                    size=(self.number_width - 10, self.row_font_size + 6),
                    font=0,
                    text=caption_number,
                    flags=RT_HALIGN_LEFT
                ),
                MultiContentEntryText(
                    pos=(self.time_x + 6, single_line_y),
                    size=(self.time_width - 10, self.row_font_size + 6),
                    font=0,
                    text=timestamp,
                    flags=RT_HALIGN_LEFT
                ),
                MultiContentEntryText(
                    pos=(self.subtitle_x + 6, vertical_padding),
                    size=(self.subtitle_width - 12, self.row_height - (vertical_padding * 2)),
                    font=0,
                    text=display_text,
                    flags=RT_HALIGN_LEFT
                ),
            ]
            menu_items.append(row)

        self["subList"].l.setItemHeight(self.row_height)
        self["subList"].l.setList(menu_items)
        self["subList"].l.invalidate()

    def _limit_display_lines(self, text, max_lines=2):
        """Keep picker rows uniform while preserving common two-line subtitles."""
        text = self._picker_unicode(text)
        lines = [line.strip() for line in text.replace(u"\r", u"").split(u"\n") if line.strip()]
        if not lines:
            return u""
        if len(lines) <= max_lines:
            return u"\n".join(lines)
        visible = lines[:max_lines]
        visible[-1] = visible[-1] + u" ..."
        return u"\n".join(visible)

    def clean_display_text(self, text):
        """Remove RTL/LTR control characters that appear as picker artifacts."""
        text = self._picker_unicode(text)
        control_chars = (
            u"\u202B",  # RTL embedding
            u"\u202C",  # Pop directional formatting
            u"\u202A",  # LTR embedding
            u"\u202D",  # LTR override
            u"\u202E",  # RTL override
            u"\u200F",  # RTL mark
            u"\u200E",  # LTR mark
        )
        for char in control_chars:
            text = text.replace(char, u"")
        return text.strip()

    def setInitialSelection(self):
        """Open the picker on the currently playing subtitle where possible."""
        if not self.subsList:
            return
        index = min(max(self.currentIndex, 0), len(self.subsList) - 1)
        self["subList"].moveToIndex(index)

    def format_time(self, seconds):
        """Convert a subtitle start time to hh:mm:ss,ms."""
        try:
            seconds = float(seconds)
        except Exception:
            seconds = 0.0
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int(round((seconds - int(seconds)) * 1000))
        if millisecs >= 1000:
            secs += 1
            millisecs = 0
        return "%02d:%02d:%02d,%03d" % (hours, minutes, secs, millisecs)

class DVBExternalStyleProScreen(Screen, ConfigListScreen, HelpableScreen):
    """
    Live editor for config.plugins.subtitlesSupportPro.external (same items as initExternalSettings()).
    Applies changes instantly to renderer.
    """
    skin = """
    <screen position="360,270" size="1200,650" title="External subtitles style (live)" flags="wfNoBorder" backgroundColor="#ff000000">
  <eLabel position="0,0" size="1200,650" backgroundColor="#061425" zPosition="-5" cornerRadius="20" />
  <eLabel position="10,10" size="1180,630" backgroundColor="#0a1b2d" zPosition="-4" />
  <eLabel name="" position="15,15" size="1170,620" zPosition="-1" backgroundColor="#061425" cornerRadius="20" borderWidth="1" borderColor="#27408b" />
  <widget name="config" position="20,20" size="1160,540" scrollbarWidth="10" itemHeight="30" itemCornerRadius="12" itemCornerRadiusSelected="12" backgroundColorSelected="#2c525b" backgroundColor="#061425" scrollbarMode="showNever" />
  <eLabel position="30,570" size="1130,2" backgroundColor="#6854a8" zPosition="1" />
  <widget source="key_red" render="Label" position="84,578" size="250,50" valign="center" halign="left" zPosition="2" font="Regular;28" transparent="1" foregroundColor="white" backgroundColor="#061425" />
  <widget source="key_green" render="Label" position="394,578" size="250,50" valign="center" halign="left" zPosition="2" font="Regular;28" transparent="1" foregroundColor="white" backgroundColor="#061425" />
  <widget source="key_yellow" render="Label" position="704,578" size="250,50" valign="center" halign="left" zPosition="2" font="Regular;28" transparent="1" foregroundColor="white" backgroundColor="#061425" />
  <eLabel name="" position="30,578" size="50,50" cornerRadius="25" backgroundColor="#a93247" />
  <eLabel name="" position="340,578" size="50,50" cornerRadius="25" backgroundColor="#1aa96b" />
  <eLabel name="" position="650,578" size="50,50" cornerRadius="25" backgroundColor="#c2941a" />
  <eLabel name="" position="30,578" size="52,52" cornerRadius="26" backgroundColor="#999999" zPosition="-1" />
  <eLabel name="" position="340,578" size="52,52" cornerRadius="26" backgroundColor="#999999" zPosition="-1" />
  <eLabel name="" position="650,578" size="52,52" cornerRadius="26" backgroundColor="#999999" zPosition="-1" />
</screen>
    """

    def __init__(self, session, externalSettings, apply_cb):
        try:
            self.skin = _apply_subssupportpro_theme(self.skin)
        except Exception:
            pass
        Screen.__init__(self, session)
        HelpableScreen.__init__(self)
        self.externalSettings = externalSettings
        self.apply_cb = apply_cb

        self["key_red"] = StaticText(_("Cancel"))
        self["key_green"] = StaticText(_("Save"))
        self["key_yellow"] = StaticText(_("Apply now"))

        ConfigListScreen.__init__(self, [], session=session)

        self["actions"] = HelpableActionMap(self, "OkCancelActions",
        {
            "cancel": (self.keyCancel, _("cancel")),
            "ok": (self.keyOk, _("ok")),
        }, -1)

        self["coloractions"] = HelpableActionMap(self, "ColorActions",
        {
            "red": (self.keyCancel, _("cancel")),
            "green": (self.keySave, _("save")),
            "yellow": (self.keyApply, _("apply now")),
        }, -1)

        self.onLayoutFinish.append(self.buildMenu)

    def buildMenu(self):
        # Reuse the same list builder already used in subtitles.py
        from .subtitles import SubsProSetupExternal
        self["config"].setList(SubsProSetupExternal.getConfigList(self.externalSettings))

    def _apply_live(self):
        if callable(self.apply_cb):
            self.apply_cb()

    def keyLeft(self):
        ConfigListScreen.keyLeft(self)
        cur = self["config"].getCurrent()
        if cur and cur[1] in (
            self.externalSettings.shadow.enabled,
            self.externalSettings.shadow.type,
            self.externalSettings.background.enabled,
            self.externalSettings.background.type,
            self.externalSettings.translate.mode,
        ):
            self.buildMenu()
        self._apply_live()

    def keyRight(self):
        ConfigListScreen.keyRight(self)
        cur = self["config"].getCurrent()
        if cur and cur[1] in (
            self.externalSettings.shadow.enabled,
            self.externalSettings.shadow.type,
            self.externalSettings.background.enabled,
            self.externalSettings.background.type,
            self.externalSettings.translate.mode,
        ):
            self.buildMenu()
        self._apply_live()

    def keyOk(self):
        try:
            ConfigListScreen.keyOK(self)
        except Exception:
            pass
        self._apply_live()

    def keyApply(self):
        self._apply_live()

    def keySave(self):
        for x in self["config"].list:
            x[1].save()
        configfile.save()
        self._apply_live()
        self.close(True)

    def keyCancel(self):
        for x in self["config"].list:
            x[1].cancel()
        self.close(False)

class SubsProControllerDVB(Screen, HelpableScreen):
    fpsChoices = ["23.976", "23.980", "24.000", "25.000", "29.970", "30.000"]

    def __init__(self, session, engine, autoSync=False, setSubtitlesFps=False, subtitlesFps=None, externalSettings=None):
        desktopSize = getDesktopSize()
        controllerVerticalOffset = 50
        windowPosition = (int(0.03 * desktopSize[0]), int(0.05 * desktopSize[1]) + controllerVerticalOffset)
        windowSize = (int(0.9 * desktopSize[0]), int(0.4 * desktopSize[1]))
        fontSize = 33 if isFullHD() else 22
        rowHeight = fontSize + 10
        rowStep = rowHeight + 10
        if isFullHD():
            instructionFontSize = 24
        elif desktopSize[0] >= 1280:
            instructionFontSize = 18
        else:
            instructionFontSize = 14
        instructionHeight = instructionFontSize + 10
        contentY = instructionHeight + 8
        leftWidth = int(0.4 * windowSize[0])
        rightX = int(0.6 * windowSize[0])
        rightWidth = int(0.4 * windowSize[0])
        self.skin = """
            <screen position="%(window_x)d,%(window_y)d" size="%(window_width)d,%(window_height)d" zPosition="2" backgroundColor="transparent" flags="wfNoBorder">
                <widget name="instruction" position="0,0" size="%(window_width)d,%(instruction_height)d" valign="center" halign="center" font="Regular;%(instruction_font_size)d" transparent="1" foregroundColor="#F7A900" shadowColor="#40101010" shadowOffset="2,2" />
                <widget name="subtitle" position="0,%(left_row_0)d" size="%(left_width)d,%(row_height)d" valign="center" halign="left" font="Regular;%(font_size)d" transparent="1" foregroundColor="#ffffff" shadowColor="#40101010" shadowOffset="2,2" />
                <widget name="subtitlesTime" position="0,%(left_row_1)d" size="%(left_width)d,%(row_height)d" valign="center" halign="left" font="Regular;%(font_size)d" transparent="1" foregroundColor="#ffffff" shadowColor="#40101010" shadowOffset="2,2" />
                <widget name="subtitlesPosition" position="0,%(left_row_2)d" size="%(left_width)d,%(row_height)d" valign="center" halign="left" font="Regular;%(font_size)d" transparent="1" foregroundColor="#ffffff" shadowColor="#40101010" shadowOffset="2,2" />
                <widget name="subtitlesFps" position="0,%(left_row_3)d" size="%(left_width)d,%(row_height)d" valign="center" halign="left" font="Regular;%(font_size)d" transparent="1" foregroundColor="#6F9EF5" shadowColor="#40101010" shadowOffset="2,2" />
                <widget name="eventName" position="%(right_x)d,%(right_row_0)d" size="%(right_width)d,%(row_height)d" valign="center" halign="left" font="Regular;%(font_size)d" transparent="1" foregroundColor="#ffffff" shadowColor="#40101010" shadowOffset="2,2" />
                <widget name="eventTime" position="%(right_x)d,%(right_row_1)d" size="%(right_width)d,%(row_height)d" valign="center" halign="left" font="Regular;%(font_size)d" transparent="1" foregroundColor="#ffffff" shadowColor="#40101010" shadowOffset="2,2" />
                <widget name="eventDuration" position="%(right_x)d,%(right_row_2)d" size="%(right_width)d,%(row_height)d" valign="center" halign="left" font="Regular;%(font_size)d" transparent="1" foregroundColor="#ffffff" shadowColor="#40101010" shadowOffset="2,2" />
            </screen>""" % {
                "window_x": windowPosition[0],
                "window_y": windowPosition[1],
                "window_width": windowSize[0],
                "window_height": windowSize[1],
                "instruction_height": instructionHeight,
                "instruction_font_size": instructionFontSize,
                "font_size": fontSize,
                "left_width": leftWidth,
                "row_height": rowHeight,
                "left_row_0": contentY,
                "left_row_1": contentY + rowStep,
                "left_row_2": contentY + (rowStep * 2),
                "left_row_3": contentY + (rowStep * 3),
                "right_x": rightX,
                "right_width": rightWidth,
                "right_row_0": contentY,
                "right_row_1": contentY + rowStep,
                "right_row_2": contentY + (rowStep * 2),
            }

        Screen.__init__(self, session)
        HelpableScreen.__init__(self)
        self.engine = engine
        self.engine.onRenderSub.append(self.onRenderSub)
        self.engine.onHideSub.append(self.onHideSub)
        self.engine.onPositionUpdate.append(self.onUpdateSubPosition)
        subtitlesFps = subtitlesFps and fps_float(subtitlesFps)
        if subtitlesFps and str(subtitlesFps) in self.fpsChoices:
            self.providedSubtitlesFps = subtitlesFps
        else:
            self.providedSubtitlesFps = None
        self.externalSettings = externalSettings
        self.hideTimer = eTimer()
        self.hideTimer_conn = eConnectCallback(self.hideTimer.timeout, self.hideStatus)
        self.hideTimerDelay = 5000
        self.eventTimer = eTimer()
        self.eventTimer_conn = eConnectCallback(self.eventTimer.timeout, self.updateEventStatus)
        self.subtitlesTimer = eTimer()
        self.subtitlesTimer_conn = eConnectCallback(self.subtitlesTimer.timeout, self.updateSubtitlesTime)
        self.subtitlesTimerStep = 500
        self._baseTime = 0
        self._accTime = 0
        self.statusLocked = False
        self["instruction"] = Label(_("Press RED to open subtitle picker - Press OK to hide/unhide - Press MENU to open Subtitle display - Press INFO to open help screen"))
        self['subtitle'] = Label()
        self['subtitlesPosition'] = Label(_("Subtitles Position") + ":")
        self['subtitlesTime'] = Label(_("Subtitles Time") + ":")
        self['subtitlesFps'] = Label(_("Subtitles FPS") + ":")
        self["eventName"] = Label(_("Event Name") + ":")
        self["eventTime"] = Label(_("Event Time") + ":")
        self["eventDuration"] = Label(_("Event Duration") + ":")
        self["actions"] = HelpableActionMap(self, "SubtitlesDVBActions",
        {
            "closePlugin": (self.close, _("close plugin")),
            "showHideStatus": (self.showHideStatus, _("show/hide subtitles status")),
            "playPauseSub": (self.playPause, _("play/pause subtitles playback")),
            "pauseSub": (self.pause, _("pause subtitles playback")),
            "resumeSub": (self.resume, _("resumes subtitles playback")),
            "restartSub": (self.restart, _("restarts current subtitle")),
            "nextSub": (self.nextSkip, _("skip to next subtitle")),
            "nextSubMinute": (self.nextMinuteSkip, _("skip to next subtitle (minute jump)")),
            "nextSubManual": (self.nextManual, _("skip to next subtitle by setting time in minutes")),
            "prevSub": (self.previousSkip, _("skip to previous subtitle")),
            "prevSubMinute": (self.previousMinuteSkip, _("skip to previous subtitle (minute jump)")),
            "prevSubManual": (self.previousManual, _("skip previous subtitle by setting time in minutes")),
            "eventSync": (self.eventSync, _("skip subtitle to current event position")),
            "changeFps": (self.changeFps, _("change subtitles fps")),
            "openSubtitleProPicker": (self.openSubtitleProPicker, _("open Subtitle Picker")),
            "applySavedDelay": (self.applySavedDelay, _("apply Saved Delay")),
            "saveCurrentDelay": (self.saveCurrentDelay,_("save current delay for this channel")),
            "showHelp": (self.showHelp, _("show help")),
            "confirmClose": (self.confirmClose, _("exit (confirm)")),
            "externalStyle": (self.externalStyle, _("External style")),
        }, -1)

        try:
            from Screens.InfoBar import InfoBar
            InfoBar.instance.subtitle_window.hide()
        except:
            pass
        self.onLayoutFinish.append(self.hideStatus)
        self.onLayoutFinish.append(self.engine.start)
        self.onLayoutFinish.append(self.startEventTimer)
        self.onLayoutFinish.append(self.startSubtitlesTimer)
        self.onLayoutFinish.append(self.showStatusWithTimer)
        if setSubtitlesFps and self.providedSubtitlesFps:
            self.onFirstExecBegin.append(self.setProvidedSubtitlesFps)
        if autoSync:
            self.onFirstExecBegin.append(self.eventSync)
        self.onClose.append(self.engine.close)
        self.onClose.append(self.delTimers)

    def applyExternalStyleNow(self):
        r = self.engine.renderer
        try:
            r.hideSubtitle()
        except Exception:
            pass
        if hasattr(r, "reloadSettings"):
            r.reloadSettings()
        self.engine.renderSub()

    def externalStyle(self):
        if self.externalSettings is None:
            self.session.openMessageBox(_("External settings not provided!"), MessageBox.TYPEERROR, timeout=3)
            return
        self.session.open(
            DVBExternalStyleProScreen,
            self.externalSettings,
            self.applyExternalStyleNow
    )

    def confirmClose(self):
        def cb(answer):
            if answer:
                self.close()

        self.session.openWithCallback(
            cb,
            MessageBox,
            _("Exit SubsSupportPro DVB player?"),
            MessageBox.TYPE_YESNO
        )

    def showHelp(self):
        txt = "\n".join([
            _("Controls:"),
            "",
            _("RED: Open Subtitle Picker"),
            _("YELLOW: Sync subtitle to current event"),
            _("BLUE: Change subtitles FPS"),
            _("OK: Show/Hide status panel"),
            _("LEFT: Previous subtitle"),
            _("RIGHT: Next subtitle"),
            _("UP/DOWN: Restart current subtitle"),
            _("PREV/REWIND (short): -1 minute"),
            _("NEXT/FF (short): +1 minute"),
            _("PREV (long): Manual -minutes jump"),
            _("NEXT (long): Manual +minutes jump"),
            _("5: Apply saved delay"),
            _("6: Save current delay for this channel"),
            _("EXIT: Exit (confirm)"),
            _("MENU: Show subtitle Style Settings"),
            _("INFO: Show this help"),
        ])
        self.session.open(MessageBox, txt, MessageBox.TYPE_INFO, timeout=20)

    def openSubtitleProPicker(self):
        #print("[DEBUG] RED button pressed - Attempting to open SubtitleProPicker")
        try:
            subtitleList = self.engine.getSubtitlesList()  # Get a list of subtitles
            currentIndex = self.engine.getPosition()  # Get the current subtitle index

            if not subtitleList:
                print("[ERROR] No subtitles available to open SubtitleProPicker")
                return
            print('[DEBUG] Opening SubtitleProPicker with {} items'.format(len(subtitleList)))
            self.session.openWithCallback(self.onSubtitlePicked, SubtitleProPicker, subtitleList, currentIndex)
            print("[DEBUG] SubtitleProPicker opened successfully")
        except Exception as e:
            print('[ERROR] Failed to open SubtitleProPicker: {}'.format(e))



    def onSubtitlePicked(self, index=None):
        if index is not None:
            self.engine.setPosition(index)
            self.engine.renderSub()  # Ensure the new subtitle is displayed immediately
            self.engine.setRefTime()  # Reset timing to allow automatic progression
            self.engine.startHideTimer()  # Restart timer for next subtitle
            self.showStatus(True)  # Refresh UI

    def startEventTimer(self):
        self.eventTimer.start(500)

    def startSubtitlesTimer(self):
        self.subtitlesTimer.start(self.subtitlesTimerStep)

    def setProvidedSubtitlesFps(self):
        self.engine.setSubsFps(self.providedSubtitlesFps)
        self.updateSubtitlesFps()

    def onUpdateSubPosition(self, position):
        self.updateSubtitlesPosition(position)

    def onRenderSub(self, sub):
        if self['subtitle'].visible:
            self.updateSubtitle(sub, True)
        if self['subtitlesTime'].visible:
            self.updateSubtitlesTime(sub)

    def onHideSub(self, sub):
        if sub == self.engine.subsList[-1]:
            self.subtitlesTimer.stop()
        if self['subtitle'].visible:
            nextSubIdx = self.engine.subsList.index(sub) + 1
            if nextSubIdx >= len(self.engine.subsList) - 1:
                nextSub = None
            else:
                nextSub = self.engine.subsList[nextSubIdx]
            self.updateSubtitle(nextSub, active=False)

    def showStatusWithTimer(self):
        self.showStatus(True)

    def showStatus(self, withTimer=False):
        sub = self.engine.getCurrentSub()
        active = self.engine.renderer.subShown
        self.updateSubtitle(sub, active)
        self.updateSubtitlesFps()
        self.updateSubtitlesPosition()
        self.updateEventStatus()
        self['instruction'].visible = True
        self['subtitle'].visible = True
        self['subtitlesPosition'].visible = True
        self['subtitlesTime'].visible = True
        self['subtitlesFps'].visible = True
        self['eventName'].visible = True
        self['eventTime'].visible = True
        self['eventDuration'].visible = True
        if withTimer and not self.statusLocked:
            self.hideTimer.start(self.hideTimerDelay, True)

    def hideStatus(self):
        self['instruction'].visible = False
        self['subtitle'].visible = False
        self['subtitlesPosition'].visible = False
        self['subtitlesTime'].visible = False
        self['subtitlesFps'].visible = False
        self['eventName'].visible = False
        self['eventTime'].visible = False
        self['eventDuration'].visible = False

    def updateSubtitle(self, sub, active):
        if sub is None:
            self['subtitle'].setText("")
            return
        st = sub['start'] * self.engine.fpsRatio / 90000
        et = sub['end'] * self.engine.fpsRatio / 90000
        stStr = "%d:%02d:%02d" % ((st / 3600, st % 3600 / 60, st % 60))
        etStr = "%d:%02d:%02d" % ((et / 3600, et % 3600 / 60, et % 60))
        if active:
            self['subtitle'].instance.setForegroundColor(parseColor("#F7A900"))
            self['subtitle'].setText("%s ----> %s" % (stStr, etStr))
        else:
            self['subtitle'].instance.setForegroundColor(parseColor("#aaaaaa"))
            self['subtitle'].setText("%s ----> %s" % (stStr, etStr))

    def updateSubtitlesPosition(self, position=None):
        if position is None:
            position = self.engine.subsList.index(self.engine.getCurrentSub())
        self['subtitlesPosition'].setText("%s: %d / %d" % (_("Subtitles Position"), position, len(self.engine.subsList) - 1))

    def updateSubtitlesTime(self, sub=None):
        if sub:
            self._baseTime = sub['start'] * self.engine.fpsRatio / 90
            self._accTime = 0
            if not self.engine.isPaused():
                self.startSubtitlesTimer()
        else:
            self._accTime += self.subtitlesTimerStep
        self._subtitlesTime = self._baseTime + self._accTime
        if self['subtitlesTime'].visible:
            st = self._subtitlesTime / 1000
            time = "%d:%02d:%02d" % (st / 3600, st % 3600 / 60, st % 60)
            self['subtitlesTime'].setText("%s: %s" % (_("Subtitles Time"), time))

    def updateSubtitlesFps(self):
        subsFps = self.engine.getSubsFps()
        videoFps = getFps(self.session, True)
        if subsFps is None or videoFps is None:
            self['subtitlesFps'].setText("%s: %s" % (_("Subtitles FPS"), _("unknown")))
            return
        if subsFps == videoFps:
            if self.providedSubtitlesFps is not None:
                if self.providedSubtitlesFps == videoFps:
                    self['subtitlesFps'].setText("%s: %s (%s)" % (_("Subtitles FPS"), _("original"), _("original")))
                else:
                    self['subtitlesFps'].setText("%s: %s (%s)" % (_("Subtitles FPS"), _("original"), str(self.providedSubtitlesFps)))
            else:
                self['subtitlesFps'].setText("%s: %s" % (_("Subtitles FPS"), _("original")))
        else:
            if self.providedSubtitlesFps is not None:
                if self.providedSubtitlesFps == videoFps:
                    self['subtitlesFps'].setText("%s: %s (%s)" % (_("Subtitles FPS"), str(subsFps), _("original")))
                else:
                    self['subtitlesFps'].setText("%s: %s (%s)" % (_("Subtitles FPS"), str(subsFps), str(self.providedSubtitlesFps)))
            else:
                self['subtitlesFps'].setText("%s: %s" % (_("Subtitles FPS"), str(subsFps)))

    def updateEventStatus(self):
        event = self.session.screen["Event_Now"].getEvent()
        if event is not None:
            eventName = event.getEventName()
            if eventName:
                if self["eventName"].getText() != eventName:
                    self["eventName"].setText("%s" % eventName)
            else:
                self["eventName"].setText("%s" % (_("unknown")))
            eventStartTime = event.getBeginTime()
            if eventStartTime:
                ep = int(time.time()) - eventStartTime
                self["eventTime"].setText("%s: %d:%02d:%02d" % (_("Time"), ep / 3600, ep % 3600 / 60, ep % 60))
            else:
                self["eventTime"].setText("%s: %s" % (_("Event Time"), "0:00:00"))
            eventDuration = event.getDuration()
            if eventDuration:
                if eventStartTime:
                    eventProgress = int(time.time()) - eventStartTime
                    if eventProgress > eventDuration:
                        ed = 0
                    else:
                        ed = eventDuration
                else:
                    ed = eventDuration
                self["eventDuration"].setText("%s: %d:%02d:%02d" % (_("Duration"), ed / 3600, ed % 3600 / 60, ed % 60))
            else:
                self["eventTime"].setText("%s: %s" % (_("Event Duration"), "0:00:00"))
        else:
            self["eventName"].setText("")
            self["eventTime"].setText("")
            self["eventDuration"].setText("")

    def changeFps(self):
        subsFps = self.engine.getSubsFps()
        if subsFps is None:
            return
        currIdx = self.fpsChoices.index(str(subsFps))
        if currIdx == len(self.fpsChoices) - 1:
            nextIdx = 0
        else:
            nextIdx = currIdx + 1
        self.engine.setSubsFps(fps_float(self.fpsChoices[nextIdx]))
        self.updateSubtitlesFps()
        sub = self.engine.getCurrentSub()
        active = self.engine.renderer.subShown
        self.updateSubtitle(sub, active)
        self.updateSubtitlesPosition()
        self.showStatus(True)

    def showHideStatus(self):
        if self['subtitle'].visible:
            self.statusLocked = False
            self.hideStatus()
        else:
            self.statusLocked = True
            self.showStatus()

    def eventSync(self):
        event = self.session.screen["Event_Now"].getEvent()
        if event is not None:
            progress = (int(time.time()) - event.getBeginTime()) * 1000
            self.engine.seekTo(progress)
        else:
            self.session.open(MessageBox, _("cannot sync to event, event is not available"), MessageBox.TYPE_INFO, simple=True, timeout=3)

    def playPause(self):
        if self.engine.isPaused():
            self.resume()
        else:
            self.pause()

    def pause(self):
        self.engine.pause()
        self.subtitlesTimer.stop()
        self.showStatus()

    def resume(self):
        self.engine.resume()
        self.startSubtitlesTimer()
        self.showStatus(True)

    def restart(self):
        self.engine.pause()
        self.engine.resume()
        self.showStatus(True)

    def nextSkip(self):
        self.engine.toNextSub()
        self.showStatus(True)

    def nextMinuteSkip(self):
        self.engine.seekRelative(60 * 1000)
        self.showStatus(True)

    def nextManual(self):
        def nextManualCB(minutes):
            if minutes > 0:
                self.engine.seekRelative(minutes * 60 * 1000)
                self.showStatus(True)
        self.session.openWithCallback(nextManualCB, MinuteInput)

    def previousSkip(self):
        self.engine.toPrevSub()
        self.showStatus(True)

    def previousMinuteSkip(self):
        self.engine.seekRelative(-60 * 1000)
        self.showStatus(True)

    def previousManual(self):
        def previousManualCB(minutes):
            if minutes > 0:
                self.engine.seekRelative(-minutes * 60 * 1000)
                self.showStatus(True)
        self.session.openWithCallback(previousManualCB, MinuteInput)

    def delTimers(self):
        self.hideTimer.stop()
        del self.hideTimer_conn
        del self.hideTimer
        self.eventTimer.stop()
        del self.eventTimer_conn
        del self.eventTimer
        self.subtitlesTimer.stop()
        del self.subtitlesTimer_conn
        del self.subtitlesTimer

    # -----------------------------------------------------------
    #  Save-delay hot-key
    # -----------------------------------------------------------
    def saveCurrentDelay(self):
        """
        Compute subtitle <-> event offset *now* and store it so we can
        re-apply it next time we zap to this service.
        """
        event = self.session.screen["Event_Now"].getEvent()
        if not event:
            self.session.open(MessageBox,
                _("Cannot save delay - event information unavailable"),
                MessageBox.TYPE_INFO, simple=True, timeout=3)
            return

        # current video position relative to event start
        elapsed = int(time.time()) - event.getBeginTime()     # seconds
        self.updateSubtitlesTime()        # <-- add this line
        # current subtitle timestamp (we keep it in ms)
        subtitle_ts = self._subtitlesTime / 1000.0            # seconds

        delay = elapsed - subtitle_ts     # <-- correct sign

        # store it
        self.engine.saveMainDelayToJson(delay, subs_fps=self.engine.getSubsFps())


        # feedback
        self.session.open(MessageBox,
            _("Delay of %.2f s saved for this channel") % delay,
            MessageBox.TYPE_INFO, simple=True, timeout=3)
    # -----------------------------------------------------------

    def applySavedDelay(self):
        """Apply previously stored delay for this service."""
        self.engine.applySavedDelay()
        self.showStatus(True)

class SubsEngineDVB(object):
    def __init__(self, session, engineSettings, renderer):
        self.session = session
        self.renderer = renderer
        # --- delay persistence ------------------------------
        self.json_path = "/tmp/subsSupport_delays.json"  # any writable place
        if not os.path.exists(os.path.dirname(self.json_path)):
            os.makedirs(os.path.dirname(self.json_path))
        self.channel_reference = self.getCurrentChannelReference()
        # ----------------------------------------------------
        self.delay = 0
        self.__position = 0
        self.fpsRatio = 1
        self.subsList = None
        self.paused = True
        self.waitTimer = eTimer()
        self.waitTimer_conn = eConnectCallback(self.waitTimer.timeout, self.doWait)
        self.hideTimer = eTimer()
        self.hideTimer_conn = eConnectCallback(self.hideTimer.timeout, self.hideTimerCallback)
        self.onRenderSub = []
        self.onHideSub = []
        self.onPositionUpdate = []
        
    def getSubtitlesList(self):
        """Returns a list of available subtitles with timestamps."""
        result = []
        for idx, sub in enumerate(self.subsList):
            # Check if the subtitle has rows (multi-line) or just text
            if 'rows' in sub:
                # Combine all rows into a single string with newlines
                text = u'\n'.join([toUnicode(row.get('text', '')) for row in sub['rows']])
            else:
                text = toUnicode(sub.get('text', ''))
                
            result.append({
                "index": idx,
                "text": text,
                "start": sub["start"] / 90000,  # 90,000 ticks per second
                "end": sub["end"] / 90000,
            })
        return result


    def setSubsList(self, subsList):
        self.subsList = subsList

    def setSubsFps(self, subsFps):
        print("[SubsEngineDVB] setSubsFps - setting fps to %s" % str(subsFps))
        videoFps = getFps(self.session, True)
        if videoFps is None:
            print("[SubsEngineDVB] setSubsFps - cannot get video fps!")
        else:
            self.waitTimer.stop()
            self.hideTimer.stop()
            base = subsFps / float(videoFps)
            override = self.getFpsDriftOverride()
            self.fpsRatio = base * override
            self.setRefTime()                 # <-- keeps timing coherent
            self.renderSub()
            if not self.paused:
                self.setRefTime()
                self.startHideTimer()

    def setPosition(self, position):
        if position > len(self.subsList) - 1:
            return
        self.__position = position
        for f in self.onPositionUpdate:
            f(self.__position)

    def getPosition(self):
        return self.__position

    position = property(getPosition, setPosition)

    def getSubsFps(self):
        videoFps = getFps(self.session, True)
        if videoFps is None:
            return None
        return fps_float(self.fpsRatio * videoFps)

    def getCurrentSub(self):
        return self.subsList[self.position]

    def _safeRatio(self, cfg, default=1.0):
        try:
            s = str(cfg.value).strip().replace(",", ".")
            v = float(s)
            # optional clamp to avoid insane values
            if v < 0.80 or v > 1.20:
                return default
            return v
        except:
            return default

    def getFpsDriftOverride(self):
        if not config.plugins.subsSupportPro.dvb.fpsDriftEnable.value:
            return 1.0

        videoFps = getFps(self.session, True)
        if videoFps is None:
            return 1.0

        vf = "%.3f" % float(videoFps)

        m = {
            "23.976": config.plugins.subsSupportPro.dvb.fpsRatio_23_976,
            "24.000": config.plugins.subsSupportPro.dvb.fpsRatio_24_000,
            "25.000": config.plugins.subsSupportPro.dvb.fpsRatio_25_000,
            "29.970": config.plugins.subsSupportPro.dvb.fpsRatio_29_970,
            "30.000": config.plugins.subsSupportPro.dvb.fpsRatio_30_000,
            "50.000": config.plugins.subsSupportPro.dvb.fpsRatio_50_000,
            "59.940": config.plugins.subsSupportPro.dvb.fpsRatio_59_940,
        }

        cfg = m.get(vf)
        return self._safeRatio(cfg, 1.0) if cfg else 1.0

    def setRefTime(self):
        self.reftime = time.time() * 1000
        self.refposition = self.position
        self.delay = 0

    def isPaused(self):
        return self.paused

    def start(self):
        self.renderer.show()
        self.resume()

    def pause(self):
        self.waitTimer.stop()
        self.hideTimer.stop()
        self.paused = True

    def resume(self):
        self.waitTimer.stop()
        self.hideTimer.stop()
        self.setRefTime()
        self.renderSub()
        self.paused = False
        self.startHideTimer()

    def renderSub(self):
        for f in self.onRenderSub:
            f(self.subsList[self.position])
        
        # Check if the subtitle has rows (multi-line) or just text
        if 'rows' in self.subsList[self.position]:
            # For multi-line subtitles, we need to combine them
            combined_text = '\n'.join([row['text'] for row in self.subsList[self.position]['rows']])
            # Create a temporary subtitle dict with combined text
            temp_sub = self.subsList[self.position].copy()
            temp_sub['text'] = combined_text
            self.renderer.setSubtitle(temp_sub)
        else:
            self.renderer.setSubtitle(self.subsList[self.position])

    def hideSub(self):
        for f in self.onHideSub:
            f(self.subsList[self.position])
        self.renderer.hideSubtitle()

    def startHideTimer(self):
        self.hideTimer.start(int(self.subsList[self.position]['duration'] * self.fpsRatio), True)

    def hideTimerCallback(self):
        self.hideTimer.stop()
        self.waitTimer.stop()
        if self.position == len(self.subsList) - 1:
            self.hideSub()
        elif self.subsList[self.position]['end'] * self.fpsRatio + (200 * 90) < self.subsList[self.position + 1]['start'] * self.fpsRatio:
            self.hideSub()

        if self.position < len(self.subsList) - 1:
            self.position += 1
            self.toTime = self.reftime + ((self.subsList[self.position]['start'] - self.subsList[self.refposition]['start']) / 90 * self.fpsRatio)
            timeout = ((self.subsList[self.position]['start'] - self.subsList[self.position - 1]['end']) / 90 * self.fpsRatio) + self.delay
            self.waitTimer.start(int(timeout), True)

    def doWait(self):
        timeNow = time.time() * 1000
        delay = int(self.toTime - timeNow)
        if delay > 50:
            self.waitTimer.start(delay, True)
        elif delay <= 50 and delay >= 0:
            print("[SubsEngineDVB] sub shown sooner by %s ms" % (delay))
            self.delay = 0
            self.waitTimer.stop()
            self.renderSub()
            self.startHideTimer()
        else:
            print("[SubsEngineDVB] sub shown later by %s ms" % (abs(delay)))
            self.delay = delay
            self.waitTimer.stop()
            self.renderSub()
            self.startHideTimer()

    def seekTo(self, time):
        self.waitTimer.stop()
        self.hideTimer.stop()
        print("[SubsEngineDVB] seekTo, position before seek: %d" % self.position)
        firstSub = self.subsList[0]
        lastSub = self.subsList[-1]
        position = self.position
        if time > lastSub['start'] / 90 * self.fpsRatio:
            position = self.subsList.index(lastSub)
        elif time < firstSub['start'] / 90 * self.fpsRatio:
            position = 0
        elif abs(time - (firstSub['start'] / 90 * self.fpsRatio)) < abs(time - (lastSub['start'] / 90 * self.fpsRatio)):
            position = 0
            subStartTime = firstSub['start'] / 90 * self.fpsRatio
            while time > subStartTime:
                position += 1
                subStartTime = self.subsList[position]['start'] / 90 * self.fpsRatio
        else:
            position = self.subsList.index(lastSub)
            subStartTime = lastSub['start'] / 90 * self.fpsRatio
            while time < subStartTime:
                position -= 1
                subStartTime = self.subsList[position]['start'] / 90 * self.fpsRatio
        self.position = position
        print("[SubsEngineDVB] seekTo, position after seek: %d" % (self.position))
        self.renderSub()
        if not self.paused:
            self.setRefTime()
            self.startHideTimer()

    def seekRelative(self, time):
        self.waitTimer.stop()
        self.hideTimer.stop()
        print("[SubsEngine] seekRelative, position before seek: %d" % self.position)
        startSubTime = self.subsList[self.position]['start'] / 90 * self.fpsRatio
        position = self.position
        if time > 0:
            nextStartSubTime = 0
            while position != len(self.subsList) - 1 and time > nextStartSubTime:
                position += 1
                nextStartSubTime = ((self.subsList[position]['start']) / 90 * self.fpsRatio) - startSubTime
        else:
            prevEndSubTime = 0
            while position != 0 and time < prevEndSubTime:
                position -= 1
                prevEndSubTime = (self.subsList[position]['end'] / 90 * self.fpsRatio) - startSubTime
        self.position = position
        print("[SubsEngine] seekRelative, position after seek: %d" % self.position)
        self.renderSub()
        if not self.paused:
            self.setRefTime()
            self.startHideTimer()

    def toNextSub(self):
        self.waitTimer.stop()
        self.hideTimer.stop()
        if self.renderer.subShown and self.position < len(self.subsList) - 1:
            self.position += 1
        self.renderSub()
        if not self.paused:
            self.setRefTime()
            self.startHideTimer()

    def toPrevSub(self):
        self.waitTimer.stop()
        self.hideTimer.stop()
        if self.position > 0:
            self.position -= 1
        self.renderSub()
        if not self.paused:
            self.setRefTime()
            self.startHideTimer()

    # ------------------------------------------------------------------
    #  Delay-persistence helpers
    # ------------------------------------------------------------------
    def getCurrentChannelReference(self):
        """Return a unique identifier for the *current* service."""
        try:
            event = self.session.screen["Event_Now"].getEvent()
            if event:
                return event.getEventName()
        except Exception as e:
            print("[SubsEngineDVB] getCurrentChannelReference error:", e)
        return "unknown_channel"

    # --- private json helpers ---
    def _loadDelayFile(self):
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, "r") as fh:
                    return json.load(fh)
            except Exception:
                pass
        return {}

    def _saveDelayFile(self, data):
        try:
            with open(self.json_path, "w") as fh:
                json.dump(data, fh, indent=4)
        except Exception as e:
            print("[SubsEngineDVB] cannot save delay file:", e)

    # --- public API ---
    def saveMainDelayToJson(self, delay, subs_fps=None):
        """
        Store both delay (seconds) *and* the subtitles FPS that was
        active when the user pressed "save".
        """
        if subs_fps is None:
            subs_fps = self.getSubsFps() or 0

        data = self._loadDelayFile()
        data[self.channel_reference] = {
            "delay": delay,
            "fps":   str(subs_fps),   # keep as string so we can compare easily
        }
        self._saveDelayFile(data)
        print("[SubsEngineDVB] saved %.3fs @ %s fps for %s"
              % (delay, subs_fps, self.channel_reference))


    def retrieveMainDelayFromJson(self):
        data = self._loadDelayFile()
        return data.get(self.channel_reference)   # may be None


    # subtitlesdvb.py  (inside SubsEngineDVB.applySavedDelay)
    def applySavedDelay(self):
        record = self.retrieveMainDelayFromJson()
        if not record:
            print("[SubsEngineDVB] no stored delay for", self.channel_reference)
            return

        delay_sec = record.get("delay", 0)
        saved_fps  = record.get("fps")

        # 1) restore FPS if necessary (unchanged)
        pass

        # 2) jump by the stored offset ---------------------------------
        # Current subtitle's (already fps-scaled) start-time in ms
        now_ms = self.subsList[self.position]['start'] / 90 * self.fpsRatio
        # Where we actually want to be:
        target_ms = now_ms + delay_sec * 1000
        # Move there in one go
        self.seekTo(target_ms)
        print("[SubsEngineDVB] applied saved delay %.3fs (seekTo)" % delay_sec)



    def close(self):
        self.waitTimer.stop()
        del self.waitTimer_conn
        del self.waitTimer
        self.hideTimer.stop()
        del self.hideTimer_conn
        del self.hideTimer
