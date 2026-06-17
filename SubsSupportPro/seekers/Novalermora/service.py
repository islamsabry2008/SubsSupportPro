# -*- coding: utf-8 -*-
import io
import sys
import os
import re
import json
import requests
import time
from six.moves.urllib.parse import quote_plus, unquote
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from ..utilities import languageTranslate, log, getFileSize
from ..seeker import SubtitlesDownloadError, SubtitlesErrors

# Suppress insecure request warnings
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
from ..user_agents import get_random_ua
# Constants
HEADERS = {
    'User-Agent': get_random_ua(),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'fr,fr-FR;q=0.8,en-US;q=0.5,en;q=0.3',
    'Content-Type': 'text/html; charset=UTF-8',
    'Host': 'subs.ath.cx',
    'Referer': 'http://subs.ath.cx',
    'Upgrade-Insecure-Requests': '1',
    'Connection': 'keep-alive',
    'Accept-Encoding': 'gzip, deflate'
}

SESSION = requests.Session()
MAIN_URL = "http://subs.ath.cx"
DEBUG_PRETEXT = "subs.ath.cx"
CACHE_DIR = "/var/volatile/tmp"
CACHE_FILE = os.path.join(CACHE_DIR, "subs_ath_cx_subtitles.html")
CACHE_TIMEOUT = 86400  # 24 hours in seconds

# Roman numeral mapping
ROMAN_NUMERAL_MAP = [
    (r'\bII\b', '2'), (r'\bIII\b', '3'), (r'\bIV\b', '4'), (r'\bV\b', '5'),
    (r'\bVI\b', '6'), (r'\bVII\b', '7'), (r'\bVIII\b', '8'), (r'\bIX\b', '9'),
    (r'\bX\b', '10'), (r'\bXI\b', '11'), (r'\bXII\b', '12'), (r'\bXIII\b', '13'),
    (r'\bXIV\b', '14'), (r'\bXV\b', '15'), (r'\bXVI\b', '16'), (r'\bXVII\b', '17'),
    (r'\bXVIII\b', '18'), (r'\bXIX\b', '19'), (r'\bXX\b', '20'), (r'\bI\b', '1')
]

def get_url(url, referer=None):
    headers = {'User-Agent': HEADERS['User-Agent']}
    if referer:
        headers['Referer'] = referer
    
    response = SESSION.get(url, headers=headers, verify=False)
    return response.text.replace('\n', '')

