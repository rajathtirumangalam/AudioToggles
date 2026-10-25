import ctypes
import uuid
from ctypes import wintypes

import globalPluginHandler
import scriptHandler
import ui
import winUser
import speech
import wx

from winBindings.user32 import KEYEVENTF

# Windows virtual key for microphone mute
VK_MICROPHONE_MUTE = 0xAD

# Delay before muting so NVDA can finish speaking
MUTE_DELAY = 1000  # milliseconds

# Windows Core Audio constants
CLSCTX_ALL = 0x17
DEVICE_STATE_ACTIVE = 0x1
E_DATA_FLOW_RENDER = 0
E_ROLE_CONSOLE = 0
E_ROLE_MULTIMEDIA = 1
E_ROLE_COMMUNICATIONS = 2
STGM_READ = 0
VT_LPWSTR = 31

CLSID_MMDEVICE_ENUMERATOR = "BCDE0395-E52F-467C-8E3D-C4579291692E"
IID_IMMDEVICE_ENUMERATOR = "A95664D2-9614-4F35-A746-DE8DB63617E6"
CLSID_POLICY_CONFIG = "870AF99C-171D-4F9E-AF0D-E63DF40C2BC9"
IID_POLICY_CONFIG = "F8679F50-850A-41CF-9C72-430F290290C8"

# PKEY_Device_FriendlyName
FRIENDLY_NAME_FMTID = "A45C254E-DF1C-4EFD-8020-67D146A850E0"
FRIENDLY_NAME_PID = 14

ole32 = ctypes.OleDLL("ole32")


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


# PROPVARIANT is 24 bytes on 64-bit Windows and 16 bytes on 32-bit Windows.
class PROPVARIANT_UNION(ctypes.Union):
    _fields_ = [
        ("pwszVal", ctypes.c_wchar_p),
        ("pointer", ctypes.c_void_p),
        ("longlong", ctypes.c_longlong),
        ("decimal_padding", ctypes.c_ubyte * 16),
    ]


class PROPVARIANT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [
        ("vt", wintypes.USHORT),
        ("wReserved1", wintypes.USHORT),
        ("wReserved2", wintypes.USHORT),
        ("wReserved3", wintypes.USHORT),
        ("value", PROPVARIANT_UNION),
    ]


def _check_hr(hr):
    if hr < 0:
        raise OSError("Windows audio API failed (HRESULT 0x%08X)" % (hr & 0xFFFFFFFF))


def _method(obj, index, restype, argtypes):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])
    return fn


def _release(obj):
    if obj:
        try:
            _method(obj, 2, wintypes.ULONG, [])(obj)
        except Exception:
            pass


def _device_id(device):
    id_ptr = ctypes.c_wchar_p()
    _check_hr(_method(device, 5, ctypes.c_long, [ctypes.POINTER(ctypes.c_wchar_p)])(device, ctypes.byref(id_ptr)))
    try:
        return id_ptr.value
    finally:
        if id_ptr:
            ole32.CoTaskMemFree(ctypes.cast(id_ptr, ctypes.c_void_p))


def _device_name(device):
    store = ctypes.c_void_p()
    _check_hr(_method(device, 4, ctypes.c_long, [wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)])(
        device, STGM_READ, ctypes.byref(store)))
    try:
        key = PROPERTYKEY(GUID(FRIENDLY_NAME_FMTID), FRIENDLY_NAME_PID)
        value = PROPVARIANT()
        ctypes.memset(ctypes.byref(value), 0, ctypes.sizeof(value))
        _check_hr(_method(store, 5, ctypes.c_long, [ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT)])(
            store, ctypes.byref(key), ctypes.byref(value)))
        try:
            if value.vt == VT_LPWSTR and value.pwszVal:
                return value.pwszVal
        finally:
            ole32.PropVariantClear(ctypes.byref(value))
    finally:
        _release(store)
    return "Unknown playback device"


def _enumerate_output_devices():
    enumerator = ctypes.c_void_p()
    clsid = GUID(CLSID_MMDEVICE_ENUMERATOR)
    iid = GUID(IID_IMMDEVICE_ENUMERATOR)
    _check_hr(ole32.CoCreateInstance(ctypes.byref(clsid), None, CLSCTX_ALL,
                                    ctypes.byref(iid), ctypes.byref(enumerator)))
    collection = ctypes.c_void_p()
    try:
        # IMMDeviceEnumerator::EnumAudioEndpoints
        _check_hr(_method(enumerator, 3, ctypes.c_long,
                          [ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)])(
            enumerator, E_DATA_FLOW_RENDER, DEVICE_STATE_ACTIVE, ctypes.byref(collection)))
        count = wintypes.UINT()
        _check_hr(_method(collection, 3, ctypes.c_long, [ctypes.POINTER(wintypes.UINT)])(
            collection, ctypes.byref(count)))
        devices = []
        for index in range(count.value):
            device = ctypes.c_void_p()
            _check_hr(_method(collection, 4, ctypes.c_long,
                              [wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)])(
                collection, index, ctypes.byref(device)))
            try:
                devices.append((_device_id(device), _device_name(device)))
            finally:
                _release(device)
        return devices
    finally:
        _release(collection)
        _release(enumerator)


