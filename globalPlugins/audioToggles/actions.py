# -*- coding: UTF-8 -*-
# AudioToggles - actions used by gesture scripts and dialogs.

import addonHandler
import api
import gui
import wx
from logHandler import log

from . import audio, feedback, logic, store
from .feedback import L, speak

addonHandler.initTranslation()

_muteTimers = {}
_presetIndex = [-1]


def report(error):
	"""Speak a friendly message for an error. Call from inside an except block."""
	if isinstance(error, audio.NoDeviceError):
		speak(L("No playback devices found") if error.flow == audio.RENDER else L("No recording devices found"))
		return
	log.error("AudioToggles error", exc_info=True)
	speak(L("Unable to complete the action: {error}").format(error=error))


def display_names(devices):
	names = [device.name for device in devices]
	return logic.shorten_names(names) if store.conf()["shortNames"] else names


def short(name):
	return logic.shorten_names([name])[0] if store.conf()["shortNames"] else name


def device_message(flow):
	return L("Playback device: {name}") if flow == audio.RENDER else L("Recording device: {name}")


# ---------------------------------------------------------------- device switching

def cycle(flow):
	devices = audio.list_devices(flow)
	if not devices:
		raise audio.NoDeviceError(flow)
	skipped = set(store.conf()[store.skip_key(flow)])
	current = audio.get_default(flow)
	current_id = current.id if current else None
	target = logic.next_device(devices, current_id, skipped)
	if target is None:
		speak(L("Every device is set to be skipped when cycling"))
		return
	if target.id == current_id:
		speak(L("Only one device is available"))
		return
	audio.set_default(target.id, store.roles())
	name = display_names(devices)[devices.index(target)]
	wx.CallLater(250, speak, device_message(flow).format(name=name))


def speak_current():
	parts = []
	for flow in (audio.RENDER, audio.CAPTURE):
		device = audio.get_default(flow)
		if device is None:
			parts.append(L("No playback devices found") if flow == audio.RENDER else L("No recording devices found"))
			continue
		volume, muted = audio.get_state(flow, device.id)
		template = (
			L("Playback: {name}, {volume} percent, {state}.") if flow == audio.RENDER
			else L("Recording: {name}, {volume} percent, {state}.")
		)
		parts.append(template.format(
			name=short(device.name), volume=volume, state=L("muted") if muted else L("unmuted"),
		))
	speak(" ".join(parts))


# ---------------------------------------------------------------- mute and volume

def _mute_delay():
	c = store.conf()
	return 250 if c["feedback"] == 1 else c["muteDelay"]


def _apply_mute(flow):
	_muteTimers.pop(flow, None)
	try:
		audio.set_mute(flow, True)
	except Exception as error:
		report(error)


def toggle_mute(flow):
	speaker = flow == audio.RENDER
	timer = _muteTimers.pop(flow, None)
	if timer is not None and timer.IsRunning():
		# A mute is still pending (waiting for speech to finish): cancel it.
		timer.Stop()
		feedback.toggle(L("Speaker unmuted") if speaker else L("Microphone unmuted"), 880 if speaker else 659)
		return
	muted = audio.get_state(flow)[1]
	if not muted:
		feedback.toggle(L("Speaker muted") if speaker else L("Microphone muted"), 330 if speaker else 262)
		# Only muting the speaker silences NVDA, so only then wait for the announcement to finish.
		delay = _mute_delay() if speaker else 0
		if delay:
			_muteTimers[flow] = wx.CallLater(delay, _apply_mute, flow)
		else:
			_apply_mute(flow)
	else:
		audio.set_mute(flow, False)
		if speaker:
			wx.CallLater(150, feedback.toggle, L("Speaker unmuted"), 880)
		else:
			feedback.toggle(L("Microphone unmuted"), 659)


def adjust_volume(flow, direction):
	value = audio.adjust_volume(flow, direction * store.conf()["volumeStep"])
	template = L("Speaker volume {value} percent") if flow == audio.RENDER else L("Microphone volume {value} percent")
	speak(template.format(value=value))


def prompt_speaker_volume():
	current = audio.get_state(audio.RENDER)[0]
	gui.mainFrame.prePopup()
	try:
		value = wx.GetNumberFromUser(L("Volume (percent):"), "", L("Set speaker volume"), current, 0, 100, gui.mainFrame)
	finally:
		gui.mainFrame.postPopup()
	if value >= 0:
		audio.set_volume(audio.RENDER, value)
		speak(L("Speaker volume {value} percent").format(value=value))


# ---------------------------------------------------------------- per-application audio

def toggle_app_mute():
	focus = api.getFocusObject()
	app_name = (getattr(getattr(focus, "appModule", None), "appName", "") or "").lower()
	entry = next((item for item in audio.list_app_audio() if item.name == app_name), None)
	if entry is None:
		speak(L("No audio session found for this application"))
		return
	audio.set_app_mute(entry.name, not entry.muted)
	speak((L("{app} unmuted") if entry.muted else L("{app} muted")).format(app=entry.name))


# ---------------------------------------------------------------- presets

def apply_preset(preset):
	if store.apply_preset(preset):
		wx.CallLater(250, speak, L("Preset applied: {name}").format(name=preset["name"]))
	else:
		speak(L("None of the devices in this preset are connected"))


def cycle_preset():
	presets = store.load_presets()
	if not presets:
		speak(L("No preset has been saved"))
		return
	_presetIndex[0] = (_presetIndex[0] + 1) % len(presets)
	apply_preset(presets[_presetIndex[0]])


# ---------------------------------------------------------------- device monitor events

def on_device_events(events):
	"""Runs on the main thread with events from the monitor thread."""
	c = store.conf()
	for kind, flow, device_id, name in events:
		try:
			if c["announceChanges"]:
				template = L("Device connected: {name}") if kind == "added" else L("Device disconnected: {name}")
				speak(template.format(name=short(name)), interrupt=False)
			if kind == "added" and flow == audio.RENDER and c["autoSwitch"]:
				audio.set_default(device_id, store.roles())
				speak(device_message(flow).format(name=short(name)), interrupt=False)
		except Exception as error:
			report(error)
