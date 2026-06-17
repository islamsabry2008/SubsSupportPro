# -*- coding: utf-8 -*-
import os
import re
import shutil



LANGUAGE_MAP = {
    "sq": ("Albanian", "flags/sq.gif"),
    "ar": ("Arabic", "flags/ar.gif"),
    "hy": ("Belarusian", "flags/hy.gif"),
    "bs": ("Bosnian", "flags/bs.gif"),
    "bg": ("Bulgarian", "flags/bg.gif"),
    "ca": ("Catalan", "flags/ca.gif"),
    "zh": ("Chinese", "flags/zh.gif"),
    "hr": ("Croatian", "flags/hr.gif"),
    "cs": ("Czech", "flags/cs.gif"),
    "da": ("Danish", "flags/da.gif"),
    "nl": ("Dutch", "flags/nl.gif"),
    "en": ("English", "flags/en.gif"),
    "et": ("Estonian", "flags/et.gif"),
    "fa": ("Persian", "flags/fa.gif"),
    "fi": ("Finnish", "flags/fi.gif"),
    "fr": ("French", "flags/fr.gif"),
    "de": ("German", "flags/de.gif"),
    "el": ("Greek", "flags/el.gif"),
    "he": ("Hebrew", "flags/he.gif"),
    "hi": ("Hindi", "flags/hi.gif"),
    "hu": ("Hungarian", "flags/hu.gif"),
    "is": ("Icelandic", "flags/is.gif"),
    "id": ("Indonesian", "flags/id.gif"),
    "it": ("Italian", "flags/it.gif"),
    "ja": ("Japanese", "flags/ja.gif"),
    "ko": ("Korean", "flags/ko.gif"),
    "lv": ("Latvian", "flags/lv.gif"),
    "lt": ("Lithuanian", "flags/lt.gif"),
    "mk": ("Macedonian", "flags/mk.gif"),
    "ms": ("Malay", "flags/ms.gif"),
    "no": ("Norwegian", "flags/no.gif"),
    "pl": ("Polish", "flags/pl.gif"),
    "pt": ("Portuguese", "flags/pt.gif"),
    "pt-br": ("Portuguese (Brazil)", "flags/pt-br.gif"),
    "pb": ("Portuguese (Brazil)", "flags/pt-br.gif"),
    "ro": ("Romanian", "flags/ro.gif"),
    "ru": ("Russian", "flags/ru.gif"),
    "sr": ("Serbian", "flags/sr.gif"),
    "sk": ("Slovak", "flags/sk.gif"),
    "sl": ("Slovenian", "flags/sl.gif"),
    "es": ("Spanish", "flags/es.gif"),
    "sv": ("Swedish", "flags/sv.gif"),
    "th": ("Thai", "flags/th.gif"),
    "tr": ("Turkish", "flags/tr.gif"),
    "uk": ("Ukrainian", "flags/uk.gif"),
    "vi": ("Vietnamese", "flags/vi.gif"),
    "r": ("Urdu", "flags/ur.gif"),
    "ta": ("Tamil", "flags/ta.gif"),
    "te": ("Telugu", "flags/te.gif"),
    "ml": ("Malayalam", "flags/ml.gif"),
    "kn": ("Kannada", "flags/kn.gif"),
    "mr": ("Marathi", "flags/mr.gif"),
    "bn": ("Bengali", "flags/bn.gif"),
    "pa": ("Punjabi", "flags/pa.gif"),
    "es-la": ("Spanish (Latin America)", "flags/es-la.gif"),
    "es-es": ("Spanish (Spain)", "flags/es-es.gif"),
    "zh-cn": ("Chinese (Simplified)", "flags/zh-cn.gif"),
    "zh-tw": ("Chinese (Traditional)", "flags/zh-tw.gif"),
}




try:
    import six
except Exception:
    six = None


def _is_py2():
    return bool(six is not None and six.PY2)


def _to_unicode(value):
    if value is None:
        return u""
    if _is_py2():
        if isinstance(value, six.text_type):
            return value
        if isinstance(value, six.binary_type):
            try:
                return value.decode('utf-8')
            except Exception:
                return value.decode('utf-8', 'ignore')
    else:
        if isinstance(value, bytes):
            return value.decode('utf-8', 'ignore')
        if isinstance(value, str):
            return value
    try:
        return six.text_type(value) if six is not None else str(value)
    except Exception:
        return u""


