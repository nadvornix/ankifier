from anki.sync import HttpSyncer
from anki import Collection as aopen
import sys, re

deck = aopen("/home/jirka/Documents/Anki/pokus/collection.anki2")
deckId = deck.decks.id("English")
deck.decks.select(deckId)
basic_model = deck.models.byName('Basic')
basic_model['did'] = deckId
deck.models.save(basic_model)
deck.models.setCurrent(basic_model)
fact = deck.newNote()
fact['Front'] = "ahoooj"
fact['Back'] = "nazdaaaar"
deck.addNote(fact)
deck.save()
deck.close()
