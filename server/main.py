import os
import json
import time
import base64
import shutil
import logging
from logging.handlers import RotatingFileHandler
from hashlib import md5
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import urlparse

import pathlib
import apis
import hunspell
import requests
from flask import Flask, render_template, request, session, make_response, redirect, abort
from flask_session import Session
from flask_login import LoginManager, login_required, login_user, current_user, logout_user
from PIL import Image
from settings import *
from utils import highlight_sentence, unique_list, get_glosbe_lang_pairs
from IPython import embed
from fuzzywuzzy.process import dedupe as fuzzy_dedupe

app = Flask(__name__, static_url_path='/static')

hobj = hunspell.HunSpell('../spellcheck_dicts/en_GB.dic',
                         '../spellcheck_dicts/en_GB.aff')

app.config.from_object(__name__)

Session(app)
SESSION_TYPE = "filesystem"
SCRIPT_FILENAME = os.path.dirname(os.path.realpath(__file__))

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# import logging
# logging.basicConfig(filename='flask-logging.log', level=logging.DEBUG)

app.logger.info = print


@app.before_request
def make_session_permanent():
    session.permanent = True


def selected_language():
    return session.get("selected_language", "cs")


class User():
    """All users are authenticated because we create this object only for authentificated users"""

    def __init__(self, user_id):
        self.is_authenticated = True
        self.is_active = self.is_authenticated
        self.is_anonymous = not self.is_authenticated
        self.user_id = user_id

    def get_id(self):
        return self.user_id

    @staticmethod
    def get(user_id):
        base_path = get_base_path(user_id)
        if not os.path.exists(base_path):
            return None
        return User(user_id)


@login_manager.user_loader
def load_user(user_id):
    # app.logger.info("LOGIN: AAAA >%s<" % user_id)
    return User.get(user_id)


@app.route("/")
@login_required
def intro():
    language_pairs = get_glosbe_lang_pairs()

    return render_template(
        'intro.html',
        language_pairs=language_pairs,
        selected_language=selected_language())


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        # remember_me = request.form["remember_me"] == "on"

        if sync_collection(username, password, "download"):
            user = User.get(username)
            login_user(user)
        else:
            return render_template('login.html', msg="Wrong login. Try again")

        next = request.args.get('next')

        # duplicity with flask-login, but I do not know how to load password for that
        session["username"] = username
        session["password"] = password

        # vulnerability: open redirects. See http://flask.pocoo.org/snippets/62/
        return redirect(next or "/")
    return render_template('login.html')


@app.route("/logout", methods=['POST'])
@login_required
def logout_page():
    logout_user()
    return redirect("/")


def delete_dir_if_exists(path):
    app.logger.info("deleting: %s" % path)
    if os.path.isdir(path):
        shutil.rmtree(path)


@app.route("/destroy", methods=['POST'])
@login_required
def destroy():
    user = current_user
    delete_dir_if_exists(get_base_path(user.user_id))
    delete_dir_if_exists(get_base_path(session["username"]))
    logout_user()
    session.clear()
    return redirect("/")


@app.route("/set_lang", methods=['POST'])
@login_required
def set_lang():
    session["selected_language"] = request.form["lang_code"]
    return redirect("/")


def download(url, base_path):
    h = md5(url.encode()).hexdigest()

    # getting filename suffix, eg: .jpg.
    # I do not know why do we want to keep suffixes
    app.logger.info("url: %s" % url)
    url_path = urlparse(url).path
    app.logger.info("url_path: %s" % url_path)
    suffix = pathlib.Path(url_path).suffix
    app.logger.info("suffix %s" % suffix)

    filename = "{}{}".format(h, suffix)
    full_path = base_path + "/collection.media/" + filename
    r = requests.get(url, verify=False)
    with open(filename, 'wb') as fd:
        for chunk in r.iter_content(chunk_size=1024):
            fd.write(chunk)
    return full_path


def resize_img(img_path, max_size):
    app.logger.info("img_path: %s" % img_path)
    img_filename = os.path.basename(img_path)
    thumbnail_filename = "thumbnail_{}.png".format(img_filename)
    try:
        canvas = Image.open(img_path).convert("RGBA")
        canvas.thumbnail((max_size, max_size), Image.ANTIALIAS)
        canvas.save(thumbnail_filename, "PNG")
    except IOError as e:
        app.logger.info("cannot create thumbnail for '%s'" % img_path)
        app.logger.info(e)
    app.logger.info("tf: %s" % thumbnail_filename)
    return thumbnail_filename


def get_base_path(ankiweb_username):
    return PROFILES_PATH.format(
        ankiweb_username_base32=base64.b32encode(
            bytes(ankiweb_username, encoding="utf-8")).decode("ascii"))


