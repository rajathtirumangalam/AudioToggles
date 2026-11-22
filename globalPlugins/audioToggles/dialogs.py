# -*- coding: UTF-8 -*-
# AudioToggles - dialogs modelled on NVDA's Elements List: type, filter, list, action buttons.

import addonHandler
import wx
from gui import guiHelper
from logHandler import log

from . import actions, audio, logic, store
from .feedback import L, speak

addonHandler.initTranslation()


class _BaseDialog(wx.Dialog):
	_instance = None

	def __init__(self, parent, title):
		super().__init__(parent, title=title)
		type(self)._instance = self
		self.Bind(wx.EVT_CLOSE, self.onClose)

	def Destroy(self):
		if type(self)._instance is self:
			type(self)._instance = None
		return super().Destroy()

	def close(self):
		if self.IsModal():
			self.EndModal(wx.ID_CLOSE)
		else:
			self.Destroy()

	def onClose(self, evt):
		self.close()

	def _finish_layout(self, helper):
		root = wx.BoxSizer(wx.VERTICAL)
		root.Add(helper.sizer, border=guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		root.Fit(self)
		self.SetSizer(root)
		self.SetEscapeId(wx.ID_CLOSE)
		self.CentreOnScreen()

	def _error(self, error):
		actions.report(error)


class DevicesDialog(_BaseDialog):
	"""Choose, mute, or exclude-from-cycling any playback or recording device."""

	def __init__(self, parent):
		super().__init__(parent, _("Audio devices"))
		self.flow = audio.RENDER
		self.rows = []
		helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		self.typeBox = helper.addItem(
			wx.RadioBox(self, label=_("&Device type"), choices=[_("Playback"), _("Recording")])
		)
		self.typeBox.Bind(wx.EVT_RADIOBOX, self.onType)
		self.filterEdit = helper.addLabeledControl(_("&Filter by:"), wx.TextCtrl)
		self.filterEdit.Bind(wx.EVT_TEXT, lambda evt: self.refresh())
		self.list = helper.addItem(
			wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=self.FromDIP(wx.Size(640, 240)))
		)
		self.list.InsertColumn(0, _("Device"), width=self.FromDIP(330))
		self.list.InsertColumn(1, _("Volume"), width=self.FromDIP(80))
		self.list.InsertColumn(2, _("Status"), width=self.FromDIP(200))
		self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.onSetDefault)
		self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda evt: self.updateSkipLabel())
		buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
		self.defaultBtn = buttons.addButton(self, label=_("&Set as default"))
		self.defaultBtn.Bind(wx.EVT_BUTTON, self.onSetDefault)
		self.muteBtn = buttons.addButton(self, label=_("&Mute or unmute"))
		self.muteBtn.Bind(wx.EVT_BUTTON, self.onMute)
		self.skipBtn = buttons.addButton(self, label=_("S&kip when cycling"))
		self.skipBtn.Bind(wx.EVT_BUTTON, self.onSkip)
		closeBtn = buttons.addButton(self, id=wx.ID_CLOSE, label=_("&Close"))
		closeBtn.Bind(wx.EVT_BUTTON, lambda evt: self.close())
		helper.addItem(buttons)
		self._finish_layout(helper)
		self.refresh()
		self.list.SetFocus()

	# -- helpers
	@property
	def skipKey(self):
		return store.skip_key(self.flow)

	def selected(self):
		index = self.list.GetFirstSelected()
		return self.rows[index] if 0 <= index < len(self.rows) else None

	def updateSkipLabel(self):
		device = self.selected()
		skipped = bool(device) and device.id in store.conf()[self.skipKey]
		self.skipBtn.SetLabel(_("&Include when cycling") if skipped else _("S&kip when cycling"))

	def refresh(self, keepId=None):
		if keepId is None:
			current = self.selected()
			keepId = current.id if current else None
		try:
			devices = audio.list_devices(self.flow)
			defaultId = audio.get_default_id(self.flow)
		except Exception:
			log.error("AudioToggles: cannot list devices", exc_info=True)
			devices, defaultId = [], None
		skipped = set(store.conf()[self.skipKey])
		needle = self.filterEdit.GetValue().strip().lower()
		self.rows = [device for device in devices if needle in device.name.lower()]
		self.list.DeleteAllItems()
		selectIndex = None
		for index, device in enumerate(self.rows):
			try:
				volume, muted = audio.get_state(self.flow, device.id)
			except Exception:
				volume, muted = 0, False
			status = []
			if device.id == defaultId:
				status.append(_("Default"))
			if muted:
				status.append(_("Muted"))
			if device.id in skipped:
				status.append(_("Skipped"))
			self.list.InsertItem(index, device.name)
			self.list.SetItem(index, 1, "%d%%" % volume)
			self.list.SetItem(index, 2, ", ".join(status))
			if device.id == keepId:
				selectIndex = index
			elif selectIndex is None and not keepId and device.id == defaultId:
				selectIndex = index
		if selectIndex is None and self.rows:
			selectIndex = 0
		if selectIndex is not None:
			self.list.Select(selectIndex)
			self.list.Focus(selectIndex)
		self.updateSkipLabel()

	# -- events
	def onType(self, evt):
		self.flow = audio.RENDER if self.typeBox.GetSelection() == 0 else audio.CAPTURE
		self.refresh(keepId="")

	def onSetDefault(self, evt):
		device = self.selected()
		if device is None:
			return
		try:
			audio.set_default(device.id, store.roles())
		except Exception as error:
			self._error(error)
			return
		self.refresh(device.id)
		speak(actions.device_message(self.flow).format(name=device.name))

	def onMute(self, evt):
		device = self.selected()
		if device is None:
			return
		try:
			muted = audio.get_state(self.flow, device.id)[1]
			text = "%s, %s" % (device.name, L("unmuted") if muted else L("muted"))
			if not muted and self.flow == audio.RENDER:
				# Announce first: muting the speaker would silence NVDA itself.
				speak(text)
				wx.CallLater(store.conf()["muteDelay"], self._applyMute, device, True)
				return
			audio.set_mute(self.flow, not muted, device.id)
			self.refresh(device.id)
			speak(text)
		except Exception as error:
			self._error(error)

	def _applyMute(self, device, muted):
		try:
			audio.set_mute(self.flow, muted, device.id)
			self.refresh(device.id)
		except Exception as error:
			self._error(error)

	def onSkip(self, evt):
		device = self.selected()
		if device is None:
			return
		ids = list(store.conf()[self.skipKey])
		if device.id in ids:
			ids.remove(device.id)
			message = L("Included when cycling: {name}")
		else:
			ids.append(device.id)
			message = L("Skipped when cycling: {name}")
		store.conf()[self.skipKey] = ids
		self.refresh(device.id)
		speak(message.format(name=device.name))


