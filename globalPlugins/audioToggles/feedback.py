# -*- coding: UTF-8 -*-
# AudioToggles - spoken/tone feedback with an optional message-language override.

import gettext
import os

import addonHandler
import braille
import speech
import tones
import ui
from logHandler import log
from speech.commands import LangChangeCommand

from . import store

addonHandler.initTranslation()

# (language code, name written in that language)
LANGUAGES = [
	("en", "English"),
	("hi", "हिन्दी"),
	("bn", "বাংলা"),
	("ta", "தமிழ்"),
	("te", "తెలుగు"),
	("mr", "मराठी"),
	("gu", "ગુજરાતી"),
	("kn", "ಕನ್ನಡ"),
	("ml", "മലയാളം"),
	("pa", "ਪੰਜਾਬੀ"),
]

_ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
_LOCALE_DIR = os.path.join(_ADDON_ROOT, "locale")
_cache = {}


def _translation(lang):
	if lang not in _cache:
		try:
			_cache[lang] = gettext.translation("nvda", _LOCALE_DIR, languages=[lang], fallback=True)
		except Exception:
			log.debugWarning("AudioToggles: cannot load language %s" % lang, exc_info=True)
			_cache[lang] = gettext.NullTranslations()
	return _cache[lang]


def L(msgid):
	"""Translate a spoken message, honouring the add-on's own message language setting."""
	lang = store.conf()["messageLanguage"]
	if not lang:
		return _(msgid)
	return _translation(lang).gettext(msgid)


def speak(text, interrupt=True):
	lang = store.conf()["messageLanguage"]
	if interrupt:
		try:
			speech.cancelSpeech()
		except Exception:
			pass
	if lang:
		try:
			speech.speak([LangChangeCommand(lang), text, LangChangeCommand(None)])
			braille.handler.message(text)
			return
		except Exception:
			log.debugWarning("AudioToggles: language-tagged speech failed", exc_info=True)
	ui.message(text)


def toggle(text, hz):
	"""Feedback for mute toggles; honours the speech/tones/both setting."""
	mode = store.conf()["feedback"]
	if mode in (1, 2):
		tones.beep(hz, 120)
	if mode in (0, 2):
		speak(text)
