import errno
import struct
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pi_endpoint import aoa, duml
from pi_endpoint import camera_control
from pi_endpoint.endpoint import Session, VideoOutput
from pi_endpoint.video import VideoDeframer


class FakeGadget:
    def __init__(self, fail_second_enable=False):
        self.disabled = []
        self.enabled = 0
        self.fail_second_enable = fail_second_enable
        self.write_calls = 0

    def ep_disable(self, endpoint):
        self.disabled.append(endpoint)

    def vbus_draw(self, _milliamps):
        pass

    def configure(self):
        pass

    def ep_enable(self, _address, max_packet=512):
        self.enabled += 1
        if self.fail_second_enable and self.enabled >= 2:
            raise OSError(16, "Device or resource busy")
        return self.enabled + 9

    def ep_write(self, _endpoint, _data):
        self.write_calls += 1
        raise OSError(errno.EAGAIN, "Resource temporarily unavailable")


class EndpointProtocolTest(unittest.TestCase):
    def test_duml_round_trip(self):
        packet = duml.build(2, 28, 0x1234, 0, 0x81, b"APP")
        parsed = duml.parse(packet)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["seq"], 0x1234)
        self.assertEqual(parsed["payload"], b"APP")

    def test_identity_reply_is_aoa_wrapped(self):
        request = duml.build(28, 2, 7, 0, 0x82)
        reply = aoa.identity_reply(request)
        self.assertIsNotNone(reply)
        self.assertEqual(duml.parse(reply)["packet_type"], 1)
        stream = bytearray(aoa.wrap(reply))
        self.assertEqual(list(aoa.unwrap(stream)), [reply])

    def test_video_frame_split_and_resync(self):
        payload = b"\x00\x00\x00\x01\x67\x42\x00\x1f"
        frame = b"garbage" + b"\x55\xcc\x4a\x57" + struct.pack("<I", len(payload)) + payload
        parser = VideoDeframer()
        self.assertEqual(parser.feed(frame[:5]), [])
        self.assertEqual(parser.feed(frame[5:]), [payload])
        self.assertEqual(parser.stats()["chunks"], 1)

    def test_camera_commands_use_app_to_camera_duml(self):
        self.assertEqual(camera_control.known_payload("record", "start"), b"\x01")
        self.assertEqual(camera_control.known_payload("record", "stop"), b"\x00")
        self.assertEqual(camera_control.known_payload("mode", "video"), b"\x01")
        self.assertEqual(camera_control.known_payload("set_iso", "25600"), b"\x0b")
        self.assertEqual(camera_control.known_payload("set_shutter", "1/50"), bytes.fromhex("01328000000040"))
        self.assertEqual(camera_control.known_payload("set_white_balance", "5600"), bytes.fromhex("0638001400"))
        self.assertEqual(camera_control.known_payload("set_exposure_compensation", "-1.3"), b"\x0c")
        self.assertEqual(camera_control.known_payload("set_video_format", {"aspect": "4:3", "resolution": "1440x1080", "fps": 60}), bytes.fromhex("0c06000000"))
        packet = camera_control.build_command(
            seq=0x4321, name="photo", payload=camera_control.known_payload("photo"))
        parsed = duml.parse(packet)
        self.assertEqual(parsed["sender_type"], camera_control.APP_TYPE)
        self.assertEqual(parsed["receiver_type"], camera_control.CAMERA_TYPE)
        self.assertEqual((parsed["cmd_set"], parsed["cmd_id"]), (0x02, 0x01))
        self.assertEqual(parsed["payload"], b"\x01")

    def test_reset_disables_raw_gadget_endpoints(self):
        gadget = FakeGadget()
        session = Session(gadget, VideoOutput(None, None), verbose=False)
        session.configured = True
        session.ep_out, session.ep_in = 10, 11
        session.reset("normal")
        self.assertEqual(gadget.disabled, [10, 11])

    def test_partial_configuration_disables_first_endpoint(self):
        gadget = FakeGadget(fail_second_enable=True)
        session = Session(gadget, VideoOutput(None, None), verbose=False)
        session.set_configuration(1)
        self.assertFalse(session.configured)
        self.assertEqual(gadget.disabled, [10])

    def test_bulk_in_stops_on_disconnect_error_without_retry_storm(self):
        gadget = FakeGadget()
        session = Session(gadget, VideoOutput(None, None), verbose=False)
        session.configured = True
        session.ep_in = 11
        self.assertFalse(session.send_bulk_in(b"packet"))
        self.assertFalse(session.configured)
        self.assertLessEqual(gadget.write_calls, 4)
        session.close()

    def test_resync_waits_for_parameter_sets_across_chunks(self):
        output = VideoOutput(None, None)
        output.decoder_reset.clear()
        output.wait_sps = True
        output.push(b"\x41" * 32)
        self.assertTrue(output.wait_sps)
        output.push(b"\x00\x00")
        output.push(b"\x00\x01\x67\x42\x00\x1f")
        self.assertFalse(output.wait_sps)
        output.close()

    def test_video_watchdog_clears_stale_hdmi_stream(self):
        gadget = FakeGadget()
        session = Session(gadget, VideoOutput(None, None), verbose=False)
        session.configured = True
        session.video_started = True
        session.video_last_monotonic = time.monotonic() - session.VIDEO_IDLE_TIMEOUT - 0.1
        self.assertTrue(session._stop_stale_video())
        self.assertFalse(session.video_started)
        self.assertIsNone(session.video_last_monotonic)
        self.assertEqual(session.video_idle_stops, 1)
        session.close()


if __name__ == "__main__":
    unittest.main()
