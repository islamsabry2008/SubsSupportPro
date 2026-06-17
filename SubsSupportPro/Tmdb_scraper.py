# -*- coding: utf-8 -*-
import io
import json
import logging
import random
import re
import time
import warnings
warnings.filterwarnings("ignore", message=".*soupsieve package is not installed.*", category=UserWarning)

import requests
import urllib3
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning
try:
    from urllib.parse import quote_plus
except ImportError:
    from urllib import quote_plus

urllib3.disable_warnings(InsecureRequestWarning)

DEBUG = False

logger = logging.getLogger("SubsSupportPro.TMDB")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [TMDB] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.2 Mobile/15E148 Safari/604.1",
]




def _json_to_unicode(data, indent=2):
    text = json.dumps(data, indent=indent, ensure_ascii=False)
    try:
        basestring
    except NameError:
        basestring = (str,)
    try:
        unicode
    except NameError:
        unicode = str
    try:
        if not isinstance(text, unicode):
            text = text.decode('utf-8')
    except Exception:
        try:
            text = text.decode('utf-8', 'ignore')
        except Exception:
            pass
    return text


def _write_json_utf8(filename, data, indent=2):
    text = _json_to_unicode(data, indent=indent)
    try:
        unicode_type = unicode
    except NameError:
        unicode_type = str
    if isinstance(text, unicode_type):
        text = text.encode('utf-8')
    with open(filename, 'wb') as f:
        f.write(text)


def get_random_ua():
    return random.choice(user_agents)


def build_headers():
    return {
        "User-Agent": get_random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9,ar-EG;q=0.8,ar;q=0.7",
        "Referer": "https://www.themoviedb.org",
        "Connection": "keep-alive",
    }


headers = build_headers()


def _to_text(value):
    if value is None:
        return ""
    try:
        if isinstance(value, bytes):
            return value.decode("utf-8", "ignore")
    except Exception:
        pass
    try:
        return str(value)
    except Exception:
        return ""


