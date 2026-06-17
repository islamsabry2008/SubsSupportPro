# -*- coding: utf-8 -*-
import requests
import os
import re, json
import six
from six.moves.urllib.parse import quote_plus, urlsplit, urlunsplit
from ..utilities import log
from .SubdlUtilities import get_language_info
from ..user_agents import get_api_user_agent, get_random_ua
from ..seeker import SubtitlesDownloadError, SubtitlesErrors

SEARCH_URL = "https://api.subdl.com/api/v1/subtitles"
DOWNLOAD_URL = "https://dl.subdl.com"
API_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 30

def build_api_headers():
    """Return headers for SubDL REST API requests."""
    return {
        "User-Agent": get_api_user_agent(),
        "Accept": "application/json",
    }

def build_download_headers(include_api_key=False):
    """Return browser-like headers for ordinary SubDL file downloads.

    Keep direct downloads anonymous by default. SubDL currently allows the
    browser-style extensionless link without an API header, while sending a
    free/non-paid API key as x-api-key may trigger HTTP 402 Payment Required.
    """
    headers = {
        "User-Agent": get_random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://subdl.com/",
        "Connection": "keep-alive",
    }
    if include_api_key:
        api_key = get_subdl_api()
        if api_key:
            headers["x-api-key"] = api_key
    return headers



def _to_text(value):
    """Small Python 2/3-safe text helper used only by this provider."""
    if value is None:
        return ""
    try:
        return six.ensure_text(value, errors="replace")
    except Exception:
        try:
            return str(value)
        except Exception:
            return ""


def _strip_download_archive_extension(url):
    """Return the SubDL download URL without a trailing archive extension.

    SubDL search results can expose links such as /subtitle/99032-259647.rar,
    but the working CDN endpoint is often extensionless:
    https://dl.subdl.com/subtitle/99032-259647
    """
    url = _to_text(url).strip()
    if not url:
        return url
    try:
        parts = urlsplit(url)
        path = re.sub(r'\.(?:zip|rar)$', '', parts.path, flags=re.I)
        return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
    except Exception:
        return re.sub(r'\.(?:zip|rar)(?=([?#]|$))', '', url, flags=re.I)


def build_download_url(subtitle_id):
    """Return a valid SubDL download URL from API url field.

    Some SubDL API responses include a relative link, and some include a full URL.
    Keep the old single-URL helper for compatibility with any external caller.
    """
    subtitle_id = _to_text(subtitle_id).strip()
    if subtitle_id.startswith("http://") or subtitle_id.startswith("https://"):
        return subtitle_id
    return DOWNLOAD_URL.rstrip("/") + "/" + subtitle_id.lstrip("/")


def build_download_urls(subtitle_id):
    """Return SubDL download URL candidates, safest/current endpoint first."""
    original_url = build_download_url(subtitle_id)
    extensionless_url = _strip_download_archive_extension(original_url)
    urls = []
    for url in (extensionless_url, original_url):
        if url and url not in urls:
            urls.append(url)
    return urls


def _append_api_key_to_url(url, api_key):
    """Append api_key to a download URL without disturbing existing query."""
    url = _to_text(url).strip()
    api_key = _to_text(api_key).strip()
    if not url or not api_key:
        return url
    separator = "&" if "?" in url else "?"
    return url + separator + "api_key=" + quote_plus(api_key)


def build_download_attempts(subtitle_id):
    """Return ordered SubDL download attempts.

    The extensionless browser URL works for anonymous browser downloads. Paid
    API users can also use api_key or x-api-key, so those are kept as fallbacks
    instead of being forced first.
    """
    attempts = []
    api_key = get_subdl_api()
    for url in build_download_urls(subtitle_id):
        attempts.append((url, build_download_headers(False), "anonymous"))
    if api_key:
        for url in build_download_urls(subtitle_id):
            attempts.append((_append_api_key_to_url(url, api_key), build_download_headers(False), "api_key-query"))
        for url in build_download_urls(subtitle_id):
            attempts.append((url, build_download_headers(True), "x-api-key-header"))

    unique = []
    seen = set()
    for url, headers, mode in attempts:
        key = (url, mode)
        if url and key not in seen:
            unique.append((url, headers, mode))
            seen.add(key)
    return unique


