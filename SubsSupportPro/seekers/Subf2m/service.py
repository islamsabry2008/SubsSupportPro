# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function

import os
import re
import zipfile
try:
    import html
except ImportError:
    html = None
import time
import random
import string
import warnings
# Python 2 receiver images may ship BeautifulSoup without soupsieve.
# Subf2m uses only old BeautifulSoup-safe find/find_all calls, so the warning is harmless.
warnings.filterwarnings('ignore', message='.*soupsieve package is not installed.*', category=UserWarning)
from bs4 import BeautifulSoup
from six.moves import html_parser
from six.moves.urllib.parse import quote_plus, urlencode, urljoin
import urllib3
from urllib3.exceptions import InsecureRequestWarning
import requests

from ..seeker import SubtitlesDownloadError, SubtitlesErrors
from ..utilities import log
from ..user_agents import get_random_ua
from .Subf2mUtilities import get_language_info

# Suppress insecure request warnings
urllib3.disable_warnings(InsecureRequestWarning)

HDR = {
    'User-Agent': get_random_ua(),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9,ar-EG;q=0.8,ar;q=0.7',
    'Upgrade-Insecure-Requests': '1',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Referer': 'https://subf2m.co',
    'Connection': 'keep-alive',
    'Accept-Encoding': 'gzip, deflate'
}

main_url = "https://subf2m.co"
debug_pretext = ""
REQUEST_TIMEOUT = 8


def _safe_get(url, **kwargs):
    """requests.get wrapper with timeout so Python 2 receivers do not hang at 0%."""
    if "timeout" not in kwargs:
        kwargs["timeout"] = (5, REQUEST_TIMEOUT)
    try:
        log(__name__, "HTTP GET start: {}".format(url))
        response = requests.get(url, **kwargs)
        log(__name__, "HTTP GET done: {} status={}".format(url, getattr(response, 'status_code', 'unknown')))
        return response
    except Exception as error:
        log(__name__, "HTTP GET failed: {} error={}".format(url, error))
        return None

seasons = [
    "Specials", "First", "Second", "Third", "Fourth", "Fifth", "Sixth", 
    "Seventh", "Eighth", "Ninth", "Tenth", "Eleventh", "Twelfth", 
    "Thirteenth", "Fourteenth", "Fifteenth", "Sixteenth", "Seventeenth",
    "Eighteenth", "Nineteenth", "Twentieth", "Twenty-first", "Twenty-second", 
    "Twenty-third", "Twenty-fourth", "Twenty-fifth", "Twenty-sixth",
    "Twenty-seventh", "Twenty-eighth", "Twenty-ninth"
]

movie_season_pattern = (
    "<a href=\"(?P<link>/subscene/[^\"]*)\">(?P<title>[^<]+)\((?P<year>\d{4})\)</a>\s+"
    "<div class=\"subtle count\">\s*(?P<numsubtitles>\d+\s+subtitles)</div>\s+"
)

# Language mappings
subf2m_languages = {
    'Chinese BG code': 'Chinese',
    'Brazillian Portuguese': 'Portuguese (Brazil)',
    'Serbian': 'SerbianLatin',
    'Ukranian': 'Ukrainian',
    'Farsi/Persian': 'Persian'
}


def getSearchTitle(title, year=None):
    """Search for title and return appropriate URL"""
    url = 'https://subf2m.co/subtitles/searchbytitle?query={}&l='.format(quote_plus(title))
    response = _safe_get(url, headers=HDR, verify=False, allow_redirects=True)
    if response is None:
        return url
    data = response.content.decode('utf-8', 'ignore')
    soup = BeautifulSoup(data, 'html.parser')
    
    search_results = soup.find('div', class_='search-result')
    if not search_results:
        return url
    
    result_items = search_results.find_all('li')
    
    for item in result_items:
        title_div = item.find('div', class_='title')
        if not title_div:
            continue
            
        a_tag = title_div.find('a')
        if not a_tag:
            continue
            
        link = a_tag.get('href')
        full_title = a_tag.get_text(strip=True)
        
        year_match = re.search(r'\((\d{4})\)', full_title)
        found_year = year_match.group(1) if year_match else None
        
        if year and found_year == str(year):
            return 'https://subf2m.co{}'.format(link)
        elif not year:
            return 'https://subf2m.co{}'.format(link)
    
    return url


