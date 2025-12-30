import globalPluginHandler
import scriptHandler
import ui
import winUser

VK_MICROPHONE_MUTE = 0xAD


class GlobalPlugin(globalPluginHandler.GlobalPlugin):

    @scriptHandler.script(
        description="Toggle system speaker mute",
        gesture="kb:NVDA+control+shift+m",
        category="AudioToggles"
    )
    def script_toggleSpeakerMute(self, gesture):
        winUser.keybd_event(winUser.VK_VOLUME_MUTE, 0, 0, 0)
        winUser.keybd_event(winUser.VK_VOLUME_MUTE, 0, winUser.KEYEVENTF_KEYUP, 0)
        ui.message("Speaker mute toggled")

    @scriptHandler.script(
        description="Toggle microphone mute",
        gesture="kb:NVDA+control+shift+u",
        category="AudioToggles"
    )
    def script_toggleMicMute(self, gesture):
        winUser.keybd_event(VK_MICROPHONE_MUTE, 0, 0, 0)
        winUser.keybd_event(VK_MICROPHONE_MUTE, 0, winUser.KEYEVENTF_KEYUP, 0)
        ui.message("Microphone mute toggled")
