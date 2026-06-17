# -*- coding: utf-8 -*-
"""XBMC-style service adapter for https://sub.wyzie.io/."""
from __future__ import absolute_import
from __future__ import print_function

import os
import re
import shutil

from ..seeker import SubtitlesDownloadError, SubtitlesErrors
from .WyzieUtilities import (
    FORMAT_PRIORITY,
    build_api_headers,
    build_download_headers,
    download_count,
    episode_match_score,
    get_language_codes,
    get_language_name,
    iter_results,
    is_transient_network_error,
    normalise_format,
    packed_type,
    request_get,
    request_json,
    resolve_external_id,
    safe_filename,
    sniff_plain_format,
    to_text,
)

SEARCH_URL = "https://sub.wyzie.io/search"
SOURCES_URL = "https://sub.wyzie.io/sources"
# A connect/read tuple prevents a slow upstream source from blocking forever.
DEFAULT_SEARCH_TIMEOUT = (5, 12)
FALLBACK_SEARCH_TIMEOUT = (5, 18)
DOWNLOAD_TIMEOUT = (5, 30)
# If the default Wyzie fan-out stalls, query currently documented sources one
# at a time.  The /sources?key endpoint is used first when possible so the
# provider does not waste time on sources unavailable for the user's key.
FALLBACK_SOURCE_PREFERENCE = (
    "subdl",
    "opensubtitles",
    "tvsubtitles",
    "yify",
    "subf2m",
    "podnapisi",
    "gestdown",
    "kitsunekko",
)


def get_wyzie_api():
    provider = globals().get("settings_provider")
    if provider is None:
        return ""
    try:
        return to_text(provider.getSetting("Wyzie_API_KEY")).strip()
    except Exception:
        return ""


def derive_title_from_path(filepath):
    filename = os.path.basename(to_text(filepath))
    filename = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", filename)
    return filename.replace(".", " ").replace("_", " ").strip()


def _normalised_episode_values(season, episode):
    try:
        season = int(season)
        episode = int(episode)
    except Exception:
        return 0, 0
    return season if season > 0 else 0, episode if episode > 0 else 0


def _dedupe_key(language_code, subtitle_format, filename, item):
    release = re.sub(r"\s+", " ", to_text(item.get("release")).lower()).strip()
    return language_code, subtitle_format, to_text(filename).lower(), release



def _http_status(error):
    response = getattr(error, "response", None)
    try:
        return response.status_code
    except Exception:
        return None


def _ordered_source_list(params):
    """Return source fallbacks valid for the configured Wyzie API key.

    Wyzie exposes /sources?key=... so clients can see which sources are
    currently enabled and available for that key.  If that lookup fails, keep a
    conservative documented preference list.
    """
    api_key = to_text(params.get("key")).strip()
    discovered = []
    if api_key:
        try:
            payload = request_json(
                SOURCES_URL,
                headers=build_api_headers(),
                params={"key": api_key},
                timeout=(4, 8),
                retries=1,
            )
            if isinstance(payload, dict):
                for field in ("available", "free", "sources"):
                    value = payload.get(field)
                    if isinstance(value, list):
                        for source in value:
                            source = to_text(source).strip().lower()
                            if source and source not in discovered:
                                discovered.append(source)
        except Exception as error:
            print("[Wyzie] could not fetch source list: %s" % error)

    ordered = []
    for source in FALLBACK_SOURCE_PREFERENCE:
        if (not discovered or source in discovered) and source not in ordered:
            ordered.append(source)
    for source in discovered:
        if source not in ordered:
            ordered.append(source)
    return ordered