def find_movie(content, title, year):
    """Find movie in search results"""
    soup = BeautifulSoup(content, 'html.parser')
    search_results = soup.find('div', class_='search-result')
    
    if not search_results:
        return None
    
    result_items = search_results.find_all('li')
    
    for item in result_items:
        title_div = item.find('div', class_='title')
        if not title_div:
            continue
            
        a_tag = title_div.find('a')
        if not a_tag:
            continue
            
        link = a_tag.get('href')
        full_title = a_tag.get_text(strip=True)
        
        year_match = re.search(r'\((\d{4})\)', full_title)
        found_year = year_match.group(1) if year_match else None
        
        if (title.lower() in full_title.lower() and 
            found_year == str(year)):
            return link
    
    return None


def find_tv_show_season(content, tvshow, season):
    """Find TV show season in search results"""
    soup = BeautifulSoup(content, 'html.parser')
    search_results = soup.find('div', class_='search-result')
    
    if not search_results:
        return None
    
    result_items = search_results.find_all('li')
    season_num = int(season)
    season_text = seasons[season_num] if season_num < len(seasons) else 'Season {}'.format(season)
    
    for item in result_items:
        title_div = item.find('div', class_='title')
        if not title_div:
            continue
            
        a_tag = title_div.find('a')
        if not a_tag:
            continue
            
        link = a_tag.get('href')
        full_title = a_tag.get_text(strip=True)
        
        tvshow_lower = tvshow.lower()
        title_lower = full_title.lower()
        
        season_patterns = [
            'season {}'.format(season),
            '{} season'.format(season_text.lower()),
            '- season {}'.format(season),
            '- {} season'.format(season_text.lower()),
        ]
        
        if (tvshow_lower in title_lower and 
            any(pattern in title_lower for pattern in season_patterns)):
            return link
    
    return None


def getallsubs(content, allowed_languages, filename="", search_string=""):
    """Extract all subtitles from page content"""
    soup = BeautifulSoup(content.text, 'html.parser')
    
    subtitles_list = (soup.find('ul', class_='sublist') or 
                     soup.find('ul', class_='larglist'))
    
    if subtitles_list is None:
        log(__name__, "No subtitles list found on the page.")
        return []
    
    items = subtitles_list.find_all('li', class_='item')
    subtitles = []
    
    for item in items:
        try:
            # Get language
            lang_span = item.find('span', class_='language')
            if not lang_span:
                continue
                
            lang_text = lang_span.text.strip()
            language_info = get_language_info(lang_text)
            
            if not language_info and lang_text in subf2m_languages:
                language_info = get_language_info(subf2m_languages[lang_text])
            
            if not language_info or language_info['name'] not in allowed_languages:
                continue
            
            # Get download link
            download_link = item.find('a', class_='download')
            if not download_link or not download_link.get('href'):
                continue
                
            link = '{}{}'.format(main_url, download_link['href'])
            
            # Get subtitle filename
            subtitle_name = ""
            scrolllist = item.find('ul', class_='scrolllist')
            if scrolllist:
                first_li = scrolllist.find('li')
                if first_li:
                    subtitle_name = first_li.text.strip()
            
            # Get rating
            rating_span = item.find('span', class_='rate')
            rating = 'not rated'
            
            if rating_span:
                rating_classes = rating_span.get('class', [])
                if 'good' in rating_classes:
                    rating = 'good'
                elif 'bad' in rating_classes:
                    rating = 'bad'
                elif 'neutral' in rating_classes:
                    rating = 'neutral'
            
            # Check sync
            sync = False
            if filename and subtitle_name:
                if (filename.lower() in subtitle_name.lower() or 
                    subtitle_name.lower() in filename.lower()):
                    sync = True
            
            if search_string:
                if search_string.lower() in subtitle_name.lower():
                    subtitles.append({
                        'filename': subtitle_name, 
                        'sync': sync, 
                        'link': link,
                        'language_name': language_info['name'], 
                        'lang': language_info,
                        'rating': rating
                    })
            else:
                subtitles.append({
                    'filename': subtitle_name, 
                    'sync': sync, 
                    'link': link,
                    'language_name': language_info['name'], 
                    'lang': language_info,
                    'rating': rating
                })
                
        except Exception as e:
            log(__name__, 'Error parsing subtitle item: {}'.format(str(e)))
            continue
    
    # Sort by sync status and rating
    rating_order = {'good': 0, 'neutral': 1, 'bad': 2, 'not rated': 3}
    subtitles.sort(key=lambda x: (not x['sync'], rating_order.get(x['rating'], 4)))
    
    return subtitles


