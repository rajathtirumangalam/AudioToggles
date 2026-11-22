# -*- coding: UTF-8 -*-
# AudioToggles - speaker/microphone mute, device switching, volume, presets and per-app audio.

import functools

import addonHandler
import globalPluginHandler
import globalVars
import gui
import scriptHandler
import wx
from gui.settingsDialogs import NVDASettingsDialog

from . import actions, audio, dialogs, settings, store

addonHandler.initTranslation()

SCRCAT = _("Audio Toggles")


def disableInSecureMode(cls):
	"""Add-ons must not run on the secure desktop (sign-in and UAC screens)."""
	if getattr(globalVars.appArgs, "secure", False):
		return globalPluginHandler.GlobalPlugin
	return cls


def _guard(func):
	"""Report errors by speech instead of silently failing."""
	@functools.wraps(func)
	def wrapper(self, gesture):
		try:
			func(self, gesture)
		except Exception as error:
			actions.report(error)
	return wrapper


def _later(func, *args):
	"""Run func on the GUI thread after the current script finishes, with error reporting."""
	def runner():
		try:
			func(*args)
		except Exception as error:
			actions.report(error)
	wx.CallAfter(runner)


def _show(dialogClass):
	instance = dialogClass._instance
	if instance:
		try:
			instance.Raise()
			return
		except RuntimeError:
			pass  # the wx object is already gone
	gui.mainFrame.prePopup()
	try:
		dialogClass(gui.mainFrame).Show()
	finally:
		gui.mainFrame.postPopup()


@disableInSecureMode
class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = SCRCAT

	def __init__(self):
		super().__init__()
		store.register()
		self._monitor = None
		NVDASettingsDialog.categoryClasses.append(settings.AudioTogglesPanel)
		store.add_listener(self._syncMonitor)
		self._syncMonitor()

	def terminate(self):
		store.remove_listener(self._syncMonitor)
		if self._monitor:
			self._monitor.stop()
			self._monitor = None
		try:
			NVDASettingsDialog.categoryClasses.remove(settings.AudioTogglesPanel)
		except ValueError:
			pass
		super().terminate()

	def _syncMonitor(self):
		c = store.conf()
		wanted = c["monitor"] and (c["announceChanges"] or c["autoSwitch"])
		if wanted and not self._monitor:
			self._monitor = audio.DeviceMonitor(lambda events: wx.CallAfter(actions.on_device_events, events))
			self._monitor.start()
		elif not wanted and self._monitor:
			self._monitor.stop()
			self._monitor = None

	# ------------------------------------------------------------ mute
	@scriptHandler.script(description=_("Toggles speaker mute"), gesture="kb:NVDA+control+shift+m")
	@_guard
	def script_toggleSpeakerMute(self, gesture):
		actions.toggle_mute(audio.RENDER)

	@scriptHandler.script(description=_("Toggles microphone mute"), gesture="kb:NVDA+control+shift+u")
	@_guard
	def script_toggleMicMute(self, gesture):
		actions.toggle_mute(audio.CAPTURE)

	# ------------------------------------------------------------ devices
	@scriptHandler.script(description=_("Switches to the next playback device"), gesture="kb:NVDA+control+shift+o")
	@_guard
	def script_cycleOutput(self, gesture):
		actions.cycle(audio.RENDER)

	@scriptHandler.script(description=_("Switches to the next recording device"), gesture="kb:NVDA+control+shift+i")
	@_guard
	def script_cycleInput(self, gesture):
		actions.cycle(audio.CAPTURE)

	@scriptHandler.script(
		description=_("Speaks the current playback and recording devices"), gesture="kb:NVDA+control+shift+d"
	)
	@_guard
	def script_speakCurrent(self, gesture):
		actions.speak_current()

	@scriptHandler.script(description=_("Opens the audio devices list"), gesture="kb:NVDA+control+shift+l")
	@_guard
	def script_devicesList(self, gesture):
		_later(_show, dialogs.DevicesDialog)

	# ------------------------------------------------------------ volume
	@scriptHandler.script(description=_("Increases the speaker volume"), gesture="kb:NVDA+control+shift+upArrow")
	@_guard
	def script_speakerVolumeUp(self, gesture):
		actions.adjust_volume(audio.RENDER, 1)

	@scriptHandler.script(description=_("Decreases the speaker volume"), gesture="kb:NVDA+control+shift+downArrow")
	@_guard
	def script_speakerVolumeDown(self, gesture):
		actions.adjust_volume(audio.RENDER, -1)

	@scriptHandler.script(description=_("Increases the microphone volume"))
	@_guard
	def script_micVolumeUp(self, gesture):
		actions.adjust_volume(audio.CAPTURE, 1)

	@scriptHandler.script(description=_("Decreases the microphone volume"))
	@_guard
	def script_micVolumeDown(self, gesture):
		actions.adjust_volume(audio.CAPTURE, -1)

	@scriptHandler.script(description=_("Sets the speaker volume to a specific level"))
	@_guard
	def script_setSpeakerVolume(self, gesture):
		_later(actions.prompt_speaker_volume)

	# ------------------------------------------------------------ presets
	@scriptHandler.script(description=_("Applies the next saved preset"), gesture="kb:NVDA+control+shift+p")
	@_guard
	def script_cyclePreset(self, gesture):
		actions.cycle_preset()

	@scriptHandler.script(description=_("Opens the presets manager"))
	@_guard
	def script_presetsManager(self, gesture):
		_later(_show, dialogs.PresetsDialog)

	# ------------------------------------------------------------ per-application audio
	@scriptHandler.script(
		description=_("Toggles mute for the application you are using"), gesture="kb:NVDA+control+shift+a"
	)
	@_guard
	def script_toggleAppMute(self, gesture):
		actions.toggle_app_mute()

	@scriptHandler.script(description=_("Opens the application volumes list"))
	@_guard
	def script_appsList(self, gesture):
		_later(_show, dialogs.AppsDialog)

	# ------------------------------------------------------------ settings
	@scriptHandler.script(description=_("Opens the Audio Toggles settings"))
	@_guard
	def script_openSettings(self, gesture):
		wx.CallAfter(gui.mainFrame.popupSettingsDialog, NVDASettingsDialog, settings.AudioTogglesPanel)