def get_rating(downloads):
    return min(10, max(1, downloads // 50 + 1))

def generate_title_variations(text):
    """
    Generate variations of a title with both Roman numerals and digits
    """
    variations = [text]
    
    # Convert Roman numerals to digits
    digit_version = text
    for roman, digit in ROMAN_NUMERAL_MAP:
        digit_version = re.sub(roman, digit, digit_version, flags=re.IGNORECASE)
    if digit_version != text:
        variations.append(digit_version)
    
    # Convert digits to Roman numerals (reverse mapping)
    for roman, digit in ROMAN_NUMERAL_MAP:
        roman_version = re.sub(r'\b' + digit + r'\b', roman, text, flags=re.IGNORECASE)
        if roman_version != text and roman_version not in variations:
            variations.append(roman_version)
    
    return variations

def get_cached_content():
    """
    Get content from cache if available and not expired
    """
    if os.path.exists(CACHE_FILE):
        # Check if cache is still valid
        if time.time() - os.path.getmtime(CACHE_FILE) < CACHE_TIMEOUT:
            try:
                with io.open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                log(__name__, '{} Error reading cache: {}'.format(DEBUG_PRETEXT, e))
    
    return None

def save_content_to_cache(content):
    """
    Save content to cache file
    """
    try:
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)
        with io.open(CACHE_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
        log(__name__, '{} Content cached to {}'.format(DEBUG_PRETEXT, CACHE_FILE))
    except Exception as e:
        log(__name__, '{} Error saving cache: {}'.format(DEBUG_PRETEXT, e))


def _fetch_index_content(urls):
    """
    Fetch Novalermora listing content from its own /subtitles index.
    This provider intentionally uses subs.ath.cx/subtitles, while
    Subtitlesmora uses archive.org/download/mora25r.
    """
    cached = get_cached_content()
    if cached:
        log(__name__, '{} Using cached content from {}'.format(DEBUG_PRETEXT, CACHE_FILE))
        return cached

    last_error = None
    for url in urls:
        log(__name__, '{} Fetching: {}'.format(DEBUG_PRETEXT, url))
        try:
            response = SESSION.get(url, headers=HEADERS, verify=False, allow_redirects=True, timeout=20)
            response.raise_for_status()
            content = response.text
            # Cache only a useful looking directory/listing page.
            if content and '<a ' in content.lower():
                save_content_to_cache(content)
            return content
        except requests.RequestException as e:
            last_error = e
            log(__name__, '{} Failed to fetch {}: {}'.format(DEBUG_PRETEXT, url, e))
    if last_error:
        log(__name__, '{} Failed to fetch all index candidates: {}'.format(DEBUG_PRETEXT, last_error))
    return None


def _make_search_tokens(title):
    tokens = []
    raw = title.strip()
    dot = quote_plus(raw).replace('+', '.')
    plus = quote_plus(raw)
    space = re.escape(raw)
    plain_dot = re.escape(raw.replace(' ', '.'))
    plain_space = re.escape(raw)
    for token in (dot, plus, space, plain_dot, plain_space):
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _absolute_url(href):
    if href.startswith('http://') or href.startswith('https://'):
        return href
    if not href.startswith('/'):
        href = '/' + href
    return MAIN_URL + href


def _safe_filename_from_id(subtitle_id):
    name = subtitle_id.split('?')[0].rstrip('/').split('/')[-1]
    if not name:
        name = 'novalermora_subtitle.srt'
    return name


def _mora_text_type():
    try:
        return unicode
    except NameError:
        return str

def _mora_separator_for_value(value):
    sep = u'\u258e'
    text_type = _mora_text_type()
    if not isinstance(value, text_type):
        return sep.encode('utf-8')
    return sep

def _mora_skip_filename(filename):
    if not filename:
        return True
    if filename == 'subs4series':
        return True
    greek_label = u'\u0395\u03c1\u03b3\u03b1\u03c3\u03c4\u03ae\u03c1\u03b9 \u03a5\u03c0\u03bf\u03c4\u03af\u03c4\u03bb\u03c9\u03bd'
    try:
        if filename == greek_label:
            return True
        if not isinstance(filename, _mora_text_type()) and filename == greek_label.encode('utf-8'):
            return True
    except Exception:
        pass
    return False

def search_subtitles(file_path, title, tvshow, year, season, episode, set_temp, rar, lang1, lang2, lang3, stack):
    subtitles_list = []
    msg = ""

    # Check if title is blank or empty
    if not title or title.strip() == "":
        log(__name__, '{} Title is blank, skipping search'.format(DEBUG_PRETEXT))
        return subtitles_list, "", msg

    sep = _mora_separator_for_value(title)
    title = re.sub(' ' + sep, sep, title)

    # Define bad strings to remove
    lang_codes = [
        "ae", "al", "ar", "at", "ba", "be", "bg", "br", "cg", "ch", "cz", "da", "de", "dk",
        "ee", "en", "es", "eu", "ex-yu", "fi", "fr", "gr", "hr", "hu", "in", "ir", "it", "lt",
        "mk", "mx", "nl", "no", "pl", "pt", "ro", "rs", "ru", "se", "si", "sk", "sp", "tr",
        "uk", "us", "yu"
    ]
    bad_strings = [code + "|" for code in lang_codes]
    bad_strings += [code + sep for code in lang_codes]
    bad_strings += ["1080p", "4k", "720p", "hdrip", "hindi", "imdb", "vod", "x264"]
    
    # Remove bad strings from title
    for bad in bad_strings:
        title = title.replace(bad, "")
    
    # Clean up remaining special characters and spaces
    title = re.sub(r'[:,"&!?\-]', '', title).replace("  ", " ").strip()
    title = re.sub(r"'", '', title)
    
    # Generate title variations for Roman numerals
    title_variations = generate_title_variations(title)
    print('Title variations: {}'.format(title_variations))  # Debug print
    
    if tvshow:
        search_string = '{} S{:02d}E{:02d}'.format(tvshow, int(season), int(episode)) if title != tvshow else '{} ({:02d}{:02d})'.format(tvshow, int(season), int(episode))
    else:
        search_string = '{} ({})'.format(title, year) if year else title
    
    log(__name__, '{} Search string = {}'.format(DEBUG_PRETEXT, search_string))
    
    # Search for each title variation
    for title_var in title_variations:
        get_subtitles_list(title_var, search_string, "ar", "Arabic", subtitles_list)
        
    return subtitles_list, "", msg

def get_subtitles_list(title, search_string, lang_short, lang_long, subtitles_list):
    # Novalermora uses its own /subtitles listing URL.  Do not use the
    # Subtitlemora archive.org /download/mora25r path here.
    urls = [
        '{}/subtitles'.format(MAIN_URL)
    ]
    content = _fetch_index_content(urls)
    if content is None:
        return

    try:
        search_tokens = _make_search_tokens(title)
        rows = []
        for token in search_tokens:
            pattern = r'(<td>\s*<a\s+href=["\']([^"\']+)["\'][^>]*>.*?{}.*?</a>\s*</td>)'.format(token)
            found = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
            rows.extend(found)

        seen = set()
        for row, href in rows:
            match = re.search(r'<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', row, re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            id_, filename = match.groups()
            filename = re.sub(r'<[^>]+>', '', filename)
            filename = unquote(filename).replace('.srt', '').strip()
            if _mora_skip_filename(filename):
                continue
            dedupe_key = (id_, filename)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            log(__name__, '{} Found subtitle: {} (id = {})'.format(DEBUG_PRETEXT, filename, id_))
            subtitles_list.append({
                'no_files': 1,
                'filename': filename,
                'sync': True,
                'id': id_,
                'language_flag': 'flags/{}.gif'.format(lang_short),
                'language_name': lang_long
            })
    except Exception as e:
        log(__name__, '{} Error parsing subtitles: {}'.format(DEBUG_PRETEXT, e))

def download_subtitles(subtitles_list, pos, zip_subs, tmp_sub_dir, sub_folder, session_id):
    subtitle_info = subtitles_list[pos]
    language = subtitle_info["language_name"]
    subtitle_id = subtitle_info["id"]

    # Normalize ids from the Novalermora /subtitles listing.
    candidate_links = []
    if subtitle_id.startswith('/subtitles'):
        candidate_links.append(_absolute_url(subtitle_id))
    elif subtitle_id.startswith('http://') or subtitle_id.startswith('https://'):
        candidate_links.append(subtitle_id)
    elif subtitle_id.startswith('/download/'):
        # Keep absolute /download links if the live index ever contains them,
        # but do not construct mora25r links for Novalermora.
        candidate_links.append(_absolute_url(subtitle_id))
    else:
        candidate_links.append('{}/subtitles/{}'.format(MAIN_URL, subtitle_id))

    # Avoid duplicate candidate requests.
    unique_links = []
    for link in candidate_links:
        if link not in unique_links:
            unique_links.append(link)

    response = None
    last_error = None
    for download_link in unique_links:
        log(__name__, '{} Downloading from: {}'.format(DEBUG_PRETEXT, download_link))
        try:
            response = SESSION.get(download_link, headers=HEADERS, verify=False, allow_redirects=True, timeout=20)
            response.raise_for_status()
            if response.content:
                break
            last_error = 'empty response from {}'.format(download_link)
            response = None
        except requests.RequestException as e:
            last_error = e
            log(__name__, '{} Download failed from {}: {}'.format(DEBUG_PRETEXT, download_link, e))
            response = None

    if response is None:
        log(__name__, '{} Download failed: {}'.format(DEBUG_PRETEXT, last_error))
        return False, language, None

    if not os.path.exists(tmp_sub_dir):
        os.makedirs(tmp_sub_dir)

    local_tmp_file = os.path.join(tmp_sub_dir, _safe_filename_from_id(subtitle_id))
    try:
        with open(local_tmp_file, "wb") as file:
            file.write(response.content)
        log(__name__, '{} Subtitles saved to: {}'.format(DEBUG_PRETEXT, local_tmp_file))
    except Exception as e:
        log(__name__, '{} Error saving subtitle: {}'.format(DEBUG_PRETEXT, e))
        return False, language, None

    packed = False
    subs_file = local_tmp_file
    try:
        with open(local_tmp_file, "rb") as file:
            file_header = file.read(2).decode(errors="ignore")
            if file_header.startswith("R"):
                packed = True
                subs_file = "rar"
            elif file_header.startswith("PK"):
                packed = True
                subs_file = "zip"
            else:
                subs_file = local_tmp_file
    except Exception as e:
        log(__name__, '{} Error checking file type: {}'.format(DEBUG_PRETEXT, e))

    log(__name__, '{} Returning: packed={}, language={}, subs_file={}'.format(DEBUG_PRETEXT, packed, language, subs_file))
    return packed, language, subs_file
