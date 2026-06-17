# -*- coding: utf-8 -*-
"""Helpers for the SubsSupport Wyzie subtitle provider.

The Wyzie API searches by IMDb or TMDb identifier.  SubsSupport normally passes
visible movie or series titles to an XBMC-style provider, so this module resolves
an IMDb title ID through the same lightweight IMDb suggestion CDN used by the
plugin UI before calling Wyzie.
"""
from __future__ import absolute_import
from __future__ import print_function

import os
import re
import time

import requests
import six
from six.moves.urllib.parse import quote

from ..utilities import log as _log
from ..user_agents import get_api_user_agent, get_random_ua


HTTP_SESSION = requests.Session()
IMDB_SUGGESTIONS_URL = "https://v3.sg.media-imdb.com/suggestion/x/%s.json"
IMDB_TIMEOUT = 6

MOVIE_TYPES = set(("movie", "tvMovie", "short", "video", "tvSpecial"))
TV_TYPES = set(("tvSeries", "tvMiniSeries", "tvEpisode", "tvSpecial"))

# Wyzie can occasionally expose an old source filename even when the payload is
# an SRT file.  Normalise local names to formats supported by SubsSupport.
SUPPORTED_FORMATS = {
    "srt": "srt",
    "ass": "ass",
    "ssa": "ass",
    "sub": "sub",
    "txt": "srt",
}
FORMAT_PRIORITY = {"srt": 3, "ass": 2, "sub": 1}

# Full-name -> ISO 639-1 conversion for the XBMC adapter interface.  Include the
# aliases commonly emitted by existing SubsSupport providers.
LANGUAGE_CODES = {
    "Albanian": "sq", "Arabic": "ar", "Belarusian": "hy",
    "Bosnian": "bs", "BosnianLatin": "bs", "Bulgarian": "bg",
    "Catalan": "ca", "Chinese": "zh", "Chinese (Traditional)": "zh",
    "Chinese (Simplified)": "zh", "Croatian": "hr", "Czech": "cs",
    "Danish": "da", "Dutch": "nl", "English": "en",
    "English (US)": "en", "English (UK)": "en", "Estonian": "et",
    "Persian": "fa", "Farsi": "fa", "Farsi/Persian": "fa",
    "Finnish": "fi", "French": "fr", "German": "de", "Greek": "el",
    "Hebrew": "he", "Hindi": "hi", "Hungarian": "hu",
    "Icelandic": "is", "Indonesian": "id", "Italian": "it",
    "Japanese": "ja", "Korean": "ko", "Latvian": "lv",
    "Lithuanian": "lt", "Macedonian": "mk", "Malay": "ms",
    "Norwegian": "no", "Polish": "pl", "Portuguese": "pt",
    "PortugueseBrazil": "pt-br", "Portuguese (Brazilian)": "pt-br",
    "Portuguese (Brazil)": "pt-br", "Portuguese-BR": "pt-br",
    "Brazilian": "pt-br", "Romanian": "ro", "Russian": "ru",
    "Serbian": "sr", "SerbianLatin": "sr", "Slovak": "sk",
    "Slovenian": "sl", "Spanish": "es", "Español": "es",
    "Español (Latinoamérica)": "es", "Español (España)": "es",
    "Spanish (Latin America)": "es", "Spanish (Spain)": "es",
    "Swedish": "sv", "Thai": "th", "Turkish": "tr",
    "Ukrainian": "uk", "Ukranian": "uk", "Vietnamese": "vi",
}
CODE_LANGUAGE_NAMES = {
    "sq": "Albanian", "ar": "Arabic", "hy": "Belarusian", "bs": "Bosnian",
    "bg": "Bulgarian", "ca": "Catalan", "zh": "Chinese", "hr": "Croatian",
    "cs": "Czech", "da": "Danish", "nl": "Dutch", "en": "English",
    "et": "Estonian", "fa": "Persian", "fi": "Finnish", "fr": "French",
    "de": "German", "el": "Greek", "he": "Hebrew", "hi": "Hindi",
    "hu": "Hungarian", "is": "Icelandic", "id": "Indonesian", "it": "Italian",
    "ja": "Japanese", "ko": "Korean", "lv": "Latvian", "lt": "Lithuanian",
    "mk": "Macedonian", "ms": "Malay", "no": "Norwegian", "pl": "Polish",
    "pt": "Portuguese", "pt-br": "Portuguese (Brazilian)", "ro": "Romanian",
    "ru": "Russian", "sr": "Serbian", "sk": "Slovak", "sl": "Slovenian",
    "es": "Spanish", "sv": "Swedish", "th": "Thai", "tr": "Turkish",
    "uk": "Ukrainian", "vi": "Vietnamese",
}

_IMDB_CACHE = {}


def to_text(value):
    if value is None:
        return ""
    return six.ensure_text(value, errors="replace") if isinstance(value, bytes) else six.text_type(value)


def log(module, msg):
    try:
        _log(module, to_text(msg))
    except Exception:
        print("[%s] %s" % (module, to_text(msg)))


def build_api_headers():
    return {
        "User-Agent": get_api_user_agent(),
        "Accept": "application/json",
    }


