import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband.zybo import probe, uart_candidates


class FakeSerial:
    """Stands in for pyserial: a port that answers with `replies`."""
    SerialException = OSError

    def __init__(self, replies):
        self.replies = replies
        self.written = b""

    def Serial(self, port, baud, timeout):
        if port not in self.replies:
            raise OSError("no such port")
        self.lines = list(self.replies[port])
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.written += data

    def readline(self):
        return self.lines.pop(0) if self.lines else b""


def test_uart_candidates():
    pair = ["/dev/cu.usbserial-210351BDF9941", "/dev/cu.usbserial-210351BDF9940"]
    assert uart_candidates(pair) == ["/dev/cu.usbserial-210351BDF9941"]
    assert uart_candidates(["/dev/cu.usbserial-A10"]) == ["/dev/cu.usbserial-A10"]
    assert uart_candidates([]) == []


def test_probe():
    fake = FakeSerial({"/dev/board": [b"ERR COMMAND\r\n", b"PONG DB01\r\n"],
                       "/dev/other": [b"Zybo Z7-20 Rev. B Demo Image\r\n"]})
    assert probe(fake, "/dev/board", 0.2)
    assert fake.written.endswith(b"PING\n")
    assert not probe(fake, "/dev/other", 0.2)
    assert not probe(fake, "/dev/missing", 0.2)


if __name__ == "__main__":
    test_uart_candidates()
    test_probe()
    print("ok")
