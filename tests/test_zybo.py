import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband import config as C
from deskband.zybo import probe, uart_candidates
from main import App


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


LIGHT = (slice(22, 40), slice(138, 196))      # the dot and its label, clear of the title
BAR = types.SimpleNamespace(math=False)


def light(app):
    """Mean brightness of the status light in the rendered frame."""
    return float(app.render(0.033)[LIGHT].mean())


def test_status_light():
    """Unlit without a board, steady once it answers, brightest on the downbeat."""
    folder = tempfile.TemporaryDirectory()
    old_folder, C.SHELF_DIR = C.SHELF_DIR, folder.name
    try:
        app = App()
        app.on = {"cup"}
        app.engine.bar_now = lambda: (1.2, BAR)          # between downbeats

        app.zybo.status = "looking for board"
        away = light(app)
        app.zybo.status = "connected cu.usbserial-210351BDF9941"
        attached = light(app)
        app.engine.fpga_mode = True
        conducting = light(app)
        app.engine.bar_now = lambda: (0.0, BAR)
        downbeat = light(app)
        assert away < attached < conducting < downbeat, (away, attached, conducting, downbeat)

        app.enter_summary()                              # the Collections page has its own header
        app.zybo.status = "looking for board"
        app.engine.fpga_mode = False
        off = light(app)
        app.zybo.status = "connected cu.usbserial-210351BDF9941"
        app.engine.fpga_mode = True
        assert light(app) == off                         # no light reaches that screen
    finally:
        C.SHELF_DIR = old_folder
        folder.cleanup()


if __name__ == "__main__":
    test_uart_candidates()
    test_probe()
    test_status_light()
    print("ok")
