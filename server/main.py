from IPython import embed
import requests
import json
import time
from pprint import pprint
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from lxml import etree
import itertools
import http.client, urllib.request, urllib.parse, urllib.error

from hashlib import md5

from flask import Flask
from flask import render_template
from flask import request
from flask import session
app = Flask(__name__)

wordnikApiUrl = 'http://api.wordnik.com/v4/'
wordnikApiKey = '6ba4e1c8a2b0546c7b0080b84fd08feb6ffdd3de24ea7b8c1'
# wordnik = swagger.ApiClient(wordnikApiUrl, wordnikApiKey)


@app.before_request
def make_session_permanent():
    session.permanent = True


def get_images_data(word, pool, futures):

    def fut(word):

        headers = {
            # Request headers
            'Content-Type': 'multipart/form-data',
            'Ocp-Apim-Subscription-Key': '856f37af4bcc4298934e0e52c2b6c970',
        }

        params = urllib.parse.urlencode({
            "q": word
        })

        try:
            conn = http.client.HTTPSConnection('api.cognitive.microsoft.com')
            conn.request("POST", "/bing/v5.0/images/search?%s" % params, "{body}", headers)
            response = conn.getresponse()
            data = response.read()
            conn.close()
            data_json = json.loads(data.decode("utf8"))
            return data_json
        except Exception as e:
            print("[Errno {0}] {1}".format(e.errno, e.strerror))
            return {"images": None}

    futures["images"] = pool.submit(fut, (word))

def get_pearson_data(word, pool, futures):
    url = "http://api.pearson.com/v2/dictionaries/entries?headword={word}&limit=100"


    def fut(word):
        data_json = requests.get(url.format(word=word), headers={"Accept": "application/json"}).text
        print("###", data_json)
        if not data_json:
            return None
        data = json.loads(data_json)
        results = data.get("results") or []
        selected_dicts = ["ldoce5", "lasde", "wordwise", "laad3"]
        selected_results = [r for r in results if (set(r["datasets"]) & set(selected_dicts))]
        
        ipas = {a.get("ipa") for r in selected_results if r.get("pronunciations") for a in r["pronunciations"] if a.get("ipa")}
        audios = [a["audio"] for r in selected_results if r.get("pronunciations") for a in r["pronunciations"] if a.get("audio")]
        audios = list(itertools.chain.from_iterable(audios))  # flatten

        examples = [e.get("text") for r in selected_results for s in r["senses"] if s.get("examples") for e in s["examples"]]
        
        senses = []
        for r in selected_results:
            if r.get("senses"):
                for s in r["senses"]:
                    s["part_of_speech"] = r.get("part_of_speech")
                    s["definition"] = s.get("definition") or ''
                    if s.get("definition") and type(s["definition"]) != list:
                        s["definition"] = [s["definition"]]
                        # senses += s
                    else:
                        senses.append(s)

        print ({"ipas": ipas, "audios": audios, "senses": senses, "examples": examples})
        return {"ipas": ipas, "audios": audios, "senses": senses, "examples": examples}

    futures["pearson"] = pool.submit(fut, (word))


def get_slovnik_data(word, pool, futures):
    url = "http://slovnik.cz/bin/mld.fpl?vcb={word}&trn=p%C5%99elo%C5%BEit&dictdir=encz.en&lines=100&js=0"
    
    def fut(word):
        html_doc = requests.get(url.format(word=word)).text

        soup = BeautifulSoup(html_doc, 'html.parser')
        translations = []

        for pair in soup.find_all(class_="pair"):
            [s.extract() for s in pair('i')]
            l = pair.find(class_="l").text
            r = pair.find(class_="r").text
            translations.append((l, r))
        return translations
    futures["slovnik"] = pool.submit(fut, (word))

def process_ety(data):
    return data
    # etymologies=[]
    # for etymology in data:
    #     b=etree.XML(etymology.encode("utf-8"))
    #     for c in b.xpath("//er"):
    #         c.tag = 'em'
    #     etymology_html = etree.tostring(b, encoding='unicode')
    #     etymologies.append(etymology_html)
    # return etymologies

def process_related(data):
    return {d["relationshipType"]: d["words"] for d in data}

