import itertools
import random
from lxml import etree
import os
import json
import urllib.error
import urllib.parse
import urllib.request

from pyquery import PyQuery as pq
from apiclient.discovery import build
import requests
from settings import *
from utils import highlight_sentence, unique_list

websterTree = etree.parse("data/WebstersUnabridged.xml")

from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


# Google images:
def get_images_data(word, pool, futures):
    service = build("customsearch", "v1", developerKey=googleDevKey)

    def fut(word):
        res = service.cse().list(
            q=word, cx=googleCX, searchType='image', num=10,
            safe='off').execute()
        return {"images": res.get("items") or ""}

    futures["images"] = pool.submit(fut, (word))


# Etym online:
def get_etymonline_data(word, pool, futures):
    def fut(word):
        try:
            d = pq(url="https://www.etymonline.com/word/{}".format(word))
        except urllib.error.HTTPError:  # not found
            return None
        try:
            etyms = d("section")
            etyms = [etym.text_content().strip() for etym in etyms]

            return "\n\n".join(etyms)
        except IndexError:
            return None

    futures["etymology"] = pool.submit(fut, (word))


# Webster:
def get_webster_data(word):
    def take_subelements(element, class_):
        return [
            elem.text.strip()
            for elem in element.cssselect(".{}".format(class_))
        ]

    entries = websterTree.find('.//entry[@title="{}"]'.format(word.upper()))
    keys = [
        "definition", "etymology", "pronunciation", "part_of_speech",
        "specialty"
    ]
    data = {key: [] for key in keys}
    if entries is not None:
        for entry in entries:
            for key in keys:
                data[key] += take_subelements(entry, key)
    return data


# Pearson:
def parse_pronunciations(results):
    ipas = []
    for r in results:
        if r.get("pronunciations"):
            for pron in r["pronunciations"]:
                if pron.get("ipa"):
                    for ipa in [p.split() for p in pron["ipa"].split(",")]:
                        ipas += ipa
                    break  # just from inner cycle
    # unique:
    ipas = list(set([ipa.strip() for ipa in ipas]))
    return ipas


def parse_audios(results):
    all_audios = []
    for r in results:
        if r.get("pronunciations"):
            for pron in r["pronunciations"]:
                if pron.get("audio"):
                    for a in pron["audio"]:
                        a["filename"] = os.path.basename(a["url"])
                    all_audios.append(pron["audio"])

    return list(itertools.chain.from_iterable(all_audios))  # flatten


def parse_senses(results):
    senses = []
    exs = []

    for r in results:
        if r.get("senses"):
            for s in r["senses"]:
                s["part_of_speech"] = r.get("part_of_speech")
                s["definition"] = s.get("definition") or ''
                if s.get("definition") and type(s["definition"]) != list:
                    s["definition"] = [s["definition"]]
                else:
                    senses.append(s)

                examples = s.get("examples") or []
                for example in examples:
                    if example and example.get("text"):
                        exs.append(example["text"])
    return senses, unique_list(exs)


def get_pearson_data(word, pool, futures):
    url = "http://api.pearson.com/v2/dictionaries/entries?headword={word}&limit=100"

    def fut(word):
        data_json = requests.get(
            url.format(word=word),
            headers={
                "Accept": "application/json"
            },
            verify=False).text
        if not data_json:
            return None
        data = json.loads(data_json)
        results = data.get("results") or []
        selected_dicts = ["ldoce5", "lasde", "wordwise", "laad3"]
        selected_results = [
            r for r in results if (set(r["datasets"]) & set(selected_dicts))
        ]

        ipas = parse_pronunciations(selected_results)
        audios = parse_audios(selected_results)
        senses, examples = parse_senses(selected_results)
        # examples = [highlight_sentence(example, word) for example in examples]

        return {
            "ipas": ipas,
            "audios": audios,
            "senses": senses,
            "examples": examples
        }

    futures["pearson"] = pool.submit(fut, (word))


# Glosbe:
def get_glosbe_data(word, from_, dest, pool, futures):
    url = "https://glosbe.com/gapi/translate?from={from_}&dest={dest}&format=json&phrase={word}&pretty=true"

    def fut(word):
        json_doc = requests.get(
            url.format(word=word, from_=from_, dest=dest), verify=False).text
        data = json.loads(json_doc)
        translations = []
        definitions = []
        for item in data['tuc']:
            if 'phrase' in item:
                translations.append(item['phrase']['text'])  # xxx: fragile
            if 'meanings' in item:
                for meaning in item['meanings']:
                    definitions.append(meaning['text'])  # xxx: fragile
        return {"translations": translations, "definitions": definitions}

    futures["glosbe"] = pool.submit(fut, (word))


# wordnik:
def process_related(data):
    if type(data) == dict:
        # when wordnik do not know some words (eg: "o do? Wit") it returns different format without any useful data
        return {}
    return {d["relationshipType"]: d["words"] for d in data}


def get_wordnik_data(word, pool, futures):

    process_data = {
        "cannonical": lambda data: data.get("canonicalForm"),
        "definitions": lambda data: data,
        "relatedWords": process_related,
        "pronunciations": lambda data: data,
        "phrases": lambda data: data,
        "audio": lambda data: data,
    }

    def download_wordnik_data(params):
        name, url = params
        data = requests.get(
            wordnikApiUrl + url.format(word=word),
            params={
                "api_key": wordnikApiKey
            },
            verify=False).json()
        return process_data[name](data)

    urls = {
        "cannonical":
        "word.json/{word}?useCanonical=true&includeSuggestions=true",
        "definitions":
        "word.json/{word}/definitions?limit=200&includeRelated=true&sourceDictionaries=all&useCanonical=false&includeTags=false",
        "relatedWords":
        "word.json/{word}/relatedWords?useCanonical=false&limitPerRelationshipType=100",
        "pronunciations":
        "word.json/{word}/pronunciations?useCanonical=false&limit=50",
        "phrases":
        "word.json/{word}/phrases?limit=50&wlmi=0&useCanonical=false",
        "audio":
        "word.json/{word}/audio?useCanonical=false&limit=50",
    }

    for name, url in urls.items():
        futures[name] = pool.submit(download_wordnik_data, (name, url))


def get_flickr_urls(word, sort):
    url = "https://api.flickr.com/services/rest/?method=flickr.photos.search&api_key={flickr_key}&text={word}&sort=interestingness-desc&safe_search=3&per_page=20".format(
        flickr_key=flickr_key, word=word)
    tree = etree.fromstring(requests.get(url).content)
    d = pq(tree)  # pq(url..) was not working

    image_urls = [
        "https://farm{farm}.staticflickr.com/{server}/{id}_{secret}.jpg".
        format(**photo.attrib) for photo in d("photo")
    ]
    return image_urls


# flickr:
def get_flickr_data(word, pool, futures):
    def fut(word):
        image_urls = unique_list(
            get_flickr_urls(word, "relevance") +
            get_flickr_urls(word, "interestingness-desc"))
        random.shuffle(image_urls)
        return image_urls

    futures["flickr"] = pool.submit(fut, (word))


# wordsapi
def get_wordsapi_data(word, pool, futures):
    def fut(word):
        headers = {
            "X-Mashape-Key":
            "BXP5ZTT6Gjmsh6MD1Y0BmERC8hgAp1ZRrD2jsnduCKrLM38tPE",
            "X-Mashape-Host": "wordsapiv1.p.mashape.com"
        }
        json_data = requests.get(
            "https://wordsapiv1.p.mashape.com/words/{word}".format(word=word),
            headers=headers).json()
        return json_data

    futures["wordsapi"] = pool.submit(fut, (word))