def build_download_headers():
    return {
        "User-Agent": get_random_ua(),
        "Accept": "application/octet-stream,*/*;q=0.8",
    }


TRANSIENT_NETWORK_ERRORS = (
    requests.exceptions.ConnectTimeout,
    requests.exceptions.ReadTimeout,
    requests.exceptions.ConnectionError,
)


def is_transient_network_error(error):
    """Return True only for temporary transport failures worth retrying."""
    return isinstance(error, TRANSIENT_NETWORK_ERRORS)


def _get_with_tls_fallback(url, kwargs):
    """Perform one HTTP GET, retrying only when the CA bundle is stale."""
    try:
        return HTTP_SESSION.get(url, verify=True, **kwargs)
    except requests.exceptions.SSLError:
        try:
            requests.packages.urllib3.disable_warnings()
        except Exception:
            pass
        return HTTP_SESSION.get(url, verify=False, **kwargs)


def request_get(url, headers=None, params=None, timeout=10, stream=False,
                retries=0, retry_delay=0.75):
    """GET with TLS fallback and bounded retries for temporary network errors.

    ``timeout`` may be either a single value or a ``(connect, read)`` tuple,
    which is supported by requests and is useful on slower Enigma2 receivers.
    Authentication errors and other HTTP failures are never retried.
    """
    kwargs = {
        "headers": headers or build_api_headers(),
        "params": params,
        "timeout": timeout,
        "stream": stream,
        "allow_redirects": True,
    }
    attempts = max(0, int(retries)) + 1
    last_error = None
    for attempt in range(attempts):
        try:
            response = _get_with_tls_fallback(url, kwargs)
            response.raise_for_status()
            return response
        except TRANSIENT_NETWORK_ERRORS as error:
            last_error = error
            if attempt >= attempts - 1:
                raise
            time.sleep(float(retry_delay) * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError("HTTP request failed")


def request_json(url, headers=None, params=None, timeout=10, retries=0,
                 retry_delay=0.75):
    return request_get(
        url,
        headers=headers,
        params=params,
        timeout=timeout,
        retries=retries,
        retry_delay=retry_delay,
    ).json()


def get_language_info(language):
    """Return language metadata for either a full name or ISO 639-1 code."""
    language = to_text(language).strip()
    if not language:
        return None
    lower = language.lower()
    if lower in CODE_LANGUAGE_NAMES:
        code = lower
        return {"name": CODE_LANGUAGE_NAMES[code], "2et": code}
    code = LANGUAGE_CODES.get(language)
    if code:
        return {"name": CODE_LANGUAGE_NAMES.get(code, language), "2et": code}
    for name, value in LANGUAGE_CODES.items():
        if name.lower() == lower:
            return {"name": CODE_LANGUAGE_NAMES.get(value, name), "2et": value}
    return None


def get_language_codes(*languages):
    result = []
    for language in languages:
        info = get_language_info(language)
        if info and info["2et"] not in result:
            result.append(info["2et"])
    return result


def get_language_name(code, fallback=""):
    code = to_text(code).strip().lower()
    return CODE_LANGUAGE_NAMES.get(code) or to_text(fallback).strip() or code or "Unknown"


def extract_external_id(value):
    """Return a direct IMDb title ID or manually entered numeric TMDb ID."""
    value = to_text(value).strip()
    match = re.search(r"\b(tt\d{5,12})\b", value, re.I)
    if match:
        return match.group(1).lower()
    if re.match(r"^\d{1,12}$", value):
        return value
    return None


def extract_year(value, fallback=None):
    try:
        fallback_year = int(fallback)
        if 1800 <= fallback_year <= 2200:
            return str(fallback_year)
    except Exception:
        pass
    match = re.search(r"(?:\(|\b)((?:19|20)\d{2})(?:\)|\b)", to_text(value))
    return match.group(1) if match else ""


def clean_title(value):
    value = os.path.basename(to_text(value))
    value = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", value)
    value = re.sub(r"\b[Ss]\d{1,2}[ ._\-]*[Ee]\d{1,3}\b", " ", value)
    value = re.sub(r"\b\d{1,2}[xX]\d{1,3}\b", " ", value)
    value = re.sub(r"\b(?:19|20)\d{2}\b", " ", value)
    value = re.sub(r"[._+\-]+", " ", value)
    value = re.split(
        r"\b(?:480p|720p|1080p|2160p|web\s*dl|webrip|bluray|brrip|hdrip|dvdrip|x264|x265|h264|h265|hevc|aac|dts)\b",
        value,
        maxsplit=1,
        flags=re.I,
    )[0]
    return re.sub(r"\s+", " ", value).strip(" ()[]{}-_")


def normalise_title(value):
    return re.sub(r"[^a-z0-9]+", "", clean_title(value).lower())


def resolve_external_id(value, year="", is_tv=False):
    """Resolve the best IMDb ID through the plugin's IMDb suggestion CDN."""
    direct_id = extract_external_id(value)
    if direct_id:
        return direct_id

    query = clean_title(value)
    if not query:
        return None
    expected_year = extract_year(value, year)
    cache_key = (query.lower(), expected_year, bool(is_tv))
    if cache_key in _IMDB_CACHE:
        return _IMDB_CACHE[cache_key]

    payload = request_json(
        IMDB_SUGGESTIONS_URL % quote(query.lower(), safe=""),
        headers=build_api_headers(),
        timeout=IMDB_TIMEOUT,
    )
    items = payload.get("d", []) if isinstance(payload, dict) else []
    query_key = normalise_title(query)
    preferred_types = TV_TYPES if is_tv else MOVIE_TYPES
    best = None

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        imdb_id = to_text(item.get("id"))
        item_title = to_text(item.get("l")).strip()
        item_type = to_text(item.get("qid"))
        if not imdb_id.startswith("tt") or not item_title:
            continue

        score = max(0, 100 - index)
        item_key = normalise_title(item_title)
        if item_key == query_key:
            score += 500
        elif item_key.startswith(query_key) or query_key.startswith(item_key):
            score += 120
        if item_type in preferred_types:
            score += 80
        elif item_type:
            score -= 40
        item_year = to_text(item.get("y"))
        if expected_year and item_year:
            score += 100 if item_year == expected_year else -25
        if best is None or score > best[0]:
            best = (score, imdb_id)

    resolved = best[1] if best else None
    _IMDB_CACHE[cache_key] = resolved
    return resolved


def iter_results(payload):
    """Current Wyzie response is a raw array; keep wrapper fallbacks too."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "subtitles", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def normalise_format(item):
    """Prefer Wyzie's format field and fall back to the legacy source name."""
    api_format = to_text(item.get("format")).lower().lstrip(".")
    filename_ext = os.path.splitext(to_text(item.get("fileName")))[1].lower().lstrip(".")
    if api_format in SUPPORTED_FORMATS:
        return SUPPORTED_FORMATS[api_format]
    if filename_ext in SUPPORTED_FORMATS:
        return SUPPORTED_FORMATS[filename_ext]
    return None


def safe_filename(value, subtitle_id, subtitle_format):
    subtitle_format = SUPPORTED_FORMATS.get(to_text(subtitle_format).lower().lstrip("."), "srt")
    extension = "." + subtitle_format
    filename = os.path.basename(to_text(value).replace("\\", "/"))
    filename = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", filename)
    filename = re.sub(r"\.{2,}", ".", filename).strip(" ._")
    if not filename:
        return "wyzie_%s%s" % (to_text(subtitle_id) or "subtitle", extension)
    stem, current_ext = os.path.splitext(filename)
    mapped_ext = SUPPORTED_FORMATS.get(current_ext.lower().lstrip("."))
    if mapped_ext != subtitle_format or current_ext.lower() != extension:
        filename = (stem or filename) + extension
    return filename


def result_text(item):
    values = [item.get("release"), item.get("fileName"), item.get("media")]
    releases = item.get("releases")
    if isinstance(releases, list):
        values.extend(releases)
    return " ".join([to_text(value) for value in values if value])


def extract_episode_pairs(text):
    pairs = set()
    patterns = (
        r"\b[Ss](\d{1,2})[ ._\-]*[Ee](\d{1,3})\b",
        r"\b(\d{1,2})[xX](\d{1,3})\b",
        r"\b[Ss]eason[ ._\-]*(\d{1,2})[ ._\-]*(?:[Ee]pisode|[Ee]p)[ ._\-]*(\d{1,3})\b",
    )
    for pattern in patterns:
        for found_season, found_episode in re.findall(pattern, to_text(text), re.I):
            try:
                pairs.add((int(found_season), int(found_episode)))
            except Exception:
                pass
    return pairs


def episode_match_score(item, season, episode):
    """Rank exact matches and reject only explicit different episodes."""
    try:
        expected = (int(season), int(episode))
    except Exception:
        return 0
    if expected[0] <= 0 or expected[1] <= 0:
        return 0
    pairs = extract_episode_pairs(result_text(item))
    if not pairs:
        return 0
    return 2 if expected in pairs else -1


def download_count(item):
    try:
        return int(item.get("downloadCount", 0) or 0)
    except Exception:
        return 0


def packed_type(filepath):
    try:
        with open(filepath, "rb") as handle:
            header = handle.read(8)
    except Exception:
        return None
    if header.startswith(b"PK\x03\x04"):
        return "zip"
    if header.startswith(b"Rar!\x1a\x07"):
        return "rar"
    return None


def sniff_plain_format(filepath, fallback="srt"):
    """Best-effort parser-safe extension after downloading a plain text file."""
    try:
        with open(filepath, "rb") as handle:
            sample = handle.read(8192).decode("utf-8", "ignore")
    except Exception:
        return SUPPORTED_FORMATS.get(to_text(fallback).lower(), "srt")
    stripped = sample.lstrip("\ufeff \t\r\n")
    if "[Script Info]" in sample or re.search(r"(?im)^Dialogue\s*:", sample):
        return "ass"
    if re.search(r"(?m)^\{\d+\}\{\d+\}", stripped):
        return "sub"
    if "-->" in sample:
        return "srt"
    return SUPPORTED_FORMATS.get(to_text(fallback).lower(), "srt")
