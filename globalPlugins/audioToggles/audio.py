# -*- coding: UTF-8 -*-
# AudioToggles - Windows Core Audio access using only ctypes.

import ctypes
import os
import threading
import uuid
from collections import namedtuple
from contextlib import contextmanager
from ctypes import wintypes

from logHandler import log

RENDER = 0    # playback
CAPTURE = 1   # recording
ROLE_CONSOLE = 0
ROLE_MULTIMEDIA = 1
ROLE_COMMUNICATIONS = 2

CLSCTX_ALL = 0x17
DEVICE_STATE_ACTIVE = 0x1
STGM_READ = 0
VT_LPWSTR = 31
HRESULT_E_NOTFOUND = 0x80070490
HRESULT_RPC_E_CHANGED_MODE = 0x80010106

CLSID_MMDEVICE_ENUMERATOR = "BCDE0395-E52F-467C-8E3D-C4579291692E"
IID_IMMDEVICE_ENUMERATOR = "A95664D2-9614-4F35-A746-DE8DB63617E6"
CLSID_POLICY_CONFIG = "870AF99C-171D-4F9E-AF0D-E63DF40C2BC9"
IID_POLICY_CONFIG = "F8679F50-850A-41CF-9C72-430F290290C8"
IID_AUDIO_ENDPOINT_VOLUME = "5CDF2C82-841E-4546-9722-0CF74078229A"
IID_AUDIO_SESSION_MANAGER2 = "77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F"
IID_AUDIO_SESSION_CONTROL2 = "BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D"
IID_SIMPLE_AUDIO_VOLUME = "87CE5498-68D6-44E5-9215-6DA47EF883D8"
FRIENDLY_NAME_FMTID = "A45C254E-DF1C-4EFD-8020-67D146A850E0"
FRIENDLY_NAME_PID = 14

Device = namedtuple("Device", "id name flow")
AppAudio = namedtuple("AppAudio", "name volume muted")

ole32 = ctypes.OleDLL("ole32")
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [
	wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class NoDeviceError(OSError):
	"""Raised when there is no active device of the requested kind."""

	def __init__(self, flow):
		super().__init__("No audio device available")
		self.flow = flow


class GUID(ctypes.Structure):
	_fields_ = [
		("Data1", ctypes.c_ulong),
		("Data2", ctypes.c_ushort),
		("Data3", ctypes.c_ushort),
		("Data4", ctypes.c_ubyte * 8),
	]

	def __init__(self, value=None):
		super().__init__()
		if value:
			parsed = uuid.UUID(value)
			self.Data1 = parsed.time_low
			self.Data2 = parsed.time_mid
			self.Data3 = parsed.time_hi_version
			self.Data4[:] = parsed.bytes[8:]


class PROPERTYKEY(ctypes.Structure):
	_fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class _PVData(ctypes.Union):
	_fields_ = [("pwszVal", ctypes.c_wchar_p), ("padding", ctypes.c_byte * 16)]


class PROPVARIANT(ctypes.Structure):
	_anonymous_ = ("data",)
	_fields_ = [
		("vt", ctypes.c_ushort),
		("r1", ctypes.c_ushort),
		("r2", ctypes.c_ushort),
		("r3", ctypes.c_ushort),
		("data", _PVData),
	]


def _method(obj, index, restype, argtypes):
	"""Fetch a COM vtable method by index."""
	vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
	prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
	return prototype(vtable[index])


def _check_hr(hr, flow=None):
	if hr >= 0:
		return
	if flow is not None and (hr & 0xFFFFFFFF) == HRESULT_E_NOTFOUND:
		raise NoDeviceError(flow)
	raise OSError("COM call failed, HRESULT 0x%08X" % (hr & 0xFFFFFFFF))


def _invoke(obj, index, argtypes, *args, **kwargs):
	hr = _method(obj, index, ctypes.c_long, argtypes)(obj, *args)
	_check_hr(hr, kwargs.get("flow"))
	return hr


def _release(obj):
	if obj and obj.value:
		_method(obj, 2, ctypes.c_ulong, [])(obj)


@contextmanager
def com_apartment(multithreaded=False):
	initialized = False
	try:
		ole32.CoInitializeEx(None, 0x0 if multithreaded else 0x2)
		initialized = True
	except OSError as error:
		code = (getattr(error, "winerror", 0) or 0) & 0xFFFFFFFF
		if code != HRESULT_RPC_E_CHANGED_MODE:
			raise
	try:
		yield
	finally:
		if initialized:
			ole32.CoUninitialize()


def _create_enumerator():
	enumerator = ctypes.c_void_p()
	clsid = GUID(CLSID_MMDEVICE_ENUMERATOR)
	iid = GUID(IID_IMMDEVICE_ENUMERATOR)
	ole32.CoCreateInstance(
		ctypes.byref(clsid), None, CLSCTX_ALL, ctypes.byref(iid), ctypes.byref(enumerator)
	)
	return enumerator


def _device_id(device):
	pointer = ctypes.c_wchar_p()
	_invoke(device, 5, [ctypes.POINTER(ctypes.c_wchar_p)], ctypes.byref(pointer))
	try:
		return pointer.value
	finally:
		ole32.CoTaskMemFree(ctypes.cast(pointer, ctypes.c_void_p))


def _device_name(device):
	store = ctypes.c_void_p()
	_invoke(device, 4, [wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)], STGM_READ, ctypes.byref(store))
	try:
		key = PROPERTYKEY()
		key.fmtid = GUID(FRIENDLY_NAME_FMTID)
		key.pid = FRIENDLY_NAME_PID
		value = PROPVARIANT()
		_invoke(
			store, 5, [ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT)],
			ctypes.byref(key), ctypes.byref(value),
		)
		try:
			if value.vt == VT_LPWSTR and value.pwszVal:
				return value.pwszVal
			return "Unknown device"
		finally:
			ole32.PropVariantClear(ctypes.byref(value))
	finally:
		_release(store)


