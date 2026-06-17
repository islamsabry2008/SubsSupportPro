# -*- coding: utf-8 -*-
'''
Created on Feb 10, 2014

@author: marko
'''
from __future__ import absolute_import
try:
    from . import _
except ImportError:
    def _(txt):
        return txt

from .seeker import SubtitlesDownloadError, SubtitlesSearchError, SubtitlesErrors
from .xbmc_subtitles import (
    LocalDriveSeeker,
    SubsourceSeeker,
    Subf2mSeeker,
    SubdlSeeker,
    OpenSubtitles2Seeker,
    SubtitlesmoraSeeker,
    WyzieSeeker,
    NovalermoraSeeker,
)