def open_or_create_collection(ankiweb_username):
    from anki import Collection
    base_path = get_base_path(ankiweb_username)
    app.logger.info(base_path)
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

    # clozedeck = data["clozedeck"][0]
    # spellingdeck = data["spellingdeck"][0]
    maindeck = data["maindeck"][0]
    if data.get("example"):
        data["example"] = fuzzy_dedupe(data["example"])

    collection = None
    try:
        if data.get("use_maindeck"):
            user = current_user
            collection = open_or_create_collection(user.user_id)
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
            base_path = get_base_path(user.user_id)
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
    #     if data.get("use_clozedeck"):
    #         collection = open_or_create_collection(ankiweb_username)
    #         deckId = collection.decks.id(clozedeck)
    #         collection.decks.select(deckId)
    #         basic_model = collection.models.byName('Cloze')
    #         basic_model['did'] = deckId
    #         collection.models.save(basic_model)
    #         collection.models.setCurrent(basic_model)

    #         translations_str = ", ".join(data.get("glosbe", []))
    #         for cloze_sentence in create_cloze_data(data):
    #             fact = collection.newNote()

    #             # from IPython import embed
    #             # embed()
    #             fact['Text'] = "{} ({})".format(cloze_sentence,
    #                                             translations_str)

    #             ipas = ", ".join(data.get("pronunciations", []))
    #             fact[
    #                 'Extra'] = "<hr>[sound:%s](%s)<br/><img src='%s' /><br/>" % (
    #                     audio_filename, ipas, img_resized_filename)
    #             collection.addNote(fact)

    #         collection.save()
    #         collection.close()

    #     # creating cards w/ typing
    #     if data.get("use_spellingdeck") and audio_filename:
    #         collection = open_or_create_collection(ankiweb_username)
    #         deckId = collection.decks.id(spellingdeck)
    #         collection.decks.select(deckId)
    #         basic_model = collection.models.byName('Text-input2')
    #         if not basic_model:
    #             app.logger.info("model text-input does not exist")

    #             basic_model = json.load(
    #                 open(SCRIPT_FILENAME + "/data/Text-input-card.json"))
    #             collection.models.add(basic_model)

    #         basic_model['did'] = deckId
    #         collection.models.save(basic_model)
    #         collection.models.setCurrent(basic_model)

    #         fact = collection.newNote()
    #         fact["Front"] = "[sound:%s]" % audio_filename
    #         fact["Back"] = word

    #         collection.addNote(fact)

    #         collection.save()
    #         collection.close()
    except:
        if collection:
            collection.close()
        raise


def sync_collection(username, password, full_sync="upload"):
    from anki.sync import Syncer, RemoteServer, FullSyncer, MediaSyncer, RemoteMediaServer

    collection = open_or_create_collection(username)

    server = RemoteServer(None)
    app.logger.info("u: %s,pass: %s" % (username, password))
    hkey = server.hostKey(username, password)
    syncer = Syncer(collection, server)
    ret = syncer.sync()
    app.logger.info("syncer return: %s" % ret)

    if (ret == "fullSync"):
        # app.logger.info("trying to do fullSync - upload - Not tested")
        client = FullSyncer(collection, hkey, server.client)
        if full_sync == "download":
            client.download()
        else:
            client.upload()

    if ret not in ("noChanges", "fullSync", "success"):
        collection.close()
        return False

    mediaserver = RemoteMediaServer(collection, hkey, server.client)
    mediaclient = MediaSyncer(collection, mediaserver)
    mediaret = mediaclient.sync()
    app.logger.info("mediasync returned: %s" % mediaret)
    collection.save()
    collection.close()

    return True


@app.route("/sync", methods=['POST'])
@login_required
def sync_page():
    if sync_collection(session["username"], session["password"]):
        return render_template("success_sync.html")
    else:
        abort(400)


@app.route("/word", methods=['GET', 'POST'])
@login_required
def word():
    if request.method == 'POST':
        data_raw = dict(list(request.form.lists()))
        process_data(data_raw)
        resp = make_response(render_template('success.html'))
        resp.set_cookie('maindeck',
                        bytes(data_raw["maindeck"][0], encoding="utf-8"))
        # resp.set_cookie('clozedeck',
        #                 bytes(data_raw["clozedeck"][0], encoding="utf-8"))
        # resp.set_cookie('spellingdeck',
        #                 bytes(data_raw["spellingdeck"][0], encoding="utf-8"))
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
    apis.get_glosbe_data(word, "eng", selected_language(), pool, futures)
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

    language_pairs = get_glosbe_lang_pairs()
    # TODO: default lang is czech
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
        spellingdeck=spellingdeck,
        selected_language=language_pairs[selected_language()])


app.secret_key = flask_secret_key
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365 * 10)

# formatter = logging.Formatter(
#     "[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s")

if __name__ == "__main__":
    # handler = RotatingFileHandler(
    # 'flask-logging.log', maxBytes=1000 * 1000, backupCount=10)
    # handler.setLevel(logging.DEBUG)
    # handler.setFormatter(formatter)
    # app.logger.addHandler(handler)

    # log = logging.getLogger('werkzeug')
    # log.setLevel(logging.DEBUG)
    # log.addHandler(handler)

    # from flask.logging import default_handler
    # app.logger.removeHandler(default_handler)
    app.run(debug=False, host="0.0.0.0")