@contextmanager
def _device(device_id=None, flow=RENDER, role=ROLE_MULTIMEDIA):
	enumerator = _create_enumerator()
	device = ctypes.c_void_p()
	try:
		if device_id:
			_invoke(
				enumerator, 5, [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)],
				device_id, ctypes.byref(device), flow=flow,
			)
		else:
			_invoke(
				enumerator, 4, [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)],
				flow, role, ctypes.byref(device), flow=flow,
			)
		yield device
	finally:
		_release(device)
		_release(enumerator)


def list_devices(flow):
	"""Active devices of the given flow."""
	with com_apartment():
		enumerator = _create_enumerator()
		collection = ctypes.c_void_p()
		try:
			_invoke(
				enumerator, 3, [ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)],
				flow, DEVICE_STATE_ACTIVE, ctypes.byref(collection),
			)
			count = wintypes.UINT()
			_invoke(collection, 3, [ctypes.POINTER(wintypes.UINT)], ctypes.byref(count))
			result = []
			for index in range(count.value):
				device = ctypes.c_void_p()
				_invoke(
					collection, 4, [wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)],
					index, ctypes.byref(device),
				)
				try:
					result.append(Device(_device_id(device), _device_name(device), flow))
				finally:
					_release(device)
			return result
		finally:
			_release(collection)
			_release(enumerator)


def get_default(flow, role=ROLE_MULTIMEDIA):
	"""The default device for a flow, or None."""
	try:
		with com_apartment(), _device(flow=flow, role=role) as device:
			return Device(_device_id(device), _device_name(device), flow)
	except NoDeviceError:
		return None


def get_default_id(flow, role=ROLE_MULTIMEDIA):
	device = get_default(flow, role)
	return device.id if device else None


def set_default(device_id, roles=(ROLE_CONSOLE, ROLE_MULTIMEDIA, ROLE_COMMUNICATIONS)):
	"""Make a device the default for the given Windows roles (undocumented IPolicyConfig)."""
	with com_apartment():
		policy = ctypes.c_void_p()
		clsid = GUID(CLSID_POLICY_CONFIG)
		iid = GUID(IID_POLICY_CONFIG)
		ole32.CoCreateInstance(
			ctypes.byref(clsid), None, CLSCTX_ALL, ctypes.byref(iid), ctypes.byref(policy)
		)
		try:
			for role in roles:
				_invoke(policy, 13, [ctypes.c_wchar_p, ctypes.c_int], device_id, role)
		finally:
			_release(policy)


