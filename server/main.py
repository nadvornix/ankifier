import itertools
from lxml import etree
from os import path
import json
import time
from hashlib import md5
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from apiclient.discovery import build
import hunspell
import requests
import nltk
from fuzzywuzzy import process
from flask import Flask, render_template, request, session
from PIL import Image
from pyquery import PyQuery as pq
from apikeys import *

app = Flask(__name__, static_url_path='/static')

hobj = hunspell.HunSpell('../spellcheck_dicts/en_GB.dic',
                         '../spellcheck_dicts/en_GB.aff')
tree = etree.parse("data/WebstersUnabridged.xml")


@app.before_request
def make_session_permanent():
    session.permanent = True


def get_images_data(word, pool, futures):
    service = build("customsearch", "v1", developerKey=googleDevKey)

    def fut(word):
        res = service.cse().list(
            q=word, cx=googleCX, searchType='image', num=10,
            safe='off').execute()
        return {"images": res.get("items") or ""}

    futures["images"] = pool.submit(fut, (word))


def get_etymonline_data(word, pool, futures):
    def fut(word):
        try:
            d = pq(url="https://www.etymonline.com/word/{}".format(word))
        except urllib.error.HTTPError:  # not found
            return None
        try:
            return d("section")[0].text_content()
        except IndexError:
            return None

    futures["etymology"] = pool.submit(fut, (word))


def get_webster_data(word):
    def take_subelements(element, class_):
        return [
            elem.text.strip()
            for elem in element.cssselect(".{}".format(class_))
        ]

    entries = tree.find('.//entry[@title="{}"]'.format(word.upper()))
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
                        a["filename"] = path.basename(a["url"])
                    all_audios.append(pron["audio"])

    return list(itertools.chain.from_iterable(all_audios))  # flatten


def unique_list(l):
    return list(set([s.strip() for s in l]))


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
                    # print("type(pearson.example)==",type(example))
                    if example and example.get("text"):
                        exs.append(example["text"])
    return senses, unique_list(exs)


def get_pearson_data(word, pool, futures):
    url = "http://api.pearson.com/v2/dictionaries/entries?headword={word}&limit=100"

    def fut(word):
        data_json = requests.get(
            url.format(word=word), headers={
                "Accept": "application/json"
            }).text
        # print("###", data_json)
        if not data_json:
            return None
        data = json.loads(data_json)
        # pprint (data)
        results = data.get("results") or []
        selected_dicts = ["ldoce5", "lasde", "wordwise", "laad3"]
        selected_results = [
            r for r in results if (set(r["datasets"]) & set(selected_dicts))
        ]

        ipas = parse_pronunciations(selected_results)
        audios = parse_audios(selected_results)
        senses, examples = parse_senses(selected_results)
        examples = [highlight_sentence(example, word) for example in examples]

        return {
            "ipas": ipas,
            "audios": audios,
            "senses": senses,
            "examples": examples
        }

    futures["pearson"] = pool.submit(fut, (word))


def get_glosbe_data(word, from_, dest, pool, futures):
    url = "https://glosbe.com/gapi/translate?from={from_}&dest={dest}&format=json&phrase={word}&pretty=true"

    def fut(word):
        json_doc = requests.get(url.format(word=word, from_=from_,
                                           dest=dest)).text
        data = json.loads(json_doc)
        translations = []
        definitions = []
        for item in data['tuc']:
            if 'phrase' in item:
                translations.append(item['phrase']['text'])  # xxx: fragile
            if 'meanings' in item:
                for meaning in item['meanings']:
                    definitions.append(meaning['text'])  # xxx: fragile
        # print(translations, definitions)
        return {"translations": translations, "definitions": definitions}

    futures["glosbe"] = pool.submit(fut, (word))


def process_related(data):
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
            }).json()
        # print("yyy", data)
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


@app.route("/")
def intro():
    return render_template('intro.html')


def download(url, base_path):
    h = md5(url.encode()).hexdigest()
    filename = base_path + "/collection.media/" + h
    r = requests.get(url)
    with open(filename, 'wb') as fd:
        for chunk in r.iter_content(chunk_size=1024):
            fd.write(chunk)
    return h


