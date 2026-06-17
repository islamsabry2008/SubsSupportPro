#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SubsSupportPro Translation Auto Builder
======================================

Purpose
-------
Build and maintain gettext translations for the Enigma2 plugin:
    /usr/lib/enigma2/python/Plugins/Extensions/SubsSupportPro

What it does
------------
1. Forces the gettext domain to: SubsSupportPro
2. Extracts translatable strings from Python and XML files.
3. Generates locale/SubsSupportPro.pot.
4. Migrates old translations from the original SubsSupport domain:
       locale/<lang>/LC_MESSAGES/<lang>.po
       locale/<lang>/LC_MESSAGES/SubsSupport.po
       locale/<lang>/LC_MESSAGES/SubsSupportPro.po
5. Creates/updates:
       locale/<lang>/LC_MESSAGES/SubsSupportPro.po
6. Optionally auto-translates missing msgstr values with Google Translate.
7. Compiles .po to .mo using a built-in pure-Python compiler.

Run from plugin directory:
    python3 update_translations_subssupportpro.py

Common examples:
    python3 update_translations_subssupportpro.py --no-auto-translate
    python3 update_translations_subssupportpro.py --languages ar,de,fr,it --auto-translate
    python3 update_translations_subssupportpro.py --plugin-dir /usr/lib/enigma2/python/Plugins/Extensions/SubsSupportPro