@contextmanager
def _endpoint(flow, device_id=None):
	with _device(device_id=device_id, flow=flow) as device:
		endpoint = ctypes.c_void_p()
		iid = GUID(IID_AUDIO_ENDPOINT_VOLUME)
		_invoke(
			device, 3,
			[ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
			ctypes.byref(iid), CLSCTX_ALL, None, ctypes.byref(endpoint),
		)
		try:
			yield endpoint
		finally:
			_release(endpoint)


def get_state(flow, device_id=None):
	"""Return (volume percent, muted) for the default or a specific device."""
	with com_apartment(), _endpoint(flow, device_id) as endpoint:
		volume = ctypes.c_float()
		muted = wintypes.BOOL()
		_invoke(endpoint, 9, [ctypes.POINTER(ctypes.c_float)], ctypes.byref(volume))
		_invoke(endpoint, 15, [ctypes.POINTER(wintypes.BOOL)], ctypes.byref(muted))
		return int(round(volume.value * 100)), bool(muted.value)


def set_mute(flow, muted, device_id=None):
	with com_apartment(), _endpoint(flow, device_id) as endpoint:
		_invoke(endpoint, 14, [wintypes.BOOL, ctypes.POINTER(GUID)], bool(muted), None)


def set_volume(flow, percent, device_id=None):
	percent = max(0, min(100, int(percent)))
	with com_apartment(), _endpoint(flow, device_id) as endpoint:
		_invoke(endpoint, 7, [ctypes.c_float, ctypes.POINTER(GUID)], percent / 100.0, None)
	return percent


def adjust_volume(flow, delta, device_id=None):
	"""Change volume by delta percent; returns the new percent."""
	current = get_state(flow, device_id)[0]
	return set_volume(flow, current + delta, device_id)


# ---------------------------------------------------------------- per-application audio

def _process_stem(pid):
	handle = _kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
	if not handle:
		return None
	try:
		size = wintypes.DWORD(1024)
		buffer = ctypes.create_unicode_buffer(1024)
		if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
			return os.path.splitext(os.path.basename(buffer.value))[0].lower()
		return None
	finally:
		_kernel32.CloseHandle(handle)


def _open_session(enumerator, index):
	control = ctypes.c_void_p()
	_invoke(enumerator, 4, [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)], index, ctypes.byref(control))
	control2 = ctypes.c_void_p()
	simple = ctypes.c_void_p()
	try:
		iid2 = GUID(IID_AUDIO_SESSION_CONTROL2)
		iid_simple = GUID(IID_SIMPLE_AUDIO_VOLUME)
		query = [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
		_invoke(control, 0, query, ctypes.byref(iid2), ctypes.byref(control2))
		_invoke(control, 0, query, ctypes.byref(iid_simple), ctypes.byref(simple))
		pid = wintypes.DWORD()
		_invoke(control2, 14, [ctypes.POINTER(wintypes.DWORD)], ctypes.byref(pid))
		return (control2, simple, pid.value)
	except Exception:
		_release(control2)
		_release(simple)
		return None
	finally:
		_release(control)


@contextmanager
def _app_groups():
	"""Yield {process name: [ISimpleAudioVolume pointers]} for the default playback device."""
	items = []
	with _device(flow=RENDER) as device:
		manager = ctypes.c_void_p()
		iid = GUID(IID_AUDIO_SESSION_MANAGER2)
		_invoke(
			device, 3,
			[ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
			ctypes.byref(iid), CLSCTX_ALL, None, ctypes.byref(manager),
		)
		enumerator = ctypes.c_void_p()
		try:
			_invoke(manager, 5, [ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(enumerator))
			count = ctypes.c_int()
			_invoke(enumerator, 3, [ctypes.POINTER(ctypes.c_int)], ctypes.byref(count))
			for index in range(count.value):
				item = _open_session(enumerator, index)
				if item:
					items.append(item)
			groups = {}
			for _control2, simple, pid in items:
				if not pid or pid == os.getpid():
					continue
				stem = _process_stem(pid)
				if not stem or stem == "nvda":
					continue  # never offer to mute the screen reader itself
				groups.setdefault(stem, []).append(simple)
			yield groups
		finally:
			for control2, simple, _pid in items:
				_release(control2)
				_release(simple)
			_release(enumerator)
			_release(manager)


def _simple_state(simple):
	volume = ctypes.c_float()
	muted = wintypes.BOOL()
	_invoke(simple, 4, [ctypes.POINTER(ctypes.c_float)], ctypes.byref(volume))
	_invoke(simple, 6, [ctypes.POINTER(wintypes.BOOL)], ctypes.byref(muted))
	return volume.value, bool(muted.value)


def list_app_audio():
	"""Applications with audio sessions on the default playback device."""
	with com_apartment(), _app_groups() as groups:
		result = []
		for name in sorted(groups):
			volumes, mutes = [], []
			for simple in groups[name]:
				try:
					volume, muted = _simple_state(simple)
				except OSError:
					continue
				volumes.append(volume)
				mutes.append(muted)
			if volumes:
				result.append(AppAudio(name, int(round(max(volumes) * 100)), all(mutes)))
		return result


def set_app_mute(name, muted):
	"""Mute or unmute every session of an application. Returns the number changed."""
	changed = 0
	with com_apartment(), _app_groups() as groups:
		for simple in groups.get(name, []):
			_invoke(simple, 5, [wintypes.BOOL, ctypes.POINTER(GUID)], bool(muted), None)
			changed += 1
	return changed


def set_app_volume(name, percent):
	percent = max(0, min(100, int(percent)))
	changed = 0
	with com_apartment(), _app_groups() as groups:
		for simple in groups.get(name, []):
			_invoke(simple, 3, [ctypes.c_float, ctypes.POINTER(GUID)], percent / 100.0, None)
			changed += 1
	return changed


# ---------------------------------------------------------------- device monitoring

def snapshot():
	"""{(flow, id): name} for every active device."""
	result = {}
	for flow in (RENDER, CAPTURE):
		for device in list_devices(flow):
			result[(flow, device.id)] = device.name
	return result


class DeviceMonitor(threading.Thread):
	"""Polls for device arrival/removal and reports events through a callback."""

	def __init__(self, callback, interval=3.0):
		super().__init__(name="AudioTogglesMonitor")
		self.daemon = True
		self._callback = callback
		self._interval = interval
		self._stopEvent = threading.Event()

	def stop(self):
		self._stopEvent.set()

	def run(self):
		from . import logic
		try:
			with com_apartment(multithreaded=True):
				known = snapshot()
				while not self._stopEvent.wait(self._interval):
					try:
						current = snapshot()
					except Exception:
						log.debugWarning("AudioToggles: device snapshot failed", exc_info=True)
						continue
					events = logic.diff_snapshots(known, current)
					known = current
					if events:
						self._callback(events)
		except Exception:
			log.error("AudioToggles: device monitor stopped", exc_info=True)