def _fetch_search_payload(params):
    """Fetch Wyzie results and recover from slow default-source fan-out.

    The normal request is attempted first to preserve the API's default
    behaviour.  If it hits a temporary transport timeout, fall back to
    currently available documented sources explicitly.  This keeps normal
    searches unchanged while making Enigma2 receivers resilient to one slow
    upstream subtitle source.
    """
    try:
        return request_json(
            SEARCH_URL,
            headers=build_api_headers(),
            params=params,
            timeout=DEFAULT_SEARCH_TIMEOUT,
        )
    except Exception as error:
        if not is_transient_network_error(error):
            raise
        print("[Wyzie] default source timed out; trying source fallbacks")
        first_error = error

    saw_valid_empty_response = False
    last_error = first_error
    for source in _ordered_source_list(params):
        fallback_params = dict(params)
        fallback_params["source"] = source
        try:
            print("[Wyzie] retrying subtitle search with source=%s" % source)
            payload = request_json(
                SEARCH_URL,
                headers=build_api_headers(),
                params=fallback_params,
                timeout=FALLBACK_SEARCH_TIMEOUT,
            )
            results = iter_results(payload)
            if results:
                return payload
            saw_valid_empty_response = True
        except Exception as error:
            last_error = error
            status = _http_status(error)
            if status in (400, 402, 403, 404, 429):
                print("[Wyzie] source=%s skipped after HTTP %s: %s" % (source, status, error))
                continue
            if is_transient_network_error(error):
                print("[Wyzie] source=%s failed: %s" % (source, error))
                continue
            print("[Wyzie] source=%s failed: %s" % (source, error))
            continue

    if saw_valid_empty_response:
        return []
    raise last_error


def _build_result(item, is_tv=False, season=0, episode=0):
    if not isinstance(item, dict):
        return None
    download_url = to_text(item.get("url")).strip()
    if not download_url:
        return None
    subtitle_format = normalise_format(item)
    if not subtitle_format:
        return None

    episode_score = episode_match_score(item, season, episode) if is_tv else 0
    if episode_score < 0:
        # Keep ambiguous packs, but remove explicit wrong-episode entries.
        return None

    subtitle_id = to_text(item.get("id"))
    language_code = to_text(item.get("language")).strip().lower()
    filename = safe_filename(item.get("fileName") or item.get("release"), subtitle_id, subtitle_format)
    count = download_count(item)
    return {
        "filename": filename,
        "language_name": get_language_name(language_code, item.get("display")),
        "language_flag": language_code,
        "sync": bool(item.get("matchedRelease") or item.get("matchedFilter")),
        "id": subtitle_id,
        "url": download_url,
        "format": subtitle_format,
        "encoding": to_text(item.get("encoding")),
        "source": to_text(item.get("source")) or "Wyzie",
        "release": to_text(item.get("release")),
        "releases": item.get("releases") if isinstance(item.get("releases"), list) else [],
        "download_count": count,
        "origin": to_text(item.get("origin")),
        "hearing_impaired": bool(item.get("isHearingImpaired")),
        "ai": bool(item.get("ai")),
        "_episode_score": episode_score,
    }


def search_subtitles(file_original_path, title, tvshow, year, season, episode,
                     set_temp, rar, lang1, lang2, lang3, stack):
    """Standard SubsSupport XBMC-provider entry point."""
    subtitles_list = []
    api_key = get_wyzie_api()
    if not api_key:
        return subtitles_list, "", "Wyzie requires an API key"

    season, episode = _normalised_episode_values(season, episode)
    is_tv = bool(tvshow) or bool(season and episode)
    search_title = to_text(tvshow or title or derive_title_from_path(file_original_path))
    if not search_title:
        return subtitles_list, "", "Nothing to search for"

    try:
        external_id = resolve_external_id(search_title, year=year, is_tv=is_tv)
    except Exception as error:
        print("[Wyzie] IMDb ID lookup failed: %s" % error)
        return subtitles_list, "", "Wyzie could not resolve an IMDb ID"

    if not external_id:
        return subtitles_list, "", "Wyzie could not resolve an IMDb ID"

    params = {
        "id": external_id,
        "key": api_key,
        "format": "srt,ass,sub",
    }
    languages = get_language_codes(lang1, lang2, lang3)
    if languages:
        params["language"] = ",".join(languages)
    if is_tv and season and episode:
        params["season"] = season
        params["episode"] = episode

    try:
        print("[Wyzie] resolved '%s' to %s" % (search_title, external_id))
        payload = _fetch_search_payload(params)
    except Exception as error:
        print("[Wyzie] subtitle search failed: %s" % error)
        return subtitles_list, external_id, "Wyzie search failed: %s" % error

    best_by_release = {}
    for item in iter_results(payload):
        result = _build_result(item, is_tv=is_tv, season=season, episode=episode)
        if result is None:
            continue
        key = _dedupe_key(result["language_flag"], result["format"], result["filename"], item)
        previous = best_by_release.get(key)
        if previous is None or result["download_count"] > previous.get("download_count", 0):
            best_by_release[key] = result

    subtitles_list = list(best_by_release.values())
    subtitles_list.sort(
        key=lambda sub: (
            int(sub.get("_episode_score", 0)),
            1 if sub.get("sync") else 0,
            FORMAT_PRIORITY.get(sub.get("format"), 0),
            int(sub.get("download_count", 0) or 0),
        ),
        reverse=True,
    )
    for subtitle in subtitles_list:
        subtitle.pop("_episode_score", None)
    return subtitles_list, external_id, ""


