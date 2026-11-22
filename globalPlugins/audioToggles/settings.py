# -*- coding: UTF-8 -*-
# AudioToggles - NVDA settings panel.

import addonHandler
import wx
from gui import guiHelper, nvdaControls
from gui.settingsDialogs import SettingsPanel
from logHandler import log

from . import audio, feedback, store

addonHandler.initTranslation()


def _skip_list(helper, label, flow):
	"""A check list of devices; checked devices are skipped when cycling."""
	try:
		devices = audio.list_devices(flow)
	except Exception:
		log.debugWarning("AudioToggles: cannot list devices for settings", exc_info=True)
		return None, None
	skipped = set(store.conf()[store.skip_key(flow)])
	control = helper.addLabeledControl(label, wx.CheckListBox, choices=[device.name for device in devices])
	control.SetCheckedItems([i for i, device in enumerate(devices) if device.id in skipped])
	return control, devices


class AudioTogglesPanel(SettingsPanel):
	title = _("Audio Toggles")

	def makeSettings(self, settingsSizer):
		c = store.conf()
		helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		self._langCodes = [""] + [code for code, _name in feedback.LANGUAGES]
		langNames = [_("Follow NVDA language")] + [name for _code, name in feedback.LANGUAGES]
		self.langChoice = helper.addLabeledControl(
			_("&Language of spoken messages:"), wx.Choice, choices=langNames
		)
		current = c["messageLanguage"]
		self.langChoice.SetSelection(self._langCodes.index(current) if current in self._langCodes else 0)

		self.feedbackChoice = helper.addLabeledControl(
			_("&Feedback type:"), wx.Choice, choices=[_("Speech"), _("Tones"), _("Speech and tones")]
		)
		self.feedbackChoice.SetSelection(c["feedback"])

		self.delaySpin = helper.addLabeledControl(
			_("&Delay before muting the speaker (milliseconds):"),
			nvdaControls.SelectOnFocusSpinCtrl, min=0, max=3000, initial=c["muteDelay"],
		)
		self.stepSpin = helper.addLabeledControl(
			_("Volume &step (percent):"), nvdaControls.SelectOnFocusSpinCtrl, min=1, max=25, initial=c["volumeStep"],
		)

		self.consoleCheck = helper.addItem(wx.CheckBox(self, label=_("Set as default for the &console role")))
		self.consoleCheck.SetValue(c["roleConsole"])
		self.multimediaCheck = helper.addItem(wx.CheckBox(self, label=_("Set as default for the &multimedia role")))
		self.multimediaCheck.SetValue(c["roleMultimedia"])
		self.commsCheck = helper.addItem(wx.CheckBox(self, label=_("Set as default for the c&ommunications role")))
		self.commsCheck.SetValue(c["roleCommunications"])

		self.shortCheck = helper.addItem(wx.CheckBox(self, label=_("Use s&hort device names")))
		self.shortCheck.SetValue(c["shortNames"])
		self.monitorCheck = helper.addItem(wx.CheckBox(self, label=_("Monitor d&evice changes")))
		self.monitorCheck.SetValue(c["monitor"])
		self.announceCheck = helper.addItem(
			wx.CheckBox(self, label=_("A&nnounce devices when they connect or disconnect"))
		)
		self.announceCheck.SetValue(c["announceChanges"])
		self.autoSwitchCheck = helper.addItem(
			wx.CheckBox(self, label=_("S&witch to a playback device when it connects"))
		)
		self.autoSwitchCheck.SetValue(c["autoSwitch"])

		self.outList, self._outDevices = _skip_list(helper, _("Playback devices to s&kip when cycling:"), audio.RENDER)
		self.inList, self._inDevices = _skip_list(helper, _("&Recording devices to skip when cycling:"), audio.CAPTURE)

		presetsButton = helper.addItem(wx.Button(self, label=_("Manage &presets...")))
		presetsButton.Bind(wx.EVT_BUTTON, self.onPresets)

	def onPresets(self, evt):
		from .dialogs import PresetsDialog
		dialog = PresetsDialog(self)
		try:
			dialog.ShowModal()
		finally:
			dialog.Destroy()

	@staticmethod
	def _merge_skips(control, devices, old_ids):
		"""Checked devices, plus previously skipped devices that are simply not connected now."""
		connected = set(device.id for device in devices)
		checked = [devices[i].id for i in control.GetCheckedItems()]
		return checked + [device_id for device_id in old_ids if device_id not in connected]

	def onSave(self):
		c = store.conf()
		c["messageLanguage"] = self._langCodes[self.langChoice.GetSelection()]
		c["feedback"] = self.feedbackChoice.GetSelection()
		c["muteDelay"] = self.delaySpin.GetValue()
		c["volumeStep"] = self.stepSpin.GetValue()
		c["roleConsole"] = self.consoleCheck.GetValue()
		c["roleMultimedia"] = self.multimediaCheck.GetValue()
		c["roleCommunications"] = self.commsCheck.GetValue()
		c["shortNames"] = self.shortCheck.GetValue()
		c["monitor"] = self.monitorCheck.GetValue()
		c["announceChanges"] = self.announceCheck.GetValue()
		c["autoSwitch"] = self.autoSwitchCheck.GetValue()
		if self.outList is not None:
			c["skipOutput"] = self._merge_skips(self.outList, self._outDevices, c["skipOutput"])
		if self.inList is not None:
			c["skipInput"] = self._merge_skips(self.inList, self._inDevices, c["skipInput"])
		store.notify()
