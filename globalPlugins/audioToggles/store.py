# -*- coding: UTF-8 -*-
# AudioToggles - configuration and preset storage.

import config

from . import audio, logic

SECTION = "audioToggles"

CONFSPEC = {
	"messageLanguage": "string(default='')",
	"feedback": "integer(default=0,min=0,max=2)",  # 0 speech, 1 tones, 2 both
	"muteDelay": "integer(default=700,min=0,max=3000)",
	"volumeStep": "integer(default=5,min=1,max=25)",
	"roleConsole": "boolean(default=True)",
	"roleMultimedia": "boolean(default=True)",
	"roleCommunications": "boolean(default=True)",
	"shortNames": "boolean(default=True)",
	"monitor": "boolean(default=False)",
	"announceChanges": "boolean(default=True)",
	"autoSwitch": "boolean(default=False)",
	"skipOutput": "string_list(default=list())",
	"skipInput": "string_list(default=list())",
	"presets": "string(default='[]')",
}

_listeners = []


def register():
	config.conf.spec[SECTION] = CONFSPEC


def conf():
	return config.conf[SECTION]


def skip_key(flow):
	return "skipOutput" if flow == audio.RENDER else "skipInput"


def roles():
	c = conf()
	chosen = []
	if c["roleConsole"]:
		chosen.append(audio.ROLE_CONSOLE)
	if c["roleMultimedia"]:
		chosen.append(audio.ROLE_MULTIMEDIA)
	if c["roleCommunications"]:
		chosen.append(audio.ROLE_COMMUNICATIONS)
	return tuple(chosen) or (audio.ROLE_CONSOLE, audio.ROLE_MULTIMEDIA, audio.ROLE_COMMUNICATIONS)


def add_listener(callback):
	if callback not in _listeners:
		_listeners.append(callback)


def remove_listener(callback):
	if callback in _listeners:
		_listeners.remove(callback)


def notify():
	for callback in list(_listeners):
		callback()


# ---------------------------------------------------------------- presets

def load_presets():
	return logic.parse_presets(conf()["presets"])


def save_presets(presets):
	conf()["presets"] = logic.dump_presets(presets)


def capture_preset(name):
	"""Snapshot the current default playback and recording devices."""
	output = audio.get_default(audio.RENDER)
	source = audio.get_default(audio.CAPTURE)
	return {
		"name": name,
		"output": output.id if output else "",
		"outputName": output.name if output else "",
		"input": source.id if source else "",
		"inputName": source.name if source else "",
	}


def apply_preset(preset):
	"""Apply the devices of a preset that are currently connected. Returns True if any applied."""
	applied = False
	for flow, key in ((audio.RENDER, "output"), (audio.CAPTURE, "input")):
		device_id = preset.get(key)
		if not device_id:
			continue
		if device_id in [device.id for device in audio.list_devices(flow)]:
			audio.set_default(device_id, roles())
			applied = True
	return applied
