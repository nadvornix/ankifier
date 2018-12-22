import os
import json
import time
import base64
from hashlib import md5
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pathlib
import apis
import hunspell
import requests
from flask import Flask, render_template, request, session, make_response
from flask_session import Session
from PIL import Image
from settings import *
from utils import highlight_sentence, unique_list
from IPython import embed
from fuzzywuzzy.process import dedupe as fuzzy_dedupe

app = Flask(__name__, static_url_path='/static')

hobj = hunspell.HunSpell('../spellcheck_dicts/en_GB.dic',
                         '../spellcheck_dicts/en_GB.aff')

app.config.from_object(__name__)
Session(app)
SCRIPT_FILENAME = os.path.dirname(os.path.realpath(__file__))


@app.before_request
def make_session_permanent():
    session.permanent = True


@app.route("/")
def intro():
    print(session.get('key', 'not set'))
    session['key'] = 'value'
    return render_template('intro.html')


def download(url, base_path):
    h = md5(url.encode()).hexdigest()
    suffix = pathlib.Path(url).suffix

    filename = "{}{}".format(h, suffix)
    full_path = base_path + "/collection.media/" + filename
    r = requests.get(url, verify=False)
    with open(filename, 'wb') as fd:
        for chunk in r.iter_content(chunk_size=1024):
            fd.write(chunk)
    return full_path


def resize_img(img_filename, max_size):
    thumbnail_filename = "thumbnail_{}.png".format(img_filename)
    try:
        canvas = Image.open(img_filename).convert("RGBA")
        canvas.thumbnail((max_size, max_size), Image.ANTIALIAS)
        canvas.save(thumbnail_filename, "PNG")
    except IOError as e:
        print("cannot create thumbnail for '%s'" % img_filename)
        print(e)

    return thumbnail_filename


def get_base_path(ankiweb_username):
    return PROFILES_PATH.format(
        ankiweb_username_base32=base64.b32encode(
            bytes(ankiweb_username, encoding="utf-8")).decode("ascii"))


def open_or_create_collection(ankiweb_username):
    from anki import Collection
    base_path = get_base_path(ankiweb_username)
    print(base_path)
    if not os.path.exists(base_path):
        os.makedirs(base_path)
    collection = Collection(base_path + "/collection.anki2", log=True)
    return collection


def create_cloze_data(data):
    sentences = []
    if data["s"]:
        sentences.append(data["s"][0])
    if data.get("example"):
        sentences += data["example"]
    word = data["w"][0]
    return [highlight_sentence(sen, word, "{{c1::%s}}") for sen in sentences]


def process_data(data):
    word = data["w"][0]
    with open("words_sumitted.txt", "a") as f:
        f.write("{}\n".format(word))
    data_json = json.dumps(data)
    # embed()

    clozedeck = data["clozedeck"][0]
    spellingdeck = data["spellingdeck"][0]
    maindeck = data["maindeck"][0]
    if data.get("example"):
        data["example"] = fuzzy_dedupe(data["example"])

    collection = None
    try:
        if data.get("use_maindeck"):
            collection = open_or_create_collection(ankiweb_username)
            deckId = collection.decks.id(maindeck)
            collection.decks.select(deckId)
            basic_model = collection.models.byName('Basic')
            basic_model['did'] = deckId
            collection.models.save(basic_model)
            collection.models.setCurrent(basic_model)
            fact = collection.newNote()
            fact['Front'] = data["w"][0]
            data["s_html"] = None
            if data.get("s") in [["SEN"], ["None"], None]:
                data["s"] = None
            if data.get("s"):
                data["s_html"] = highlight_sentence(data["s"][0], word)

            img_filename, audio_filename, img_resized_filename = "", "", ""
            base_path = get_base_path(ankiweb_username)
            if data.get("image"):
                img_filename = download(data["image"][0], base_path)
                img_resized_filename = resize_img(img_filename, 500)

            if data.get("audio"):
                audio_filename = download(data["audio"][0], base_path)

            definitions = []
            highlight_examples = []
            if data.get("example"):
                highlight_examples = [
                    highlight_sentence(example, word)
                    for example in data["example"]
                ]

            deliminer = "###!###"
            for item in (data.get("definition") or []):
                if item.find(deliminer) != -1:
                    pos, definition = item.split(deliminer)
                    definitions.append("<em>({0})</em> {1}".format(
                        pos, definition))
                else:
                    definitions.append(item)
            fact['Back'] = render_template(
                'anki_card.html',
                data=data,
                glosbe=data.get("glosbe") or [],
                definitions=definitions,
                img_filename=img_resized_filename,
                audio_filename=audio_filename,
                data_json=data_json,
                highlight_eaxamples=highlight_examples)

            collection.addNote(fact)

            collection.save()
            collection.close()

        # creating cloze captions
        if data.get("use_clozedeck"):
            collection = open_or_create_collection(ankiweb_username)
            deckId = collection.decks.id(clozedeck)
            collection.decks.select(deckId)
            basic_model = collection.models.byName('Cloze')
            basic_model['did'] = deckId
            collection.models.save(basic_model)
            collection.models.setCurrent(basic_model)

            translations_str = ", ".join(data.get("glosbe", []))
            for cloze_sentence in create_cloze_data(data):
                fact = collection.newNote()

                # from IPython import embed
                # embed()
                fact['Text'] = "{} ({})".format(cloze_sentence,
                                                translations_str)

                ipas = ", ".join(data.get("pronunciations", []))
                fact[
                    'Extra'] = "<hr>[sound:%s](%s)<br/><img src='%s' /><br/>" % (
                        audio_filename, ipas, img_resized_filename)
                collection.addNote(fact)

            collection.save()
            collection.close()

        # creating cards w/ typing
        if data.get("use_spellingdeck") and audio_filename:
            collection = open_or_create_collection(ankiweb_username)
            deckId = collection.decks.id(spellingdeck)
            collection.decks.select(deckId)
            basic_model = collection.models.byName('Text-input2')
            if not basic_model:
                print("model text-input does not exist")

                basic_model = json.load(
                    open(SCRIPT_FILENAME + "/data/Text-input-card.json"))
                collection.models.add(basic_model)

            basic_model['did'] = deckId
            collection.models.save(basic_model)
            collection.models.setCurrent(basic_model)

            fact = collection.newNote()
            fact["Front"] = "[sound:%s]" % audio_filename
            fact["Back"] = word

            collection.addNote(fact)

            collection.save()
            collection.close()
    except:
        if collection:
            collection.close()
        raise