def _rename_plain_file(filepath, subtitle_format):
    desired_extension = "." + subtitle_format
    stem, extension = os.path.splitext(filepath)
    if extension.lower() == desired_extension:
        return filepath
    destination = stem + desired_extension
    try:
        if os.path.exists(destination):
            os.remove(destination)
        shutil.move(filepath, destination)
        return destination
    except Exception:
        return filepath


def download_subtitles(subtitles_list, pos, zip_subs, tmp_sub_dir, sub_folder, session_id):
    """Download the direct URL returned by Wyzie."""
    try:
        selected = subtitles_list[pos]
    except Exception:
        raise SubtitlesDownloadError(SubtitlesErrors.UNKNOWN_ERROR, "Invalid Wyzie subtitle selection")

    download_url = to_text(selected.get("url")).strip()
    if not download_url:
        raise SubtitlesDownloadError(SubtitlesErrors.UNKNOWN_ERROR, "Wyzie subtitle URL is missing")

    language = selected.get("language_name", "")
    subtitle_format = selected.get("format", "srt")
    filename = safe_filename(selected.get("filename"), selected.get("id"), subtitle_format)
    if not os.path.exists(tmp_sub_dir):
        os.makedirs(tmp_sub_dir)
    local_tmp_file = os.path.join(tmp_sub_dir, "wyzie_" + filename)

    try:
        response = request_get(
            download_url,
            headers=build_download_headers(),
            timeout=DOWNLOAD_TIMEOUT,
            stream=True,
            retries=1,
        )
        with open(local_tmp_file, "wb") as output:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    output.write(chunk)
    except Exception as error:
        raise SubtitlesDownloadError(SubtitlesErrors.UNKNOWN_ERROR, "Wyzie download failed: %s" % error)

    if not os.path.isfile(local_tmp_file) or os.path.getsize(local_tmp_file) == 0:
        raise SubtitlesDownloadError(SubtitlesErrors.UNKNOWN_ERROR, "Wyzie downloaded an empty subtitle file")

    compressed = packed_type(local_tmp_file)
    if compressed:
        return True, language, local_tmp_file

    detected_format = sniff_plain_format(local_tmp_file, subtitle_format)
    local_tmp_file = _rename_plain_file(local_tmp_file, detected_format)
    return False, language, local_tmp_file


def test_api_key(api_key):
    api_key = to_text(api_key).strip()
    if not api_key:
        raise Exception("API key is required")
    payload = request_json(
        SEARCH_URL,
        headers=build_api_headers(),
        params={
            "id": "tt3659388",
            "language": "en",
            "format": "srt",
            "source": "charlie",
            "key": api_key,
        },
        timeout=FALLBACK_SEARCH_TIMEOUT,
        retries=1,
    )
    results = iter_results(payload)
    if not isinstance(results, list):
        raise Exception("Unexpected Wyzie response")
    return "Wyzie API key is valid and working (%d results)" % len(results)