def _normalize_search_text(value):
    text = _to_text(value)
    text = re.sub(r"\.[a-z0-9]{2,4}$", " ", text, flags=re.I)
    text = re.sub(r"[\._]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*[\(\[\{]\s*(19|20)\d{2}\s*[\)\]\}]\s*$", "", text).strip()
    text = re.sub(r"\b(19|20)\d{2}\b", " ", text)
    text = re.sub(
        r"\b(720p|1080p|2160p|4k|uhd|hdr|x264|x265|h264|h265|hevc|bluray|blu ray|web[- ]?dl|webrip|hdtv|dvdrip|brrip|proper|repack|extended|remastered)\b",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+", " ", text).strip(" -._")
    return text


def _remove_trailing_media_hint(value):
    text = _normalize_search_text(value)
    # Event names often come as "Title movie" or "Title film".  Treat those
    # words as a search hint, not as part of the TMDB title, while keeping the
    # original query as a later fallback.
    cleaned = re.sub(r"\s+(movie|film|cinema)\s*$", "", text, flags=re.I).strip()
    return cleaned or text


def _tmdb_search_urls(movie_title):
    original = _normalize_search_text(movie_title)
    cleaned = _remove_trailing_media_hint(original)
    queries = []
    for query in (cleaned, original):
        if query and query.lower() not in [q.lower() for q in queries]:
            queries.append(query)

    urls = []
    for query in queries:
        encoded = quote_plus(query)
        urls.append(("movie", query, "https://www.themoviedb.org/search/movie?query={}".format(encoded)))
    for query in queries:
        encoded = quote_plus(query)
        urls.append(("all", query, "https://www.themoviedb.org/search?query={}".format(encoded)))
    return urls


def _safe_request(url, context, timeout= 10):
    try:
        logger.debug("HTTP GET start | context=%s | url=%s", context, url)
        response = requests.get(url, headers=build_headers(), verify=False, timeout=timeout)
        logger.debug(
            "HTTP GET done | context=%s | status=%s | url=%s",
            context,
            response.status_code,
            url,
        )
        response.raise_for_status()
        return response
    except requests.RequestException:
        logger.exception("HTTP GET failed | context=%s | url=%s", context, url)
        return None


def _parse_html(response, context):
    try:
        soup = BeautifulSoup(response.text, "html.parser")
        logger.debug("HTML parsed successfully | context=%s", context)
        return soup
    except Exception:
        logger.exception("HTML parse failed | context=%s", context)
        return None



def _class_list(tag):
    try:
        classes = tag.get("class", [])
        if isinstance(classes, str):
            return classes.split()
        return list(classes)
    except Exception:
        return []


def _has_class(tag, class_name):
    return class_name in _class_list(tag)


def _find_first_with_classes(root, tag_name, classes):
    for tag in root.find_all(tag_name):
        tag_classes = _class_list(tag)
        ok = True
        for class_name in classes:
            if class_name not in tag_classes:
                ok = False
                break
        if ok:
            return tag
    return None


def _find_all_with_classes(root, tag_name, classes):
    result = []
    for tag in root.find_all(tag_name):
        tag_classes = _class_list(tag)
        ok = True
        for class_name in classes:
            if class_name not in tag_classes:
                ok = False
                break
        if ok:
            result.append(tag)
    return result


def _find_first_href_prefix(root, prefixes):
    for tag in root.find_all("a", href=True):
        href = tag.get("href", "")
        for prefix in prefixes:
            if href.startswith(prefix):
                return tag
    return None


def _find_release_date(root):
    return _find_first_with_classes(root, "span", ["release_date"])


def _find_first_div_p(root):
    div = root.find("div")
    if div:
        p = div.find("p")
        if p:
            return p
    return root.find("p")


def _find_images_with_src_contains(root, needle):
    images = []
    for img in root.find_all("img"):
        src = img.get("src")
        if src and needle in src:
            images.append(img)
    return images


def _find_people_profiles(root):
    people = root.find("ol", class_="people")
    if not people:
        return []
    return _find_all_with_classes(people, "li", ["profile"])

def extract_title_from_card(card):
    title_span = (card.find("h2").find("span") if card.find("h2") else None)
    if title_span:
        title = title_span.get_text(strip=True)
        if title:
            return title

    h2_tag = card.find("h2")
    if h2_tag:
        for span in h2_tag.find_all("span", class_="title"):
            span.decompose()
        title = h2_tag.get_text(strip=True)
        if title:
            return title

    a_tag = _find_first_href_prefix(card, ["/movie/", "/tv/"]) or card.find("a", class_="result")
    if a_tag:
        for span in a_tag.find_all("span", class_="title"):
            span.decompose()
        title = a_tag.get_text(strip=True)
        if title:
            return title

    img_tag = card.find("img", class_="poster")
    if img_tag and img_tag.has_attr("alt"):
        return img_tag["alt"]

    if a_tag and a_tag.has_attr("href"):
        url_parts = a_tag["href"].split("/")
        if len(url_parts) > 2:
            title_part = url_parts[-1]
            if "-" in title_part:
                title_part = title_part.split("-", 1)[1]
            return title_part.replace("-", " ").title()

    return "Unknown Title"


def extract_alternative_title(card):
    alt_title_span = card.find("span", class_="title")
    if alt_title_span:
        return alt_title_span.get_text(strip=True)
    return None


def extract_poster_url(card):
    img_tag = card.find("img", class_="poster")
    if img_tag and img_tag.has_attr("src"):
        poster_url = img_tag["src"]
        replacements = {
            "w94_and_h141_bestv2": "w220_and_h330_face",
            "w130_and_h195_bestv2": "w220_and_h330_face",
            "w94_and_h141_face": "w220_and_h330_face",
            "w188_and_h282_face": "w220_and_h330_face",
        }
        for old, new in replacements.items():
            if old in poster_url:
                return poster_url.replace(old, new)
        return poster_url
    return None


def extract_tmdb_id(card):
    a_tag = _find_first_href_prefix(card, ["/movie/", "/tv/"]) or card.find("a", class_="result")
    if a_tag and a_tag.has_attr("href"):
        href = a_tag["href"]
        match = re.search(r"/(?:movie|tv)/(\d+)", href)
        if match:
            return match.group(1)
    return None


def _extract_media_type_from_url(url):
    if "/movie/" in url:
        return "movie"
    if "/tv/" in url:
        return "tv"
    return ""


def _parse_tmdb_search_page(response, query, search_kind, source_index=0):
    logger.info("Parsing TMDB search page | query=%s | kind=%s", query, search_kind)
    if not response:
        return []

    soup = _parse_html(response, "tmdb search")
    if soup is None:
        return []

    results_container = _find_first_with_classes(soup, "div", ["media-card-list"])
    if not results_container:
        logger.warning("TMDB search results container not found | query=%s | kind=%s", query, search_kind)
        logger.debug("Search HTML snippet: %s", response.text[:2000])
        return []

    movie_cards = _find_all_with_classes(results_container, "div", ["comp:media-card"])
    logger.info("Found %d TMDB cards | query=%s | kind=%s", len(movie_cards), query, search_kind)

    if not movie_cards:
        logger.warning("No TMDB cards found | query=%s | kind=%s", query, search_kind)
        logger.debug("Results container snippet: %s", str(results_container)[:3000])
        return []

    movies_data = []

    for index, card in enumerate(movie_cards, 1):
        try:
            movie = {}

            a_tag = _find_first_href_prefix(card, ["/movie/", "/tv/"])

            movie["title"] = extract_title_from_card(card)

            alt_title = extract_alternative_title(card)
            if alt_title:
                movie["alternative_title"] = alt_title

            if a_tag and a_tag.has_attr("href"):
                movie["url"] = "https://www.themoviedb.org" + a_tag["href"]
                inferred_media_type = _extract_media_type_from_url(a_tag["href"])
                if inferred_media_type:
                    movie["media_type"] = inferred_media_type

            release_date = _find_release_date(card)
            if release_date:
                movie["release_date"] = release_date.get_text(" ", strip=True)

            overview_p = _find_first_div_p(card)
            if overview_p:
                overview_text = overview_p.get_text(" ", strip=True)
                if overview_text:
                    movie["overview"] = overview_text

            poster_url = extract_poster_url(card)
            if poster_url:
                movie["poster_url"] = poster_url

            if a_tag and a_tag.has_attr("data-media-type"):
                movie["media_type"] = a_tag["data-media-type"]

            if a_tag and a_tag.has_attr("data-media-adult"):
                movie["adult_content"] = a_tag["data-media-adult"] == "true"

            tmdb_id = extract_tmdb_id(card)
            if tmdb_id:
                movie["tmdb_id"] = tmdb_id

            movie["_source_query"] = query
            movie["_source_kind"] = search_kind
            movie["_source_index"] = source_index

            logger.debug(
                "Parsed card %d | title=%s | release_date=%s | tmdb_id=%s | media_type=%s",
                index,
                movie.get("title"),
                movie.get("release_date"),
                movie.get("tmdb_id"),
                movie.get("media_type"),
            )
            movies_data.append(movie)
        except Exception:
            logger.exception("Failed parsing movie card index=%d", index)

    return movies_data


def _tmdb_result_key(movie):
    media_type = movie.get("media_type", "")
    tmdb_id = movie.get("tmdb_id", "")
    url = movie.get("url", "")
    if media_type and tmdb_id:
        return media_type + ":" + tmdb_id
    return url or (movie.get("title", "") + ":" + movie.get("release_date", ""))


def _simple_title(value):
    value = _normalize_search_text(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tmdb_score(movie, preferred_title):
    score = 0
    media_type = movie.get("media_type", "")
    if media_type == "movie":
        score += 100
    elif media_type == "tv":
        score -= 60
    if movie.get("_source_kind") == "movie":
        score += 30
    score -= int(movie.get("_source_index", 0)) * 5

    wanted = _simple_title(_remove_trailing_media_hint(preferred_title))
    title = _simple_title(movie.get("title", ""))
    alt_title = _simple_title(movie.get("alternative_title", ""))
    if wanted and title == wanted:
        score += 50
    elif wanted and alt_title == wanted:
        score += 40
    elif wanted and (title.startswith(wanted) or wanted.startswith(title)):
        score += 15

    if movie.get("poster_url"):
        score += 2
    if movie.get("release_date"):
        score += 2
    return score


def scrape_tmdb_movies(movie_title):
    logger.info("Searching TMDB movies | title=%s", movie_title)
    all_results = []
    seen = set()

    for source_index, (search_kind, query, url) in enumerate(_tmdb_search_urls(movie_title)):
        logger.info("TMDB search attempt | original=%s | query=%s | kind=%s | url=%s", movie_title, query, search_kind, url)
        response = _safe_request(url, "tmdb search")
        results = _parse_tmdb_search_page(response, query, search_kind, source_index)
        for movie in results:
            key = _tmdb_result_key(movie)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            all_results.append(movie)
        # If the movie-only search already found a likely exact movie match,
        # keep the result fast and avoid generic search bringing TV above it.
        if search_kind == "movie":
            for movie in all_results:
                if movie.get("media_type") == "movie" and _simple_title(movie.get("title", "")) == _simple_title(query):
                    all_results.sort(key=lambda item: _tmdb_score(item, movie_title), reverse=True)
                    return all_results

    all_results.sort(key=lambda item: _tmdb_score(item, movie_title), reverse=True)
    return all_results


def scrape_movie_logos(movie_url):
    logos_url = movie_url + "/images/logos"

    try:
        time.sleep(0.5)
        response = _safe_request(logos_url, "movie logos")
        if not response:
            return []

        soup = _parse_html(response, "movie logos")
        if soup is None:
            return []

        logos_section = soup.find("section", class_="panel user_images")
        if not logos_section:
            logger.debug("No logos section found | movie_url=%s", movie_url)
            return []

        logo_images = []
        logo_elements = _find_images_with_src_contains(logos_section, "w500")

        for logo_element in logo_elements:
            if logo_element.has_attr("src"):
                logo_images.append(logo_element["src"])

        logger.debug("Scraped %d logos | movie_url=%s", len(logo_images), movie_url)
        return logo_images

    except Exception:
        logger.exception("Error scraping logos | movie_url=%s", movie_url)
        return []


def scrape_movie_backdrops(movie_url):
    backdrops_url = movie_url + "/images/backdrops"

    try:
        time.sleep(0.5)
        response = _safe_request(backdrops_url, "movie backdrops")
        if not response:
            return []

        soup = _parse_html(response, "movie backdrops")
        if soup is None:
            return []

        backdrops_section = soup.find("section", class_="panel user_images")
        if not backdrops_section:
            logger.debug("No backdrops section found | movie_url=%s", movie_url)
            return []

        backdrop_images = []
        backdrop_elements = _find_images_with_src_contains(backdrops_section, "w500_and_h282_face")

        for backdrop_element in backdrop_elements:
            if backdrop_element.has_attr("src"):
                backdrop_images.append(backdrop_element["src"])

        logger.debug("Scraped %d backdrops | movie_url=%s", len(backdrop_images), movie_url)
        return backdrop_images

    except Exception:
        logger.exception("Error scraping backdrops | movie_url=%s", movie_url)
        return []


def scrape_movie_posters(movie_url):
    posters_url = movie_url + "/images/posters"

    try:
        time.sleep(0.5)
        response = _safe_request(posters_url, "movie posters")
        if not response:
            return []

        soup = _parse_html(response, "movie posters")
        if soup is None:
            return []

        posters_section = soup.find("section", class_="panel user_images")
        if not posters_section:
            logger.debug("No posters section found | movie_url=%s", movie_url)
            return []

        poster_images = []
        poster_elements = _find_images_with_src_contains(posters_section, "w220_and_h330_face")

        for poster_element in poster_elements:
            if poster_element.has_attr("src"):
                poster_images.append(poster_element["src"])

        logger.debug("Scraped %d posters | movie_url=%s", len(poster_images), movie_url)
        return poster_images

    except Exception:
        logger.exception("Error scraping posters | movie_url=%s", movie_url)
        return []


def scrape_movie_trailers(movie_url):
    trailers_url = movie_url + "/videos?active_nav_item=Trailers"

    try:
        time.sleep(0.5)
        response = _safe_request(trailers_url, "movie trailers")
        if not response:
            return []

        soup = _parse_html(response, "movie trailers")
        if soup is None:
            return []

        trailers_section = soup.find("section", class_="panel video")
        if not trailers_section:
            logger.debug("No trailers section found | movie_url=%s", movie_url)
            return []

        trailers = []
        trailer_elements = trailers_section.find_all("div", class_="video card default")

        for trailer_element in trailer_elements:
            trailer = {}

            play_button = trailer_element.find("a", class_="play_trailer")
            if play_button and play_button.has_attr("data-id"):
                trailer["youtube_id"] = play_button["data-id"]
                trailer["youtube_url"] = 'https://www.youtube.com/watch?v={}'.format(play_button['data-id'])

            title_element = trailer_element.find("h2")
            if title_element:
                trailer["title"] = title_element.get_text(strip=True)

            sub_element = trailer_element.find("h3", class_="sub")
            if sub_element:
                trailer["details"] = sub_element.get_text(strip=True)

            if play_button and play_button.has_attr("data-site"):
                trailer["site"] = play_button["data-site"]

            channel_element = trailer_element.find("h4")
            if channel_element:
                trailer["channel"] = channel_element.get_text(strip=True)

            if trailer:
                trailers.append(trailer)

        logger.debug("Scraped %d trailers | movie_url=%s", len(trailers), movie_url)
        return trailers

    except Exception:
        logger.exception("Error scraping trailers | movie_url=%s", movie_url)
        return []


def scrape_movie_cast(movie_url):
    cast_url = movie_url + "/cast"

    try:
        time.sleep(0.5)
        response = _safe_request(cast_url, "movie cast")
        if not response:
            return []

        soup = _parse_html(response, "movie cast")
        if soup is None:
            return []

        cast_section = soup.find("section", class_="panel pad")
        if not cast_section:
            logger.warning("No cast section found | movie_url=%s", movie_url)
            return []

        cast = []
        cast_elements = cast_section.find_all("li", attrs={"data-order": True})

        for i, cast_element in enumerate(cast_elements[:6]):
            actor = {}

            info_div = cast_element.find("div", class_="info")
            if info_div:
                p_tag = info_div.find("p")
                if p_tag:
                    a_tag = p_tag.find("a")
                    if a_tag:
                        actor["name"] = a_tag.get_text(strip=True)

            character_element = cast_element.find("p", class_="character")
            if character_element:
                actor["character"] = character_element.get_text(strip=True)

            profile_img = cast_element.find("img", class_="profile")
            if profile_img and profile_img.has_attr("src"):
                profile_url = profile_img["src"]
                if "w66_and_h66_face" in profile_url:
                    profile_url = profile_url.replace("w66_and_h66_face", "w132_and_h132_face")
                actor["profile_url"] = profile_url

            if actor.get("name"):
                cast.append(actor)
            else:
                logger.warning("No name found for cast member index=%d | movie_url=%s", i, movie_url)

        logger.debug("Scraped %d cast members | movie_url=%s", len(cast), movie_url)
        return cast

    except Exception:
        logger.exception("Error scraping cast | movie_url=%s", movie_url)
        return []


def scrape_movie_details(movie_url):
    try:
        logger.info("Scraping movie details | movie_url=%s", movie_url)
        response = _safe_request(movie_url, "movie details")
        if not response:
            return None

        soup = _parse_html(response, "movie details")
        if soup is None:
            return None

        details = {}

        title_element = soup.find("h2", class_="title")
        if title_element:
            details["title"] = title_element.get_text(strip=True)

        tagline_element = soup.find("h3", class_="tagline")
        if tagline_element:
            details["tagline"] = tagline_element.get_text(strip=True)

        overview_element = soup.find("div", class_="overview")
        if overview_element:
            details["overview"] = (
                overview_element.find("p").get_text(strip=True)
                if overview_element.find("p")
                else overview_element.get_text(strip=True)
            )

        release_date_element = soup.find("span", class_="release")
        if release_date_element:
            details["release_date"] = release_date_element.get_text(strip=True)

        runtime_element = soup.find("span", class_="runtime")
        if runtime_element:
            details["runtime"] = runtime_element.get_text(strip=True)

        genres = []
        genres_elements = soup.find("span", class_="genres")
        if genres_elements:
            for genre in genres_elements.find_all("a"):
                genres.append(genre.get_text(strip=True))
            details["genres"] = genres

        rating_element = soup.find("div", class_="user_score_chart")
        if rating_element and rating_element.has_attr("data-percent"):
            details["rating"] = rating_element["data-percent"]

        poster_element = soup.find("img", class_="poster")
        if poster_element and poster_element.has_attr("src"):
            details["poster_url"] = poster_element["src"]

        logos = scrape_movie_logos(movie_url)
        if logos:
            details["logo_urls"] = logos

        backdrops = scrape_movie_backdrops(movie_url)
        if backdrops:
            details["backdrop_urls"] = backdrops

        posters = scrape_movie_posters(movie_url)
        if posters:
            details["additional_poster_urls"] = posters

        trailers = scrape_movie_trailers(movie_url)
        if trailers:
            details["trailers"] = trailers

        cast = scrape_movie_cast(movie_url)
        if cast:
            details["cast"] = cast

        director_elements = _find_people_profiles(soup)
        for director_element in director_elements:
            job_element = director_element.find("p", class_="job")
            if job_element and "director" in job_element.get_text(strip=True).lower():
                name_element = director_element.find("p", class_="name")
                if name_element:
                    details["director"] = (
                        name_element.find("a").get_text(strip=True)
                        if name_element.find("a")
                        else name_element.get_text(strip=True)
                    )
                break

        logger.info(
            "Scraped movie details complete | movie_url=%s | fields=%s",
            movie_url,
            sorted(details.keys()),
        )
        return details

    except Exception:
        logger.exception("Error scraping movie details | movie_url=%s", movie_url)
        return None


def main():
    title = input("Please enter movie name: ")

    try:
        movies = scrape_tmdb_movies(title)

        if not movies:
            print("No movies found!")
            return

        print('\nFound {} movies:\n'.format(len(movies)))

        for i, movie in enumerate(movies, 1):
            print('{}. {} ({})'.format(i, movie.get('title', 'N/A'), movie.get('release_date', 'N/A')))

        selection = input("\nEnter the number of the movie you want to scrape details for (or 'all' for all movies): ")

        if selection.lower() == "all":
            detailed_movies = []
            for i, movie in enumerate(movies, 1):
                print('Scraping details for movie {}/{}: {}'.format(i, len(movies), movie.get('title', 'N/A')))
                if "url" in movie:
                    details = scrape_movie_details(movie["url"])
                    if details:
                        if "cast" in details:
                            for actor in details["cast"]:
                                if "profile_url" in actor and "w66_and_h66_face" in actor["profile_url"]:
                                    actor["profile_url"] = actor["profile_url"].replace("w66_and_h66_face", "w132_and_h132_face")

                        merged_info = movie.copy()
                        merged_info.update(details)
                        detailed_movies.append(merged_info)

            filename = 'tmdb_{}_detailed_results.json'.format(title.replace(' ', '_'))
            _write_json_utf8(filename, detailed_movies)
            print('All detailed results saved to {}'.format(filename))
            logger.info("Saved all detailed results | file=%s | count=%d", filename, len(detailed_movies))

        else:
            try:
                selection_idx = int(selection) - 1
                if 0 <= selection_idx < len(movies):
                    selected_movie = movies[selection_idx]
                    print('\nScraping details for: {}'.format(selected_movie.get('title', 'N/A')))

                    if "url" in selected_movie:
                        details = scrape_movie_details(selected_movie["url"])
                        if details:
                            if "cast" in details:
                                for actor in details["cast"]:
                                    if "profile_url" in actor and "w66_and_h66_face" in actor["profile_url"]:
                                        actor["profile_url"] = actor["profile_url"].replace("w66_and_h66_face", "w132_and_h132_face")

                            merged_info = selected_movie.copy()
                            merged_info.update(details)

                            year = ""
                            if "release_date" in merged_info:
                                year_match = re.search(r"\d{4}", merged_info["release_date"])
                                if year_match:
                                    year = '_{}'.format(year_match.group())

                            filename = 'tmdb_{}{}_details.json'.format(merged_info.get('title', 'unknown').replace(' ', '_'), year)

                            print("\nDetailed Movie Information:")
                            print("=" * 50)
                            for key, value in merged_info.items():
                                if key == "cast":
                                    print("Cast:")
                                    for i, actor in enumerate(value, 1):
                                        print('  {}. {} as {}'.format(i, actor.get('name', 'N/A'), actor.get('character', 'N/A')))
                                        if "profile_url" in actor:
                                            print('     Profile: {}'.format(actor['profile_url']))
                                elif key == "logo_urls":
                                    print("Logos:")
                                    for i, logo_url in enumerate(value, 1):
                                        print('  {}. {}'.format(i, logo_url))
                                elif key == "backdrop_urls":
                                    print("Backdrops:")
                                    for i, backdrop_url in enumerate(value, 1):
                                        print('  {}. {}'.format(i, backdrop_url))
                                elif key == "additional_poster_urls":
                                    print("Additional Posters:")
                                    for i, poster_url in enumerate(value, 1):
                                        print('  {}. {}'.format(i, poster_url))
                                elif key == "trailers":
                                    print("Trailers:")
                                    for i, trailer in enumerate(value, 1):
                                        print('  {}. {}'.format(i, trailer.get('title', 'N/A')))
                                        print('     YouTube ID: {}'.format(trailer.get('youtube_id', 'N/A')))
                                        print('     YouTube URL: {}'.format(trailer.get('youtube_url', 'N/A')))
                                        print('     Details: {}'.format(trailer.get('details', 'N/A')))
                                        print('     Site: {}'.format(trailer.get('site', 'N/A')))
                                        if "channel" in trailer:
                                            print('     Channel: {}'.format(trailer['channel']))
                                elif isinstance(value, list):
                                    print('{}: {}'.format(key.replace('_', ' ').title(), ', '.join(value)))
                                else:
                                    print('{}: {}'.format(key.replace('_', ' ').title(), value))

                            save = input("\nDo you want to save the detailed results to a JSON file? (y/n): ")
                            if save.lower() == "y":
                                _write_json_utf8(filename, merged_info)
                                print('Detailed results saved to {}'.format(filename))
                                logger.info("Saved detailed result | file=%s | title=%s", filename, merged_info.get("title"))
                        else:
                            print("Failed to scrape detailed information.")
                    else:
                        print("No URL found for the selected movie.")
                else:
                    print("Invalid selection.")
            except ValueError:
                print("Please enter a valid number or 'all'.")

    except requests.RequestException as e:
        print('Error making request: {}'.format(e))
        logger.exception("Request error in main")
    except Exception as e:
        print('An error occurred: {}'.format(e))
        logger.exception("Unhandled error in main")


if __name__ == "__main__":
    main()