def resize_img(img_filename, max_size):
    thumbnail_filename = "thumbnail_{}".format(img_filename)
    try:
        im = Image.open(img_filename).convert("RGB")
        # width, height = im.size
        # ratio = min(max_size/width, max_size/height)
        # new_size = oldsize*ratio
        im.thumbnail((max_size, max_size), Image.ANTIALIAS)
        im.save(thumbnail_filename, "JPEG")
    except IOError as e:
        print("cannot create thumbnail for '%s'" % img_filename)

    return thumbnail_filename


def process_data(data):
    from anki import Collection as aopen

    word = data["w"][0]
    with open("words_sumitted.txt", "a") as f:
        f.write("{}\n".format(word))

    data_json = json.dumps(data)
    base_path = "/home/jiri/.local/share/Anki2/User 1/"
    deck = aopen(base_path + "collection.anki2")
    try:
        deckId = deck.decks.id("English2")
        deck.decks.select(deckId)
        basic_model = deck.models.byName('Basic')
        basic_model['did'] = deckId
        deck.models.save(basic_model)
        deck.models.setCurrent(basic_model)
        fact = deck.newNote()
        fact['Front'] = data["w"][0]

        img_filename, audio_filename, img_resized_filename = "", "", ""
        if data.get("image"):
            img_filename = download(data["image"][0], base_path)
            img_resized_filename = resize_img(img_filename, 500)

        if data.get("audio"):
            audio_filename = download(data["audio"][0], base_path)

        definitions = []
        deliminer = "###!###"
        for item in (data.get("definition") or []):
            if item.find(deliminer) != -1:
                pos, definition = item.split(deliminer)
                definitions.append("<em>({0})</em> {1}".format(
                    pos, definition))
            else:
                definitions.append(item)
        # slovnik=[" - ".join(item.split("###!###")) for item in (data.get("slovnik") or [])],

        fact['Back'] = render_template(
            'anki_card.html',
            data=data,
            glosbe=data.get("glosbe") or [],
            definitions=definitions,
            img_filename=img_resized_filename,
            audio_filename=audio_filename,
            data_json=data_json)

        deck.addNote(fact)
        deck.save()
        deck.close()
    except:
        deck.close()
        raise


def highlight_sentence(sentence, word):
    if type(sentence) == str:
        words = nltk.word_tokenize(sentence)
        best_match, _ = process.extractOne(word, words)
        return sentence.replace(best_match, "<em>{}</em>".format(best_match))
    else:
        return sentence


@app.route("/word", methods=['GET', 'POST'])
def word():
    if request.method == 'POST':
        data_raw = dict(list(request.form.lists()))
        process_data(data_raw)

        return render_template('success.html')

    word = request.args['w']
    with open("words_loaded.txt", "a") as f:
        f.write("{}\n".format(word))
    # XXX: if word==None then we have trouble
    sentence = request.args.get('s')
    sentence_hl = highlight_sentence(sentence, word)

    suggestions = None
    if not hobj.spell(word):
        suggestions = hobj.suggest(word)

    pool = ThreadPoolExecutor(50)
    futures = {}

    get_images_data(word, pool, futures)
    get_wordnik_data(word, pool, futures)
    # get_slovnik_data(word, pool, futures)
    get_glosbe_data(word, "eng", "ces", pool, futures)
    get_pearson_data(word, pool, futures)
    get_etymonline_data(word, pool, futures)
    webster = get_webster_data(word)
    beginning = time.time()

    not_finished = True
    results = {}
    while time.time() - beginning < 15 and not_finished:
        not_finished = False
        for name, future in futures.items():
            if future.done():
                if name not in results:
                    results[name] = future.result()
            else:
                not_finished = True
                # print (future, "is not done")
        time.sleep(0.3)

    pearson = results.get("pearson") or {}
    return render_template(
        'word.html',
        word=word,
        sentence=sentence,
        sentence_hl=sentence_hl,
        results=results,
        pearson=pearson,
        suggestions=suggestions,
        webster=webster)


app.secret_key = 'jdf5fgmb.45f§elpjh)2jk4545*/*/f8dh*/d.-,.'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365 * 10)

if __name__ == "__main__":
    app.run(debug=True)
