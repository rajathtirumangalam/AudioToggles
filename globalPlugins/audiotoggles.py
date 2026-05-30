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


class GlobalPlugin(globalPluginHandler.GlobalPlugin):

    def __init__(self):
        super().__init__()

        # Internal state tracking
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
                # Speak first, mute afterwards
                self._announce("Speaker muted")

                def doMute():
                    self._pressKey(winUser.VK_VOLUME_MUTE)

                wx.CallLater(MUTE_DELAY, doMute)

                self.speakerMuted = True

            else:
                # Unmute immediately
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
                # Speak first, mute afterwards
                self._announce("Microphone muted")

                def doMute():
                    self._pressKey(VK_MICROPHONE_MUTE)

                wx.CallLater(MUTE_DELAY, doMute)

                self.micMuted = True

            else:
                # Unmute immediately
                self._pressKey(VK_MICROPHONE_MUTE)
                self.micMuted = False

                def doAnnounce():
                    self._announce("Microphone unmuted")

                wx.CallLater(150, doAnnounce)

        except Exception:
            ui.message("Unable to toggle microphone mute")