def get_wordnik_data(word, pool, futures):

    process_data = {
        "cannonical": lambda data: data.get("canonicalForm"),
        "examples": lambda data: [d["text"] for d in (data.get("examples") or [])],
        "definitions": lambda data: data,
        "relatedWords": process_related,
        "pronunciations": lambda data: data,
        "phrases": lambda data: data,
        "etymologies": process_ety,
        "audio": lambda data: data,
    }

    def download_wordnik_data(params):
        name, url = params
        data = requests.get(wordnikApiUrl + url.format(word=word), params={"api_key": wordnikApiKey}).json()
        # print (">>", r.text)
        # data = json.loads(r.text)
        # pprint(data)
        return process_data[name](data)

    urls = {
        "cannonical": "word.json/{word}?useCanonical=true&includeSuggestions=true",
        "examples": "word.json/{word}/examples?includeDuplicates=false&useCanonical=false&skip=0&limit=100",
        "definitions": "word.json/{word}/definitions?limit=200&includeRelated=true&sourceDictionaries=all&useCanonical=false&includeTags=false",
        "relatedWords": "word.json/{word}/relatedWords?useCanonical=false&limitPerRelationshipType=100",
        "pronunciations": "word.json/{word}/pronunciations?useCanonical=false&limit=50",
        "phrases": "word.json/{word}/phrases?limit=50&wlmi=0&useCanonical=false",
        "etymologies": "word.json/{word}/etymologies?useCanonical=false",
        "audio": "word.json/{word}/audio?useCanonical=false&limit=50",
    }


    for name, url in urls.items():
        # futures[name] = download_wordnik_data( (name, url))
        # print(name, "is done")
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


def process_data(data):
    from anki import Collection as aopen

    base_path = "/home/jirka/Documents/Anki/User 1/"
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

        img_filename, audio_filename = "", ""
        if data.get("image"):
            img_filename = download(data["image"][0], base_path)

        if data.get("audio"):
            audio_filename = download(data["audio"][0], base_path)

        fact['Back'] = render_template('anki_card.html', data=data, 
            slovnik=[" - ".join(item.split("###!###")) for item in (data.get("slovnik") or [])],
            definitions=["<em>({0})</em> {1}".format(*item.split("###!###")) for item in (data.get("definition") or [])],
            img_filename=img_filename,
            audio_filename=audio_filename
            )

        deck.addNote(fact)
        deck.save()
        deck.close()
    except:
        deck.close()
        raise

@app.route("/word", methods=['GET', 'POST'])
def word():
    # nltk.data.path.append(".")
    if request.method == 'POST':
        # s = request.form['s']
        # w = request.form['w']
        # slovnik = [v.split("###!###") for k,v in request.form.items() if k.startswith("slovnik")]
        # data = {}
        # embed()
        # return "imported"
        
        data_raw = dict(list(request.form.lists()))
        process_data(data_raw)
        # try:
        #     with open("data.json", "r") as f:
        #         data = json.load(f)
        # except FileNotFoundError:
        #     data = []


        # data.append(data_raw)
        # with open("data.json", "w") as f:
        #     json.dump(data, f, indent=4, sort_keys=True)

        # for k, v in request.form.items:
        #     if k not in data:
        #         data[k] = []
        #     data[k].append(v)

        # embed()
        return "OK :-)"

    word = request.args.get('w')
    sentence = request.args.get('s')
    print (word, sentence)

    pool = ThreadPoolExecutor(50)
    futures = {}

    
    get_images_data(word, pool, futures)
    get_wordnik_data(word, pool, futures)
    get_slovnik_data(word, pool, futures)
    get_pearson_data(word, pool, futures)
    time.sleep(15)
    # todo: active waiting

    results = {}
    for name, future in futures.items():
        if future.done():
            results[name] = future.result()
        else:
            print (future, "is not done")

    pprint(results)
    pearson = results.get("pearson") or {}
    return render_template('word.html', word=word, sentence=sentence, results=results, pearson=pearson)

app.secret_key = 'jdf5fgmb.45f§elpjh)2jk4545*/*/f8dh*/d.-,.'
app.config['PERMANENT_SESSION_LIFETIME']=timedelta(days=365*10)

if __name__ == "__main__":
    app.run(debug=True)