def _to_fs(value):
    """Return a filesystem path type that os/open/shutil can use safely."""
    if _is_py2():
        if isinstance(value, six.text_type):
            return value.encode('utf-8')
        return value
    return _to_unicode(value)


def _to_log(value):
    value = _to_unicode(value)
    if _is_py2():
        return value.encode('utf-8')
    return value


def _safe_print(message):
    try:
        print(_to_log(message))
    except Exception:
        try:
            print(_to_log(_to_unicode(message)))
        except Exception:
            print('[LocalDriveSeeker][debug] <log message unavailable>')


def get_first_word(title):
    """Extracts the first word before a space or any special symbol."""
    title = _to_unicode(title)
    match = re.match(r'^([\w]+)', title, re.UNICODE) if _is_py2() else re.match(r'^([\w]+)', title, re.UNICODE)
    return match.group(1) if match else title


def _normalize_search_text(value):
    """Normalize titles/filenames for flexible local filename matching."""
    value = _to_unicode(value)
    value = os.path.basename(value)
    value = value.lower()
    value = re.sub(r'[^\w]+', u' ', value, flags=re.UNICODE) if _is_py2() else re.sub(r'[^\w]+', ' ', value, flags=re.UNICODE)
    return (re.sub(r'\s+', u' ', value, flags=re.UNICODE) if _is_py2() else re.sub(r'\s+', ' ', value, flags=re.UNICODE)).strip()


def _subtitle_extension(filename):
    """Return True for subtitle files handled by the existing copy workflow."""
    return _to_unicode(filename).lower().endswith(u'.srt')


def extract_language_info(filename):
    """Extracts the language code before '.srt' and converts it to display info."""
    filename = _to_unicode(filename)
    match = re.search(r'([a-zA-Z-]{2,5})\.srt$', filename, re.IGNORECASE) if _is_py2() else re.search(r'([a-zA-Z-]{2,5})\.srt$', filename, re.IGNORECASE)
    lang_code = match.group(1).lower() if match else "unknown"
    language_name, language_flag = LANGUAGE_MAP.get(lang_code, ("Unknown", "flags/unknown.gif"))
    return language_name, language_flag, lang_code


def extract_language(filename):
    """Backward-compatible helper: return only the language name."""
    return extract_language_info(filename)[0]


def _iter_search_paths(download_path):
    """Build a de-duplicated list of local roots to scan.

    Search the configured LocalDrive path first, then /tmp as an explicit
    secondary location.  /tmp is useful for manually placed or previously
    extracted subtitles; the download path has a same-file guard so selecting
    an existing /tmp result does not copy the file onto itself.

    Some Python 2 images return an empty string for unset provider settings
    instead of the provider default.  In that case, use /media/hdd/subs as
    the configured-path fallback before scanning /tmp.
    """
    paths = []
    configured = _to_unicode(download_path).strip()
    candidates = []
    if configured:
        candidates.append(configured)
    else:
        candidates.append('/media/hdd/subs')
    candidates.append('/tmp')

    for path in candidates:
        if not path:
            continue
        text_path = os.path.abspath(os.path.expanduser(_to_unicode(path)))
        fs_path = _to_fs(text_path)
        if fs_path not in paths:
            paths.append(fs_path)
    return paths