class AppsDialog(_BaseDialog):
	"""Per-application volume and mute."""

	def __init__(self, parent):
		super().__init__(parent, _("Application volumes"))
		self.entries = []
		helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		self.list = helper.addItem(
			wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=self.FromDIP(wx.Size(520, 240)))
		)
		self.list.InsertColumn(0, _("Application"), width=self.FromDIP(260))
		self.list.InsertColumn(1, _("Volume"), width=self.FromDIP(100))
		self.list.InsertColumn(2, _("Status"), width=self.FromDIP(140))
		buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
		for label, handler in (
			(_("&Mute or unmute"), self.onMute),
			(_("Volume &up"), lambda evt: self.onVolume(1)),
			(_("Volume &down"), lambda evt: self.onVolume(-1)),
			(_("&Refresh"), lambda evt: self.refresh()),
		):
			buttons.addButton(self, label=label).Bind(wx.EVT_BUTTON, handler)
		closeBtn = buttons.addButton(self, id=wx.ID_CLOSE, label=_("&Close"))
		closeBtn.Bind(wx.EVT_BUTTON, lambda evt: self.close())
		helper.addItem(buttons)
		self._finish_layout(helper)
		self.refresh()
		self.list.SetFocus()

	def selected(self):
		index = self.list.GetFirstSelected()
		return self.entries[index] if 0 <= index < len(self.entries) else None

	def refresh(self, keepName=None):
		if keepName is None:
			current = self.selected()
			keepName = current.name if current else None
		try:
			self.entries = audio.list_app_audio()
		except Exception as error:
			self.entries = []
			self._error(error)
		self.list.DeleteAllItems()
		selectIndex = 0
		for index, entry in enumerate(self.entries):
			self.list.InsertItem(index, entry.name)
			self.list.SetItem(index, 1, "%d%%" % entry.volume)
			self.list.SetItem(index, 2, _("Muted") if entry.muted else "")
			if entry.name == keepName:
				selectIndex = index
		if self.entries:
			self.list.Select(selectIndex)
			self.list.Focus(selectIndex)

	def onMute(self, evt):
		entry = self.selected()
		if entry is None:
			return
		try:
			audio.set_app_mute(entry.name, not entry.muted)
		except Exception as error:
			self._error(error)
			return
		self.refresh(entry.name)
		speak((L("{app} unmuted") if entry.muted else L("{app} muted")).format(app=entry.name))

	def onVolume(self, direction):
		entry = self.selected()
		if entry is None:
			return
		value = logic.clamp(entry.volume + direction * store.conf()["volumeStep"], 0, 100)
		try:
			audio.set_app_volume(entry.name, value)
		except Exception as error:
			self._error(error)
			return
		self.refresh(entry.name)
		speak(L("{app} volume {value} percent").format(app=entry.name, value=value))


