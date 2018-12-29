import nltk
from fuzzywuzzy import process, fuzz


def get_glosbe_lang_pairs():
    with open("glosbe-languages.csv") as f:
        data = f.readlines()
        language_pairs = [tuple(line.split(";")) for line in data]
        return dict(language_pairs)


def my_extract_one(word, words):
    """ Nakonec možná byl bug někde jinde a i defaultní process.extractOne by stačil"""
    ranked_words = sorted([(fuzz.ratio(word, w), w) for w in words],
                          reverse=True)
    if ranked_words:
        return ranked_words[0][1]
    return None


def highlight_sentence(sentence, word, highlight="<em>%s</em>"):
    if type(sentence) == str:
        words = nltk.word_tokenize(sentence)
        # best_match = process.extractOne(word, words)
        best_match = my_extract_one(word, words)
        if best_match:
            highlighted_sentence = sentence.replace(best_match,
                                                    highlight % best_match)
            return highlighted_sentence
    else:
        return sentence


def unique_list(l):
    d = {s.lower().strip(): s.strip() for s in l}
    return list(d.values())