def _get_default_output_id(enumerator):
    device = ctypes.c_void_p()
    _check_hr(_method(enumerator, 4, ctypes.c_long,
                      [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)])(
        enumerator, E_DATA_FLOW_RENDER, E_ROLE_MULTIMEDIA, ctypes.byref(device)))
    try:
        return _device_id(device)
    finally:
        _release(device)


def _set_default_output(device_id):
    policy = ctypes.c_void_p()
    clsid = GUID(CLSID_POLICY_CONFIG)
    iid = GUID(IID_POLICY_CONFIG)
    _check_hr(ole32.CoCreateInstance(ctypes.byref(clsid), None, CLSCTX_ALL,
                                    ctypes.byref(iid), ctypes.byref(policy)))
    try:
        set_default = _method(policy, 13, ctypes.c_long, [ctypes.c_wchar_p, ctypes.c_int])
        # Set all Windows roles so the selected device is the system default for
        # console, multimedia, and communications applications.
        for role in (E_ROLE_CONSOLE, E_ROLE_MULTIMEDIA, E_ROLE_COMMUNICATIONS):
            _check_hr(set_default(policy, device_id, role))
    finally:
        _release(policy)


def _cycle_windows_output():
    # COM initialization is thread-local. S_FALSE means already initialized;
    # RPC_E_CHANGED_MODE means the host has initialized it in another mode.
    hr = ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    initialized_here = hr in (0, 1)
    if hr < 0 and (hr & 0xFFFFFFFF) != 0x80010106:
        _check_hr(hr)
    try:
        devices = _enumerate_output_devices()
        if not devices:
            raise RuntimeError("No active playback devices were found")

        enumerator = ctypes.c_void_p()
        clsid = GUID(CLSID_MMDEVICE_ENUMERATOR)
        iid = GUID(IID_IMMDEVICE_ENUMERATOR)
        _check_hr(ole32.CoCreateInstance(ctypes.byref(clsid), None, CLSCTX_ALL,
                                        ctypes.byref(iid), ctypes.byref(enumerator)))
        try:
            current_id = _get_default_output_id(enumerator)
        finally:
            _release(enumerator)

        current_index = next((i for i, item in enumerate(devices) if item[0] == current_id), -1)
        next_index = (current_index + 1) % len(devices)
        next_id, next_name = devices[next_index]
        if next_id == current_id:
            return "Default output: %s" % next_name
        _set_default_output(next_id)
        return "Default output changed to %s" % next_name
    finally:
        if initialized_here:
            ole32.CoUninitialize()


# Windows virtual key for microphone mute
VK_MICROPHONE_MUTE = 0xAD


class GlobalPlugin(globalPluginHandler.GlobalPlugin):

    def __init__(self):
        super().__init__()
        self.speakerMuted = False
        self.micMuted = False

    def _pressKey(self, vk):
        winUser.keybd_event(vk, 0, 0, 0)
        winUser.keybd_event(vk, 0, KEYEVENTF.KEYUP, 0)

    def _announce(self, text):
        try:
            speech.cancelSpeech()
        except Exception:
            pass
        ui.message(text)

    @scriptHandler.script(
        description="Toggle system speaker mute",
        gesture="kb:NVDA+control+shift+m",
        category="AudioToggles"
    )
    def script_toggleSpeakerMute(self, gesture):
        try:
            if not self.speakerMuted:
                self._announce("Speaker muted")
                def doMute():
                    self._pressKey(winUser.VK_VOLUME_MUTE)
                wx.CallLater(MUTE_DELAY, doMute)
                self.speakerMuted = True
            else:
                self._pressKey(winUser.VK_VOLUME_MUTE)
                self.speakerMuted = False
                def doAnnounce():
                    self._announce("Speaker unmuted")
                wx.CallLater(150, doAnnounce)
        except Exception:
            ui.message("Unable to toggle speaker mute")

    @scriptHandler.script(
        description="Toggle microphone mute",
        gesture="kb:NVDA+control+shift+u",
        category="AudioToggles"
    )
    def script_toggleMicMute(self, gesture):
        try:
            if not self.micMuted:
                self._announce("Microphone muted")
                def doMute():
                    self._pressKey(VK_MICROPHONE_MUTE)
                wx.CallLater(MUTE_DELAY, doMute)
                self.micMuted = True
            else:
                self._pressKey(VK_MICROPHONE_MUTE)
                self.micMuted = False
                def doAnnounce():
                    self._announce("Microphone unmuted")
                wx.CallLater(150, doAnnounce)
        except Exception:
            ui.message("Unable to toggle microphone mute")

    @scriptHandler.script(
        description="Cycle Windows default audio output device",
        gesture="kb:NVDA+control+shift+o",
        category="AudioToggles"
    )
    def script_cycleOutputDevice(self, gesture):
        try:
            message = _cycle_windows_output()
            # A brief delay gives Windows time to apply the new default endpoint.
            wx.CallLater(250, self._announce, message)
        except Exception as error:
            ui.message("Unable to change audio output device: %s" % str(error))