def _safe_local_tmp_file(zip_subs, tmp_sub_dir, fallback_name):
    """Keep the temp file inside tmp_sub_dir even if the release name has slashes."""
    name = os.path.basename(_to_text(zip_subs).replace("\\", "/")).strip()
    if not name:
        name = fallback_name
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" ._")
    if not name:
        name = fallback_name
    return os.path.join(tmp_sub_dir, name)


def _raise_download_error(message):
    raise SubtitlesDownloadError(SubtitlesErrors.UNKNOWN_ERROR, message)



def get_subdl_api():
    global settings_provider  # Ensure we're using the existing instance
    API_KEY = settings_provider.getSetting("Subdl_API_KEY")
    if API_KEY:
        return API_KEY
    print("Error: SubDL API key is missing.")
    return None


def prepare_search_string(s):
    s = s.replace("'", "").strip()
    s = re.sub(r'\(\d\d\d\d\)$', '', s)  # remove year from title
    s = quote_plus(s)
    return s


def get_subtitles_list_movie(searchstring, title, languageshort, languagelong, subtitles_list):
    """Fetches subtitles from the SubDL API and adds them to subtitles_list."""
    if not searchstring:
        print("Empty search string provided")
        return

    API_KEY = get_subdl_api()
    if not API_KEY:
        print("Error: SubDL API key is missing.")
        return

    try:
        params = {
            "api_key": API_KEY,
            "film_name": searchstring,
            "type": "movie",
            "imdb_id": None,
            "languages": languageshort,
            "subs_per_page": 50
        }

        response = requests.get(SEARCH_URL, params=params, headers=build_api_headers(), timeout=API_TIMEOUT)
        response.raise_for_status()  # Raises exception for bad status codes
        
        json_data = response.json()
        status = json_data.get("status", False)
        
        if status:
            all_subs_data = json_data.get("subtitles", [])
            for item in all_subs_data:
                try:
                    language = item.get("lang")
                    filename = item.get("release_name")
                    id = item.get("url")
                    if language and filename and id:
                        subtitles_list.append({
                            'filename': filename, 
                            'sync': True, 
                            'id': id, 
                            'language_flag': languageshort, 
                            'language_name': languagelong
                        })
                except Exception as e:
                    print('Error processing subtitle item: {}'.format(e))
    except Exception as e:
        print('Error in get_subtitles_list_movie: {}'.format(e))

def get_subtitles_list_tv(searchstring, tvshow, season, episode, languageshort, languagelong, subtitles_list):
    """Fetches subtitles from the SubDL API and adds them to subtitles_list."""
    if not searchstring:
        print("Empty search string provided")
        return

    API_KEY = get_subdl_api()
    if not API_KEY:
        print("Error: SubDL API key is missing.")
        return

    try:
        params = {
            "api_key": API_KEY,
            "file_name": searchstring,
            "type": "tv",
            "imdb_id": None,
            "season_number": season,
            "episode_number": episode,
            "languages": languageshort,
            "subs_per_page": 50
        }

        response = requests.get(SEARCH_URL, params=params, headers=build_api_headers(), timeout=API_TIMEOUT)
        response.raise_for_status()  # Raises exception for bad status codes
        
        json_data = response.json()
        status = json_data.get("status", False)
        
        if status:
            all_subs_data = json_data.get("subtitles", [])
            for item in all_subs_data:
                try:
                    language = item.get("lang")
                    filename = item.get("release_name")
                    id = item.get("url")
                    if language and filename and id:
                        subtitles_list.append({
                            'filename': filename, 
                            'sync': True, 
                            'id': id, 
                            'language_flag': languageshort, 
                            'language_name': languagelong
                        })
                except Exception as e:
                    print('Error processing subtitle item: {}'.format(e))
    except Exception as e:
        print('Error in get_subtitles_list_tv: {}'.format(e))