class PresetsDialog(_BaseDialog):
	"""Save, apply and delete presets (a playback + recording device pair)."""

	def __init__(self, parent):
		super().__init__(parent, _("Presets"))
		self.presets = []
		helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		self.list = helper.addLabeledControl(
			_("Presets"), wx.ListBox, choices=[], size=self.FromDIP(wx.Size(520, 200))
		)
		self.list.Bind(wx.EVT_LISTBOX_DCLICK, self.onApply)
		buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
		buttons.addButton(self, label=_("&Apply")).Bind(wx.EVT_BUTTON, self.onApply)
		buttons.addButton(self, label=_("&Save current devices as preset...")).Bind(wx.EVT_BUTTON, self.onSave)
		buttons.addButton(self, label=_("&Delete")).Bind(wx.EVT_BUTTON, self.onDelete)
		closeBtn = buttons.addButton(self, id=wx.ID_CLOSE, label=_("&Close"))
		closeBtn.Bind(wx.EVT_BUTTON, lambda evt: self.close())
		helper.addItem(buttons)
		self._finish_layout(helper)
		self.refresh()
		self.list.SetFocus()

	def refresh(self, select=0):
		self.presets = store.load_presets()
		self.list.Set([
			"%s (%s / %s)" % (p["name"], p.get("outputName") or "-", p.get("inputName") or "-")
			for p in self.presets
		])
		if self.presets:
			self.list.SetSelection(logic.clamp(select, 0, len(self.presets) - 1))

	def onApply(self, evt):
		index = self.list.GetSelection()
		if index == wx.NOT_FOUND:
			return
		try:
			actions.apply_preset(self.presets[index])
		except Exception as error:
			self._error(error)

	def onSave(self, evt):
		with wx.TextEntryDialog(self, _("Preset name:"), _("Save preset")) as entry:
			if entry.ShowModal() != wx.ID_OK:
				return
			name = entry.GetValue().strip()
		if not name:
			return
		try:
			preset = store.capture_preset(name)
		except Exception as error:
			self._error(error)
			return
		presets = [p for p in store.load_presets() if p["name"] != name]
		presets.append(preset)
		store.save_presets(presets)
		self.refresh(len(presets) - 1)

	def onDelete(self, evt):
		index = self.list.GetSelection()
		if index == wx.NOT_FOUND:
			return
		presets = store.load_presets()
		del presets[index]
		store.save_presets(presets)
		self.refresh(index)