Notes
-----
- Existing translations are preserved.
- Empty translations only are auto-translated.
- Placeholder safety is checked before saving machine translations.
- Old SubsSupport files are not deleted unless --clean-old is used.
"""

from __future__ import print_function

import argparse
import ast
import codecs
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import sys
import time
import tokenize
from collections import OrderedDict, defaultdict
from io import BytesIO
from json import loads
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree as ET

DOMAIN = "SubsSupportPro"
OLD_DOMAIN = "SubsSupport"
PLUGIN_FOLDER_NAME = "SubsSupportPro"
SOURCE_LANGUAGE = "en"

TRANSLATE_API_URL = "https://translate.googleapis.com/translate_a/single"
REQUEST_TIMEOUT = 8
MAX_CHARS_PER_REQUEST = 2000
REQUEST_DELAY = 0.15

PYTHON_KEYWORDS = {
    "_": 0,
    "gettext": 0,
    "ugettext": 0,
    "dgettext": 1,
    "pgettext": 1,
    "ngettext": (0, 1),
}

XML_TRANSLATABLE_ATTRS = {
    "text", "title", "description", "help", "caption", "label", "tooltip", "message"
}

SKIP_DIRS = {
    ".git", "__pycache__", "locale", "fonts", "img", "images", "pics", "tmp", "cache"
}

SKIP_PY_FILES = {
    "update_translations.py",
    "update_translations_subssupportpro.py",
    "translate_utils.py",
}

DEFAULT_LANGUAGES = [
    "ar", "bg", "cs", "de", "el", "es", "et", "fr", "hr", "hu", "it",
    "lt", "pl", "pt", "ru", "sk", "uk"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.8",
    "Connection": "close",
}

PLACEHOLDER_RE = re.compile(
    r"("
    r"%\([^)]+\)[#0\- +]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[diouxXeEfFgGcrs]"
    r"|%(?:\d+\$)?[#0\- +]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[diouxXeEfFgGcrs]"
    r"|\{\{"
    r"|\}\}"
    r"|\{[^{}]*\}"
    r"|\\n|\\r|\\t"
    r")"
)

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6,8}$")
NUMERIC_SYMBOL_RE = re.compile(r"^[0-9\s\W_]+$", re.UNICODE)
PATHISH_RE = re.compile(r"^(/|\./|\.\./|[A-Za-z]:\\|https?://|ftp://)")


def nowstamp():
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def log(msg):
    print(msg)


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def read_text(path):
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            pass
    return data.decode("utf-8", "ignore")


def write_text(path, text):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def po_escape(s):
    if s is None:
        s = ""
    return (s.replace("\\", "\\\\")
             .replace("\t", "\\t")
             .replace("\r", "\\r")
             .replace("\n", "\\n")
             .replace('"', '\\"'))


def po_unescape(quoted):
    quoted = quoted.strip()
    if not quoted.startswith('"'):
        return ""
    try:
        return ast.literal_eval(quoted)
    except Exception:
        try:
            return codecs.decode(quoted[1:-1], "unicode_escape")
        except Exception:
            return quoted[1:-1]


def wrap_po_string(label, value):
    value = value or ""
    escaped = po_escape(value)
    if "\\n" in escaped or len(escaped) > 120:
        parts = escaped.split("\\n")
        out = [label + ' ""']
        for idx, part in enumerate(parts):
            suffix = "\\n" if idx < len(parts) - 1 else ""
            out.append('"{}{}"'.format(part, suffix))
        return "\n".join(out)
    return '{} "{}"'.format(label, escaped)


class POEntry(object):
    __slots__ = ("msgid", "msgstr", "comments", "references", "flags", "obsolete")

    def __init__(self, msgid="", msgstr="", comments=None, references=None, flags=None, obsolete=False):
        self.msgid = msgid or ""
        self.msgstr = msgstr or ""
        self.comments = comments or []
        self.references = references or []
        self.flags = flags or []
        self.obsolete = obsolete


def parse_po_file(path):
    """Minimal robust PO parser for simple msgid/msgstr catalogs."""
    if not os.path.isfile(path):
        return OrderedDict(), None

    lines = read_text(path).splitlines()
    entries = OrderedDict()
    header = None

    comments = []
    references = []
    flags = []
    msgid = None
    msgstr = None
    active = None
    obsolete = False

    def commit():
        nonlocal comments, references, flags, msgid, msgstr, active, obsolete, header
        if msgid is not None:
            entry = POEntry(msgid, msgstr or "", list(comments), list(references), list(flags), obsolete)
            if msgid == "":
                header = entry
            else:
                entries[msgid] = entry
        comments = []
        references = []
        flags = []
        msgid = None
        msgstr = None
        active = None
        obsolete = False

    for raw in lines + [""]:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            commit()
            continue

        if stripped.startswith("#~"):
            obsolete = True
            stripped = stripped[2:].strip()

        if stripped.startswith("#:"):
            references.extend(stripped[2:].strip().split())
            continue
        if stripped.startswith("#,"):
            flags.extend([x.strip() for x in stripped[2:].split(",") if x.strip()])
            continue
        if stripped.startswith("#"):
            comments.append(stripped)
            continue

        if stripped.startswith("msgid "):
            if msgid is not None and msgstr is not None:
                commit()
            msgid = po_unescape(stripped[6:].strip())
            active = "msgid"
            continue

        if stripped.startswith("msgstr "):
            msgstr = po_unescape(stripped[7:].strip())
            active = "msgstr"
            continue

        # Ignore plural forms but keep first msgstr[0] if available.
        if stripped.startswith("msgstr["):
            if msgstr is None:
                msgstr = po_unescape(stripped.split(None, 1)[1]) if " " in stripped else ""
                active = "msgstr"
            else:
                active = None
            continue

        if stripped.startswith('"'):
            value = po_unescape(stripped)
            if active == "msgid" and msgid is not None:
                msgid += value
            elif active == "msgstr" and msgstr is not None:
                msgstr += value
            continue

    return entries, header


def create_header_entry(language=""):
    header_lines = [
        "Project-Id-Version: {}\n".format(DOMAIN),
        "Report-Msgid-Bugs-To: \n",
        "POT-Creation-Date: {}\n".format(_dt.datetime.now().strftime("%Y-%m-%d %H:%M%z")),
        "PO-Revision-Date: \n",
        "Last-Translator: \n",
        "Language-Team: {}\n".format(language or ""),
        "Language: {}\n".format(language or ""),
        "MIME-Version: 1.0\n",
        "Content-Type: text/plain; charset=UTF-8\n",
        "Content-Transfer-Encoding: 8bit\n",
        "X-Generator: SubsSupportPro auto builder\n",
    ]
    return POEntry("", "".join(header_lines))


def write_pot_file(path, catalog):
    lines = []
    lines.append("# {} translation template".format(DOMAIN))
    lines.append("# Generated by update_translations_subssupportpro.py")
    lines.append("#")
    header = create_header_entry("")
    lines.append('msgid ""')
    lines.append('msgstr ""')
    for hline in header.msgstr.splitlines(True):
        lines.append('"{}"'.format(po_escape(hline)))
    lines.append("")

    for msgid in sorted(catalog.keys(), key=lambda x: x.lower()):
        entry = catalog[msgid]
        if entry.references:
            refs = sorted(set(entry.references))
            chunk = []
            current = "#:"
            for ref in refs:
                if len(current) + len(ref) + 1 > 120:
                    lines.append(current)
                    current = "#: " + ref
                else:
                    current += " " + ref
            if current != "#:":
                lines.append(current)
        lines.append(wrap_po_string("msgid", msgid))
        lines.append('msgstr ""')
        lines.append("")
    write_text(path, "\n".join(lines))


def write_po_file(path, language, catalog, translations):
    lines = []
    lines.append("# {} translations for {}".format(language, DOMAIN))
    lines.append("# Generated by update_translations_subssupportpro.py")
    lines.append("# Existing human translations are preserved when available.")
    lines.append("#")
    header = create_header_entry(language)
    lines.append('msgid ""')
    lines.append('msgstr ""')
    for hline in header.msgstr.splitlines(True):
        lines.append('"{}"'.format(po_escape(hline)))
    lines.append("")

    for msgid in sorted(catalog.keys(), key=lambda x: x.lower()):
        entry = catalog[msgid]
        if entry.references:
            refs = sorted(set(entry.references))
            current = "#:"
            for ref in refs:
                if len(current) + len(ref) + 1 > 120:
                    lines.append(current)
                    current = "#: " + ref
                else:
                    current += " " + ref
            if current != "#:":
                lines.append(current)
        msgstr = translations.get(msgid, "") or ""
        lines.append(wrap_po_string("msgid", msgid))
        lines.append(wrap_po_string("msgstr", msgstr))
        lines.append("")
    write_text(path, "\n".join(lines))


def compile_mo(po_path, mo_path):
    entries, header = parse_po_file(po_path)
    catalog = {}
    catalog[""] = header.msgstr if header else create_header_entry("").msgstr
    for msgid, entry in entries.items():
        catalog[msgid] = entry.msgstr or ""

    keys = sorted(catalog.keys())
    ids = []
    strs = []
    for k in keys:
        ids.append(k.encode("utf-8"))
        strs.append(catalog[k].encode("utf-8"))

    n = len(keys)
    keystart = 7 * 4 + n * 8 * 2
    valuestart = keystart + sum(len(x) + 1 for x in ids)

    koffsets = []
    offset = keystart
    for item in ids:
        koffsets.append((len(item), offset))
        offset += len(item) + 1

    voffsets = []
    offset = valuestart
    for item in strs:
        voffsets.append((len(item), offset))
        offset += len(item) + 1

    output = []
    output.append(struct.pack("Iiiiiii", 0x950412de, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0))
    for length, off in koffsets:
        output.append(struct.pack("ii", length, off))
    for length, off in voffsets:
        output.append(struct.pack("ii", length, off))
    output.append(b"\0".join(ids) + b"\0")
    output.append(b"\0".join(strs) + b"\0")

    ensure_dir(os.path.dirname(mo_path))
    with open(mo_path, "wb") as f:
        f.write(b"".join(output))


def is_translatable_text(s):
    if s is None:
        return False
    s = s.strip()
    if not s:
        return False
    if len(s) == 1 and not s.isalpha():
        return False
    if COLOR_RE.match(s):
        return False
    if NUMERIC_SYMBOL_RE.match(s):
        return False
    if PATHISH_RE.match(s):
        return False
    if s.startswith(("config.", "self.", "http", "ftp")):
        return False
    if "{}" == s or re.match(r"^\{\d+\}$", s):
        return False
    if not any(ch.isalpha() for ch in s):
        return False
    return True


def add_entry(catalog, msgid, reference):
    msgid = msgid.strip()
    if not is_translatable_text(msgid):
        return
    if msgid not in catalog:
        catalog[msgid] = POEntry(msgid=msgid, msgstr="", references=[])
    if reference and reference not in catalog[msgid].references:
        catalog[msgid].references.append(reference)


def iter_source_files(plugin_dir, suffixes):
    for root, dirs, files in os.walk(plugin_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if not any(name.endswith(suf) for suf in suffixes):
                continue
            if name in SKIP_PY_FILES:
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, plugin_dir).replace(os.sep, "/")
            yield path, rel


def parse_string_token(token_text):
    try:
        return ast.literal_eval(token_text)
    except Exception:
        # Python 2 unicode prefixes are usually still accepted; this is a fallback.
        try:
            cleaned = re.sub(r"^[uUrRbB]+", "", token_text)
            return ast.literal_eval(cleaned)
        except Exception:
            return None


def collect_consecutive_strings(tokens, start_index):
    values = []
    i = start_index
    last_line = None
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == tokenize.STRING:
            value = parse_string_token(tok.string)
            if isinstance(value, bytes):
                value = value.decode("utf-8", "ignore")
            if isinstance(value, str):
                values.append(value)
                last_line = tok.start[0]
                i += 1
                continue
        break
    if not values:
        return None, start_index, None
    return "".join(values), i, last_line


def extract_python_file(path, rel, catalog):
    try:
        data = read_text(path).encode("utf-8")
        tokens = list(tokenize.tokenize(BytesIO(data).readline))
    except Exception as e:
        log("  ! Tokenize failed {}: {}".format(rel, e))
        return

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == tokenize.NAME and tok.string in PYTHON_KEYWORDS:
            keyword = tok.string
            j = i + 1
            while j < len(tokens) and tokens[j].type in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
                j += 1
            if j >= len(tokens) or tokens[j].string != "(":
                i += 1
                continue

            wanted = PYTHON_KEYWORDS[keyword]
            string_args = []
            k = j + 1
            paren_depth = 1
            current_arg = 0
            while k < len(tokens) and paren_depth > 0:
                t = tokens[k]
                if t.string == "(":
                    paren_depth += 1
                elif t.string == ")":
                    paren_depth -= 1
                    if paren_depth == 0:
                        break
                elif t.string == "," and paren_depth == 1:
                    current_arg += 1
                elif paren_depth == 1 and t.type == tokenize.STRING:
                    value, new_k, line_no = collect_consecutive_strings(tokens, k)
                    if value is not None:
                        string_args.append((current_arg, value, line_no or t.start[0]))
                        k = new_k - 1
                k += 1

            if isinstance(wanted, tuple):
                wanted_args = set(wanted)
            else:
                wanted_args = {wanted}
            for arg_index, value, line_no in string_args:
                if arg_index in wanted_args:
                    add_entry(catalog, value, "{}:{}".format(rel, line_no))
            i = k
        i += 1


def extract_xml_file(path, rel, catalog):
    try:
        parser = ET.XMLParser()
        root = ET.parse(path, parser=parser).getroot()
    except Exception as e:
        # Some Enigma2 skin XML files may contain non-standard entities.
        log("  ! XML parse skipped {}: {}".format(rel, e))
        return
    for elem in root.iter():
        for attr, value in elem.attrib.items():
            if attr.lower() in XML_TRANSLATABLE_ATTRS:
                add_entry(catalog, value, rel)


def extract_catalog(plugin_dir):
    catalog = OrderedDict()
    for path, rel in iter_source_files(plugin_dir, (".py",)):
        extract_python_file(path, rel, catalog)
    for path, rel in iter_source_files(plugin_dir, (".xml",)):
        extract_xml_file(path, rel, catalog)
    return catalog


def discover_existing_languages(locale_dir):
    langs = set()
    if not os.path.isdir(locale_dir):
        return []
    for name in os.listdir(locale_dir):
        path = os.path.join(locale_dir, name)
        if os.path.isdir(path) and os.path.isdir(os.path.join(path, "LC_MESSAGES")):
            langs.add(name)
    return sorted(langs)


def load_language_translations(locale_dir, lang, domain=DOMAIN, old_domain=OLD_DOMAIN):
    """Load translations with priority: new domain > old domain > lang.po > other .po."""
    lc = os.path.join(locale_dir, lang, "LC_MESSAGES")
    candidates = [
        os.path.join(lc, "{}.po".format(domain)),
        os.path.join(lc, "{}.po".format(old_domain)),
        os.path.join(lc, "{}.po".format(lang)),
    ]
    if os.path.isdir(lc):
        for name in sorted(os.listdir(lc)):
            if name.endswith(".po"):
                p = os.path.join(lc, name)
                if p not in candidates:
                    candidates.append(p)

    translations = {}
    source_files = []
    # Lower priority first, then override with higher priority.
    for path in reversed(candidates):
        if not os.path.isfile(path):
            continue
        entries, _header = parse_po_file(path)
        for msgid, entry in entries.items():
            if entry.msgstr and entry.msgstr.strip():
                translations[msgid] = entry.msgstr
        source_files.append(path)
    return translations, list(reversed(source_files))


def get_placeholders(text):
    return PLACEHOLDER_RE.findall(text or "")


def protect_placeholders(text):
    placeholders = []

    def repl(match):
        placeholders.append(match.group(0))
        return " ZZZPH{}ZZZ ".format(len(placeholders) - 1)

    protected = PLACEHOLDER_RE.sub(repl, text)
    return protected, placeholders


def restore_placeholders(text, placeholders):
    restored = text
    for idx, ph in enumerate(placeholders):
        restored = restored.replace("ZZZPH{}ZZZ".format(idx), ph)
        restored = restored.replace("ZZZPH {} ZZZ".format(idx), ph)
        restored = restored.replace("ZZZ PH{} ZZZ".format(idx), ph)
    return re.sub(r"\s+", " ", restored).strip()


def placeholder_safe(original, translated):
    # Preserve exact placeholder multiset. Translation may reorder, but count must match.
    return sorted(get_placeholders(original)) == sorted(get_placeholders(translated))


def google_lang(lang):
    lang = (lang or "").strip()
    if not lang:
        return "en"
    if lang.lower().startswith("zh_cn"):
        return "zh-CN"
    if lang.lower().startswith("zh_tw"):
        return "zh-TW"
    return lang.split("_")[0].lower()


def cache_key(text, target):
    return hashlib.md5((target + ":" + text).encode("utf-8")).hexdigest()


def load_cache(path):
    if os.path.isfile(path):
        try:
            return json.loads(read_text(path))
        except Exception:
            return {}
    return {}


def save_cache(path, cache):
    ensure_dir(os.path.dirname(path))
    write_text(path, json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True))


def translate_text(text, lang, cache, cache_path):
    if not text:
        return ""
    target = google_lang(lang)
    if target == SOURCE_LANGUAGE:
        return text

    protected, placeholders = protect_placeholders(text)
    key = cache_key(protected, target)
    if key in cache:
        cached = restore_placeholders(cache[key], placeholders)
        return cached if placeholder_safe(text, cached) else text

    if len(protected) > MAX_CHARS_PER_REQUEST:
        return text

    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": target,
        "dt": "t",
        "q": protected,
    }
    url = TRANSLATE_API_URL + "?" + urlencode(params)
    try:
        req = Request(url)
        for k, v in HEADERS.items():
            req.add_header(k, v)
        socket.setdefaulttimeout(REQUEST_TIMEOUT)
        response = urlopen(req, timeout=REQUEST_TIMEOUT)
        raw = response.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = loads(raw)
        translated = ""
        if isinstance(data, list) and data:
            for item in data[0]:
                if item and isinstance(item, list) and item[0]:
                    translated += item[0]
        translated = restore_placeholders(translated.strip(), placeholders)
        if translated and translated != text and placeholder_safe(text, translated):
            cache[key] = protect_placeholders(translated)[0]
            save_cache(cache_path, cache)
            time.sleep(REQUEST_DELAY)
            return translated
        return text
    except (HTTPError, URLError, socket.timeout, ValueError, Exception) as e:
        log("    translation failed [{}]: {}".format(lang, e))
        return text
    finally:
        socket.setdefaulttimeout(None)


def backup_locale(locale_dir):
    if not os.path.isdir(locale_dir):
        return None
    dst = locale_dir.rstrip(os.sep) + "_backup_" + nowstamp()
    shutil.copytree(locale_dir, dst)
    return dst


def clean_old_domain_files(locale_dir, lang, old_domain=OLD_DOMAIN):
    lc = os.path.join(locale_dir, lang, "LC_MESSAGES")
    for ext in ("po", "mo"):
        p = os.path.join(lc, "{}.{}".format(old_domain, ext))
        if os.path.isfile(p):
            os.remove(p)


def update_init_file(plugin_dir, apply=False):
    init_path = os.path.join(plugin_dir, "__init__.py")
    if not os.path.isfile(init_path):
        return False, "__init__.py not found"
    content = read_text(init_path)
    changed = False
    new = content
    if "SubsSupportPro" not in new or "bindtextdomain" not in new:
        return False, "Could not confidently patch __init__.py"

    # Add explicit PluginLanguageDomain/Path constants if missing.
    if "PluginLanguageDomain" not in new:
        marker = "import os\n"
        insertion = "\nPluginLanguageDomain = \'{}\'\nPluginLanguagePath = \'Extensions/{}/locale\'\n".format(DOMAIN, PLUGIN_FOLDER_NAME)
        if marker in new:
            new = new.replace(marker, marker + insertion, 1)
            changed = True
    else:
        new2 = re.sub(r"PluginLanguageDomain\s*=\s*['\"][^'\"]+['\"]", "PluginLanguageDomain = '{}'".format(DOMAIN), new)
        if new2 != new:
            new = new2
            changed = True

    # Replace literal domain occurrences in gettext calls.
    new2 = new.replace('"{}"'.format(OLD_DOMAIN), '"{}"'.format(DOMAIN)).replace("'{}'".format(OLD_DOMAIN), "'{}'".format(DOMAIN))
    if new2 != new:
        new = new2
        changed = True

    if apply and changed:
        shutil.copy2(init_path, init_path + ".bak_" + nowstamp())
        write_text(init_path, new)
    return changed, "patched" if changed else "already ok"


def main(argv=None):
    global DOMAIN, OLD_DOMAIN
    parser = argparse.ArgumentParser(description="Build SubsSupportPro .pot/.po/.mo translation files")
    parser.add_argument("--plugin-dir", default=os.getcwd(), help="Path to SubsSupportPro plugin directory")
    parser.add_argument("--domain", default=DOMAIN, help="New gettext domain; default SubsSupportPro")
    parser.add_argument("--old-domain", default=OLD_DOMAIN, help="Old gettext domain to migrate from; default SubsSupport")
    parser.add_argument("--languages", default="existing", help="Comma list, 'existing', or 'default'. Default: existing")
    parser.add_argument("--auto-translate", dest="auto_translate", action="store_true", default=True, help="Auto translate empty msgstr values; default enabled")
    parser.add_argument("--no-auto-translate", dest="auto_translate", action="store_false", help="Do not call Google Translate")
    parser.add_argument("--compile", dest="compile_mo", action="store_true", default=True, help="Compile .po to .mo; default enabled")
    parser.add_argument("--no-compile", dest="compile_mo", action="store_false", help="Skip .mo compilation")
    parser.add_argument("--backup", dest="backup", action="store_true", default=True, help="Backup locale folder first; default enabled")
    parser.add_argument("--no-backup", dest="backup", action="store_false", help="Do not backup locale folder")
    parser.add_argument("--clean-old", action="store_true", help="Remove old SubsSupport.po/.mo after creating SubsSupportPro files")
    parser.add_argument("--patch-init", action="store_true", help="Patch __init__.py domain constants/references if needed")
    parser.add_argument("--dry-run", action="store_true", help="Analyze only; do not write files")
    args = parser.parse_args(argv)

    DOMAIN = args.domain
    OLD_DOMAIN = args.old_domain

    plugin_dir = os.path.abspath(args.plugin_dir)
    locale_dir = os.path.join(plugin_dir, "locale")
    pot_path = os.path.join(locale_dir, "{}.pot".format(DOMAIN))
    cache_path = os.path.join(plugin_dir, "translation_cache_{}.json".format(DOMAIN))

    log("=" * 72)
    log("SubsSupportPro Translation Auto Builder")
    log("Plugin dir : {}".format(plugin_dir))
    log("Domain     : {}".format(DOMAIN))
    log("Old domain : {}".format(OLD_DOMAIN))
    log("=" * 72)

    if not os.path.isdir(plugin_dir):
        log("ERROR: plugin directory not found: {}".format(plugin_dir))
        return 2

    if args.patch_init:
        changed, message = update_init_file(plugin_dir, apply=not args.dry_run)
        log("__init__.py: {}".format(message))

    existing_langs = discover_existing_languages(locale_dir)
    if args.languages == "existing":
        languages = existing_langs
    elif args.languages == "default":
        languages = sorted(set(DEFAULT_LANGUAGES + existing_langs))
    else:
        languages = [x.strip() for x in args.languages.split(",") if x.strip()]

    if not languages:
        languages = DEFAULT_LANGUAGES

    log("Languages  : {}".format(", ".join(languages)))

    catalog = extract_catalog(plugin_dir)
    log("Extracted  : {} unique strings".format(len(catalog)))

    if len(catalog) == 0:
        log("ERROR: no translatable strings found. Check that source uses _('text').")
        return 3

    if args.dry_run:
        log("Dry-run: no files written.")
        return 0

    ensure_dir(locale_dir)
    if args.backup:
        backup_path = backup_locale(locale_dir)
        if backup_path:
            log("Backup     : {}".format(backup_path))

    write_pot_file(pot_path, catalog)
    log("POT        : {}".format(pot_path))

    cache = load_cache(cache_path)

    total_missing = 0
    total_auto = 0
    for lang in languages:
        translations, sources = load_language_translations(locale_dir, lang, DOMAIN, OLD_DOMAIN)
        missing = 0
        auto_done = 0
        if args.auto_translate:
            for msgid in catalog.keys():
                if translations.get(msgid):
                    continue
                if google_lang(lang) == SOURCE_LANGUAGE:
                    translations[msgid] = msgid
                    auto_done += 1
                    continue
                missing += 1
                translated = translate_text(msgid, lang, cache, cache_path)
                if translated and translated != msgid:
                    translations[msgid] = translated
                    auto_done += 1
        else:
            for msgid in catalog.keys():
                if not translations.get(msgid):
                    missing += 1

        lc = os.path.join(locale_dir, lang, "LC_MESSAGES")
        ensure_dir(lc)
        po_path = os.path.join(lc, "{}.po".format(DOMAIN))
        mo_path = os.path.join(lc, "{}.mo".format(DOMAIN))
        write_po_file(po_path, lang, catalog, translations)
        if args.compile_mo:
            compile_mo(po_path, mo_path)
        if args.clean_old:
            clean_old_domain_files(locale_dir, lang, OLD_DOMAIN)

        total_missing += missing
        total_auto += auto_done
        log("{:<8} po={}  mo={}  sources={}  missing={}  auto={}".format(
            lang,
            os.path.relpath(po_path, plugin_dir),
            "yes" if args.compile_mo else "no",
            len(sources),
            missing,
            auto_done,
        ))

    save_cache(cache_path, cache)
    log("=" * 72)
    log("Done. POT strings: {} | languages: {} | missing checked: {} | auto-filled: {}".format(
        len(catalog), len(languages), total_missing, total_auto
    ))
    log("Generated domain files are named {}.po / {}.mo".format(DOMAIN, DOMAIN))
    log("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
