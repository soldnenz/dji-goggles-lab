import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol import (
    BOOST_KBPS,
    HANDSHAKE_TEMPLATE,
    TYPE_ACK,
    TYPE_CMD,
    TYPE_HANDSHAKE,
    TYPE_VIDEO,
    FrameAssembler,
    LossWindow,
    build_ack,
    build_bitrate_boost,
    build_handshake,
    build_type5,
    handshake_seed,
    parse_data,
    parse_duml,
    parse_header,
    parse_video,
    xor7,
)


class ProtocolTest(unittest.TestCase):
    def test_template_checksum_and_length(self):
        header = parse_header(HANDSHAKE_TEMPLATE)
        self.assertIsNotNone(header)
        self.assertEqual(header["type"], TYPE_HANDSHAKE)
        self.assertEqual(header["length"], 48)
        self.assertEqual(header["session"], 0xDD3A)
        self.assertEqual(HANDSHAKE_TEMPLATE[7], xor7(HANDSHAKE_TEMPLATE))

    def test_build_handshake_matches_template_for_same_session(self):
        self.assertEqual(build_handshake(0xDD3A), HANDSHAKE_TEMPLATE)

    def test_build_handshake_patches_session_and_xor(self):
        packet = build_handshake(0xA55A)
        header = parse_header(packet)
        self.assertEqual(header["session"], 0xA55A)
        self.assertEqual(packet[8:], HANDSHAKE_TEMPLATE[8:])
        self.assertEqual(handshake_seed(packet), 0xE9D0)

    def test_rejects_bad_xor(self):
        bad = bytearray(HANDSHAKE_TEMPLATE)
        bad[7] ^= 0xFF
        self.assertIsNone(parse_header(bytes(bad)))

    def test_ack_window_and_checksum(self):
        ack = build_ack(0xDD3A, 0xEA08, 0xEA08)
        header = parse_header(ack)
        self.assertEqual(header["type"], TYPE_ACK)
        self.assertEqual(header["session"], 0xDD3A)
        self.assertEqual(struct.unpack_from("<HH", ack, 8), (0xEA08, 0xEA08))
        self.assertEqual(struct.unpack_from("<H", ack, 12)[0], 0)
        self.assertEqual(struct.unpack_from("<HH", ack, 14), (0xEA08, 0xEA08))
        self.assertEqual(struct.unpack_from("<HH", ack, 20), (0xEA08, 0xEA08))

    def test_ack_resend_list_grows(self):
        ack = build_ack(1, 8, 24, resend=(16, 24))
        self.assertEqual(struct.unpack_from("<H", ack, 12)[0], 2)
        self.assertEqual(struct.unpack_from("<HH", ack, 14), (16, 24))
        self.assertEqual(parse_header(ack)["length"], len(ack))

    def test_type1_windows_from_goggles(self):
        packet = bytes.fromhex(
            "22800d69000001c7d0e9d0e900000000d0e9d0e900000000d0e9d0e9000000000000"
        )
        data = parse_data(packet)
        self.assertIsNotNone(data)
        self.assertEqual(data["window_start"], 0xE9D0)
        self.assertEqual(data["window_end"], 0xE9D0)
        self.assertEqual(data["session"], 0x690D)

    def test_type1_duml_serial(self):
        packet = bytes.fromhex(
            "4e800d69000001ab"
            "d0e9d0e900000000d0e9d0e900000000d0e9d0e900000000"
            "2c00"
            "552c04361b027100000794012b2302000300"
            "373533584d335037303232503442"
            "0000000000000000000040cf"
        )
        data = parse_data(packet)
        self.assertIsNotNone(data)
        self.assertEqual(data["serial"], "753XM3P7022P4B")
        self.assertEqual(data["duml"][0]["cmdset"], 0x07)
        self.assertEqual(data["duml"][0]["cmd"], 0x94)

    def test_rtx_requests_first_gap(self):
        win = LossWindow(0xE9D0)
        self.assertEqual(win.push(1000), [])
        self.assertEqual(win.push(1000 + 16), [1008])
        ack = build_ack(1, win.start, win.end, win.missing())
        self.assertEqual(struct.unpack_from("<H", ack, 12)[0], 1)
        self.assertEqual(struct.unpack_from("<H", ack, 14)[0], 1008)

    def test_video_part_and_assemble(self):
        session = 0x1111
        payload_a = b"\x00\x00\x00\x01\x67AAAA"
        payload_b = b"\x00\x00\x00\x01\x65BBBB"

        def video(part: int, blob: bytes, seq_no: int) -> bytes:
            from protocol import HEADER_FLAG, pack_header, xor7
            n_parts = 2
            b11 = (n_parts & 0x7F) | ((part & 1) << 7)
            b12 = (part >> 1) & 0x1F
            inner = struct.pack("<HHHH", seq_no, seq_no, 0, 0)
            inner += bytes([7, b11, b12, 0])
            inner += blob
            packet = bytearray(pack_header(8 + len(inner), session, seq_no, TYPE_VIDEO) + inner)
            packet[0:2] = struct.pack("<H", (len(packet) & 0x7FFF) | HEADER_FLAG)
            packet[7] = xor7(packet)
            return bytes(packet)

        a = parse_video(video(0, payload_a, 0x20))
        b = parse_video(video(1, payload_b, 0x28))
        self.assertEqual(a["n_parts"], 2)
        self.assertEqual(a["part"], 0)
        self.assertEqual(b["part"], 1)
        asm = FrameAssembler()
        self.assertIsNone(asm.push(a))
        self.assertEqual(asm.push(b), payload_a + payload_b)

    def test_handshake_advertises_100_fps(self):
        packet = build_handshake(0xDD3A)
        self.assertEqual(struct.unpack_from("<H", packet, 0x0A)[0], 100)
        self.assertEqual(struct.unpack_from("<H", packet, 0x0C)[0], 100)

    def test_boost_duml_is_squirrel_bitrate_report(self):
        blob = build_bitrate_boost(7, BOOST_KBPS)
        chunks = parse_duml(blob)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["sender"], 0x1B)
        self.assertEqual(chunks[0]["receiver"], 0xEE)
        self.assertEqual(chunks[0]["cmdset"], 0x51)
        self.assertEqual(chunks[0]["cmd"], 0x29)
        self.assertEqual(struct.unpack_from("<I", chunks[0]["payload"], 0x13)[0], 22500)
        self.assertEqual(len(chunks[0]["payload"]), 23)

    def test_type5_carries_boost(self):
        duml = build_bitrate_boost(1)
        pkt = build_type5(0xDD3A, 0xE9D0, 0xE9D0, 0xE9D8, duml, counter=1)
        header = parse_header(pkt)
        self.assertEqual(header["type"], TYPE_CMD)
        self.assertEqual(header["seq"], 0xE9D0)
        self.assertTrue(pkt.endswith(duml))

    def test_ack_can_carry_rtx_and_boost_together(self):
        duml = build_bitrate_boost(1)
        ack = build_ack(1, 8, 24, resend=(16, 24), duml=duml)
        header = parse_header(ack)
        self.assertEqual(header["type"], TYPE_ACK)
        self.assertEqual(struct.unpack_from("<H", ack, 12)[0], 2)
        self.assertTrue(ack.endswith(duml))


class ParameterSetTest(unittest.TestCase):
    def test_keeps_latest_sps_pps(self):
        from liveview import parameter_sets

        sps = b"\x00\x00\x00\x01\x67\x64\x00\x1e\xaa"
        pps = b"\x00\x00\x00\x01\x68\xee\x38\x80"
        slc = b"\x00\x00\x00\x01\x41\x9a\x00"
        self.assertEqual(parameter_sets(sps + pps + slc), sps + pps)


if __name__ == "__main__":
    unittest.main()