def search_subtitles(file_original_path, title, tvshow, year, season, episode, set_temp, rar, lang1, lang2, lang3, stack): #standard input
    # Initialize empty list and message
    subtitles_list = []
    msg = ""
    
    # Get language info
    languagefound = lang1
    language_info = get_language_info(languagefound)
    language_info1 = language_info['name']
    language_info2 = language_info['2et']
    language_info3 = language_info['3et']

    # Check if we have something to search for
    if not title and not tvshow and not file_original_path:
        print("Nothing to search for - empty title, tvshow and file path")
        return subtitles_list, "", msg
    
    try:
        # Try to extract title from filename if no title/tvshow provided
        if not title and not tvshow and file_original_path:
            try:
                filename = os.path.basename(file_original_path)
                # Simple pattern to extract title from filename
                match = re.match(r'^(.*?)(?:\.\d{4}|\.S\d{2}E\d{2}|\.\d{3,4}p|\.\w{2,3})?\.\w+$', filename)
                if match:
                    title = match.group(1).replace('.', ' ').strip()
                    print('Derived title from filename: {}'.format(title))
            except Exception as e:
                print('Error extracting title from filename: {}'.format(e))

        if len(tvshow) == 0 and year: # Movie
            searchstring = "%s (%s)" % (title, year)
            print(("searchstring", searchstring))
            get_subtitles_list_movie(searchstring, title, language_info2, language_info1, subtitles_list)
        elif len(tvshow) > 0 and title == tvshow: # Movie not in Library
            print(len(tvshow))
            searchstring = "%s" % (tvshow)
            print(("searchstring", searchstring))
            get_subtitles_list_tv(searchstring, tvshow, season, episode, language_info2, language_info1, subtitles_list)
        elif len(tvshow) > 0: # TVShow
            searchstring = "%s S%#02dE%#02d" % (tvshow, int(season), int(episode))
            print(("searchstring", searchstring))
            get_subtitles_list_tv(searchstring, tvshow, season, episode, language_info2, language_info1, subtitles_list)
        elif title: # Just title
            searchstring = title.replace(' ', '+').replace("'", "").lower()
            print(("searchstring", searchstring))
            get_subtitles_list_movie(searchstring, title, language_info2, language_info1, subtitles_list)
    except Exception as e:
        print('Error in search_subtitles: {}'.format(e))
        return subtitles_list, "", str(e)
    
    return subtitles_list, "", msg #standard output


def download_subtitles(subtitles_list, pos, zip_subs, tmp_sub_dir, sub_folder, session_id):
    subtitle_id = subtitles_list[pos]["id"]
    language = subtitles_list[pos]["language_name"]
    download_url = build_download_url(subtitle_id)

    if not os.path.exists(tmp_sub_dir):
        os.makedirs(tmp_sub_dir)

    response = None
    used_download_url = None
    download_errors = []

    for candidate_url, headers, mode in build_download_attempts(subtitle_id):
        try:
            response = requests.get(
                candidate_url,
                headers=headers,
                stream=True,
                timeout=DOWNLOAD_TIMEOUT,
                allow_redirects=True
            )
            response.raise_for_status()
            used_download_url = candidate_url
            break
        except requests.RequestException as error:
            download_errors.append("%s [%s]: %s" % (candidate_url, mode, error))

    if response is None or used_download_url is None:
        _raise_download_error("SubDL download failed from all candidates: %s" % " | ".join(download_errors))

    local_tmp_file = _safe_local_tmp_file(zip_subs, tmp_sub_dir, "subdl_subtitle")
    packed = False
    subs_file = ""

    with open(local_tmp_file, 'wb') as file:
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                file.write(chunk)

    if not os.path.isfile(local_tmp_file) or os.path.getsize(local_tmp_file) == 0:
        _raise_download_error("SubDL downloaded an empty subtitle file from %s" % used_download_url)

    with open(local_tmp_file, "rb") as f:
        header = f.read(2)
        if header.startswith(b'R'):
            packed = True
            subs_file = "rar"
        elif header.startswith(b'P'):
            packed = True
            subs_file = "zip"
        else:
            subs_file = local_tmp_file

    return packed, language, subs_file