@app.route("/sync", methods=['POST'])
def sync():
    collection = open_or_create_collection(ankiweb_username)
    from anki.sync import Syncer, RemoteServer, FullSyncer, MediaSyncer, RemoteMediaServer

    server = RemoteServer(None)
    hkey = server.hostKey(ankiweb_username, ankiweb_password)
    syncer = Syncer(collection, server)
    ret = syncer.sync()

    if (ret == "fullSync"):
        print("trying to do fullSync - upload - Not tested")
        client = FullSyncer(collection, hkey, server.client)
        print(client.upload())

    mediaserver = RemoteMediaServer(collection, hkey, server.client)
    mediaclient = MediaSyncer(collection, mediaserver)
    mediaret = mediaclient.sync()
    print("mediaret:", mediaret)
    collection.save()
    collection.close()
    return render_template("success_sync.html")


@app.route("/word", methods=['GET', 'POST'])
def word():
    if request.method == 'POST':
        data_raw = dict(list(request.form.lists()))
        process_data(data_raw)
        resp = make_response(render_template('success.html'))
        resp.set_cookie('maindeck',
                        bytes(data_raw["maindeck"][0], encoding="utf-8"))
        resp.set_cookie('clozedeck',
                        bytes(data_raw["clozedeck"][0], encoding="utf-8"))
        resp.set_cookie('spellingdeck',
                        bytes(data_raw["spellingdeck"][0], encoding="utf-8"))
        return resp

    word = request.args['w']
    with open("words_loaded.txt", "a") as f:
        f.write("{}\n".format(word))
    # XXX: if word==None then we have trouble
    sentence = request.args.get('s')

    maindeck = request.cookies.get('maindeck', "English2")
    clozedeck = request.cookies.get('clozedeck', "English2Cloze")
    spellingdeck = request.cookies.get('spellingdeck', "English2Spelling")

    suggestions = None
    if not hobj.spell(word):
        suggestions = hobj.suggest(word)

    pool = ThreadPoolExecutor(50)
    futures = {}

    apis.get_images_data(word, pool, futures)
    apis.get_wordnik_data(word, pool, futures)
    apis.get_glosbe_data(word, "eng", "ces", pool, futures)
    apis.get_pearson_data(word, pool, futures)
    apis.get_etymonline_data(word, pool, futures)
    apis.get_flickr_data(word, pool, futures)
    webster = apis.get_webster_data(word)
    apis.get_wordsapi_data(word, pool, futures)

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
        time.sleep(0.3)

    pearson = results.get("pearson") or {}
    return render_template(
        'word.html',
        word=word,
        sentence=sentence,
        results=results,
        pearson=pearson,
        suggestions=suggestions,
        webster=webster,
        maindeck=maindeck,
        clozedeck=clozedeck,
        spellingdeck=spellingdeck)


app.secret_key = flask_secret_key
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365 * 10)

if __name__ == "__main__":
    app.run(debug=True)