def prepare_search_string(s):
    """Prepare search string for URL encoding"""
    s = s.replace("'", "").strip()
    s = re.sub(r'\(\d\d\d\d\)$', '', s)
    return quote_plus(s)


def search_movie(title, year, languages, filename):
    """Search for movie subtitles"""
    try:
        title = title.replace("MISSION IMPOSSIBLE : ROGUE NATION", 
                             "Mission: Impossible - Rogue Nation").strip()
        log(__name__, 'Searching movie: {}'.format(title))
        
        url = getSearchTitle(title, year)
        log(__name__, 'Movie search URL: {}'.format(url))
        
        response = _safe_get(url, headers=HDR, verify=False, allow_redirects=True)
        if response is None:
            return []
        if response.status_code == 200:
            return getallsubs(response, languages, filename)
        else:
            return []
    except Exception as error:
        log(__name__, 'Error searching movie: {}'.format(error))
        return []


def search_tvshow(tvshow, season, episode, languages, filename):
    """Search for TV show subtitles"""
    tvshow = tvshow.strip()
    log(__name__, 'Searching TV show: {}'.format(tvshow))
    
    search_string = prepare_search_string(tvshow).replace("+", " ")
    url = '{}/subtitles/searchbytitle?query={}'.format(main_url, quote_plus(search_string))
    
    log(__name__, 'TV show search URL: {}'.format(url))
    response = _safe_get(url, headers=HDR, verify=False, allow_redirects=True)
    if response is None:
        return []
    content = response.text
    
    if content:
        log(__name__, "Multiple TV show seasons found, searching for the right one...")
        tv_show_seasonurl = find_tv_show_season(content, tvshow, season)
        
        if tv_show_seasonurl:
            log(__name__, "TV show season found, getting subtitles...")
            url = '{}{}'.format(main_url, tv_show_seasonurl)
            
            season_response = _safe_get(url, headers=HDR, verify=False, allow_redirects=True)
            if season_response is not None and season_response.status_code == 200:
                search_string = 's{:02d}e{:02d}'.format(int(season), int(episode))
                return getallsubs(season_response, languages, filename, search_string)
    
    return []


def search_manual(searchstr, languages, filename):
    """Manual search for subtitles"""
    search_string = prepare_search_string(searchstr)
    url = '{}/subtitles/release?q={}&r=true'.format(main_url, search_string)
    
    response = _safe_get(url, headers=HDR, verify=False, allow_redirects=True)
    if response is None:
        return []
    content = response.text
    
    if content:
        return getallsubs(response, languages, filename)
    return []


def search_subtitles(file_original_path, title, tvshow, year, season, episode, 
                    set_temp, rar, lang1, lang2, lang3, stack):
    """Main search function - standard input"""
    log(__name__, 
        "{} Search_subtitles = '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}'".format(debug_pretext, file_original_path, title, tvshow, year, season, episode, set_temp, rar, lang1, lang2, lang3, stack))
    
    # Handle Farsi language mapping
    for i, lang in enumerate([lang1, lang2, lang3]):
        if lang == 'Farsi':
            if i == 0: lang1 = 'Persian'
            elif i == 1: lang2 = 'Persian'
            elif i == 2: lang3 = 'Persian'
    
    languages = [lang1, lang2, lang3]
    
    try:
        if tvshow:
            sublist = search_tvshow(tvshow, season, episode, languages, file_original_path)
        elif title:
            sublist = search_movie(title, year, languages, file_original_path)
        else:
            sublist = search_manual(title, languages, file_original_path)
    except Exception as e:
        log(__name__, 'Search error: {}'.format(e))
        sublist = []
    
    return sublist, "", ""