def search_subtitles(file_path, title, tvshow, year, season, episode, set_temp, rar, lang1, lang2, lang3, stack):
    global settings_provider
    DOWNLOAD_PATH = settings_provider.getSetting("LocalSearchPath")
    _safe_print('[LocalDriveSeeker][info] search - title: %s, filepath: %s, langs: %s, season: %s, episode: %s, tvshow: %s, year: %s' % (_to_unicode(title), _to_unicode(file_path), [_to_unicode(lang1), _to_unicode(lang2), _to_unicode(lang3)], _to_unicode(season), _to_unicode(episode), _to_unicode(tvshow), _to_unicode(year)))

    subtitles_list = []
    msg = ""
    seen_paths = set()

    raw_query = title or tvshow or file_path or ""
    title_key = _normalize_search_text(raw_query)
    _safe_print(title_key)

    _safe_print('[LocalDriveSeeker][info] using langs %s %s %s' % (_to_unicode(lang1), _to_unicode(lang2), _to_unicode(lang3)))

    if not title_key:
        msg = "No local search title supplied"
        _safe_print('[LocalDriveSeeker][info] search finished, found 0 subtitles in 0.00s')
        return subtitles_list, "", msg

    for path in _iter_search_paths(DOWNLOAD_PATH):
        _safe_print('[LocalDriveSeeker][debug] scanning path: %s' % _to_unicode(path))
        if not os.path.exists(path):
            _safe_print('[LocalDriveSeeker][debug] search path not found: %s' % _to_unicode(path))
            continue
        for root, _, files in os.walk(path):
            for filename in files:
                if not _subtitle_extension(filename):
                    continue
                display_filename = _to_unicode(filename)
                normalized_filename = _normalize_search_text(display_filename)
                if title_key not in normalized_filename:
                    continue
                full_path = os.path.join(root, filename)
                full_path_text = _to_unicode(full_path)
                if full_path_text in seen_paths:
                    continue
                seen_paths.add(full_path_text)
                _safe_print('[LocalDriveSeeker][debug] Found matching title: %s' % display_filename)
                language_name, language_flag, lang_code = extract_language_info(display_filename)
                subtitles_list.append({
                    "filename": display_filename,
                    "path": full_path_text,
                    "language_name": language_name,
                    "language_flag": language_flag,
                    "sync": True
                })

    _safe_print('[LocalDriveSeeker][info] search finished, found %d subtitles in 0.00s' % len(subtitles_list))
    return subtitles_list, "", msg


def remove_language_code(filename):
    """Removes repeated or single language codes before '.srt'."""
    filename = _to_unicode(filename)
    return re.sub(r'([._-][a-zA-Z]{2,5})+\.srt$', u'.srt', filename) if _is_py2() else re.sub(r'([._-][a-zA-Z]{2,5})+\.srt$', '.srt', filename)


def download_subtitles(subtitles_list, pos, zip_subs, tmp_sub_dir, sub_folder, session_id):
    """
    Copies the selected subtitle from its original location to the temporary folder,
    and removes any trailing language/source code from the filename.
    """
    if pos < 0 or pos >= len(subtitles_list):
        _safe_print('[LocalDriveSeeker][error] Invalid subtitle selection index: %s' % pos)
        return False, "Unknown", None

    subtitle_info = subtitles_list[pos]
    subtitle_path = subtitle_info.get("path")
    subtitle_filename = subtitle_info.get("filename")
    _safe_print(subtitle_filename)
    language = subtitle_info.get("language_name", "Unknown")

    subtitle_path_fs = _to_fs(subtitle_path)
    if not subtitle_path or not os.path.exists(subtitle_path_fs):
        _safe_print('[LocalDriveSeeker][error] Subtitle file not found: %s' % _to_unicode(subtitle_path))
        return False, language, None

    tmp_sub_dir_fs = _to_fs(tmp_sub_dir)
    if not os.path.exists(tmp_sub_dir_fs):
        os.makedirs(tmp_sub_dir_fs)

    new_filename = remove_language_code(subtitle_filename)
    _safe_print(new_filename)
    copied_path = os.path.join(_to_unicode(tmp_sub_dir), new_filename)
    copied_path_fs = _to_fs(copied_path)

    try:
        try:
            same_file = os.path.abspath(subtitle_path_fs) == os.path.abspath(copied_path_fs)
        except Exception:
            same_file = False
        if same_file:
            _safe_print('[LocalDriveSeeker][info] Subtitle already in temp folder: %s' % _to_unicode(copied_path))
        else:
            shutil.copy(subtitle_path_fs, copied_path_fs)
            _safe_print('[LocalDriveSeeker][info] Subtitle copied to: %s' % _to_unicode(copied_path))
    except Exception as e:
        _safe_print('[LocalDriveSeeker][error] Error copying subtitle: %s' % _to_unicode(e))
        return False, language, None

    packed = False
    return packed, language, copied_path