def download_subtitles(subtitles_list, pos, zip_subs, tmp_sub_dir, sub_folder, session_id):
    """Download selected subtitles"""
    url = subtitles_list[pos]["link"]
    language = subtitles_list[pos]["language_name"]
    
    log(__name__, 'Downloading from: {}'.format(url))
    response = _safe_get(url, headers=HDR, verify=False, allow_redirects=True)
    if response is None:
        raise SubtitlesDownloadError(SubtitlesErrors.UNKNOWN_ERROR,
                                     'Subf2m subtitle page request failed: %s' % url)
    try:
        response.raise_for_status()
    except Exception as e:
        raise SubtitlesDownloadError(SubtitlesErrors.UNKNOWN_ERROR,
                                     'Subf2m subtitle page failed from %s: %s' % (url, e))
    content_text = response.text

    soup = BeautifulSoup(content_text, 'html.parser')
    download_button = soup.find('a', id='downloadButton')
    
    if download_button and download_button.get('href'):
        href = download_button.get('href')
        downloadlink = urljoin(main_url, href)
        log(__name__, 'Download link: {}'.format(downloadlink))

        download_headers = HDR.copy()
        download_headers['Referer'] = url
        # Some CDN downloads fail on old Python 2 images when gzip/deflate handling is broken.
        # Let requests choose safe defaults for the actual binary download.
        if 'Accept-Encoding' in download_headers:
            del download_headers['Accept-Encoding']

        sub_response = _safe_get(downloadlink, headers=download_headers, verify=False, allow_redirects=True)
        if sub_response is None:
            raise SubtitlesDownloadError(SubtitlesErrors.UNKNOWN_ERROR,
                                         'Subf2m download request failed: %s' % downloadlink)
        try:
            sub_response.raise_for_status()
        except Exception as e:
            raise SubtitlesDownloadError(SubtitlesErrors.UNKNOWN_ERROR,
                                         'Subf2m download failed from %s: %s' % (downloadlink, e))
        if not getattr(sub_response, 'content', None):
            raise SubtitlesDownloadError(SubtitlesErrors.UNKNOWN_ERROR,
                                         'Subf2m download returned empty content: %s' % downloadlink)

        # Sanitize filename
        sanitized_filename = re.sub(r'[\\/]', '_', zip_subs)
        local_tmp_file = os.path.join(tmp_sub_dir, sanitized_filename)

        try:
            log(__name__, "{} Saving subtitles to '{}'".format(debug_pretext, local_tmp_file))
            if not os.path.exists(tmp_sub_dir):
                os.makedirs(tmp_sub_dir)
            
            with open(local_tmp_file, 'wb') as f:
                f.write(sub_response.content)

            # Check file type
            packed = False
            subs_file = local_tmp_file

            with open(local_tmp_file, "rb") as f:
                header = f.read(4)
                if header == b'PK\x03\x04':  # ZIP file
                    packed = True
                    log(__name__, "Discovered ZIP Archive")
                else:
                    log(__name__, "Discovered a non-archive file")

            if packed:
                try:
                    with zipfile.ZipFile(local_tmp_file, 'r') as zip_ref:
                        zip_ref.extractall(tmp_sub_dir)
                        extracted_files = zip_ref.namelist()
                        if extracted_files:
                            subs_file = os.path.join(tmp_sub_dir, extracted_files[0])
                            log(__name__, '{} Extracted subtitle file: {}'.format(debug_pretext, subs_file))
                except Exception as e:
                    log(__name__, '{} Failed to extract ZIP file: {}'.format(debug_pretext, e))
                    raise SubtitlesDownloadError(SubtitlesErrors.UNKNOWN_ERROR, str(e))

            log(__name__, "{} Subtitles saved to '{}'".format(debug_pretext, local_tmp_file))
            return packed, language, subs_file
            
        except Exception as e:
            log(__name__, '{} Failed to save subtitle: {}'.format(debug_pretext, e))
            raise SubtitlesDownloadError(SubtitlesErrors.UNKNOWN_ERROR, str(e))
    else:
        log(__name__, '{} No download link found'.format(debug_pretext))
        raise SubtitlesDownloadError(SubtitlesErrors.UNKNOWN_ERROR, "No download link found")