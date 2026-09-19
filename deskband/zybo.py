"""Find the Zybo on USB and run tools/zybo_bridge.py for it, so the board is
part of the app instead of a second terminal.

The bridge runs as its own process: its serial loop polls every millisecond
and must not compete with the audio callback for the GIL. If the board is
unplugged or the bridge exits, DeskBand drops back to its own sequencer and
this keeps looking, so the board can be plugged in at any time.
"""

import glob
import os
import signal
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "tools", "zybo_bridge.py")
SCAN_EVERY = 2.0


def uart_candidates(ports):
    """The FT2232 on J12 shows up as <serial>0 (JTAG) and <serial>1 (UART).
    Skip the JTAG half of a pair so probing never writes to it."""
    ports = sorted(ports)
    return [p for p in ports if not (p.endswith("0") and p[:-1] + "1" in ports)]


def probe(serial, port, seconds=1.0):
    """True if the DeskBand firmware on `port` answers PING."""
    try:
        with serial.Serial(port, 115200, timeout=0.1) as ser:
            ser.reset_input_buffer()
            ser.write(b"\nPING\n")                   # the newline flushes any partial line
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if ser.readline().startswith(b"PONG"):
                    return True
    except (OSError, serial.SerialException):
        pass
    return False


class ZyboLink(threading.Thread):
    def __init__(self, on_lost):
        super().__init__(daemon=True)
        self.on_lost = on_lost           # called when a connected board goes away
        self.status = "looking for board"
        self.proc = None
        self._halt = threading.Event()

    def run(self):
        try:
            import serial
        except ImportError:
            self.status = "off (pip install pyserial)"
            print("[zybo] pyserial not installed; hardware conductor off", flush=True)
            return
        while not self._halt.is_set():
            port = next((p for p in uart_candidates(glob.glob("/dev/cu.usbserial-*"))
                         if probe(serial, p)), None)
            if port is None or self._halt.is_set():
                self._halt.wait(SCAN_EVERY)
                continue
            print(f"[zybo] board found on {port}", flush=True)
            self.status = f"connected {os.path.basename(port)}"
            env = dict(os.environ, PYTHONPATH=ROOT)
            self.proc = subprocess.Popen([sys.executable, "-u", BRIDGE, port], cwd=ROOT, env=env)
            while self.proc.poll() is None and not self._halt.is_set():
                self._halt.wait(0.5)
            if self._halt.is_set():
                break
            self.on_lost()
            self.status = "lost board, looking again"
            print("[zybo] bridge stopped; looking for the board again", flush=True)
            self._halt.wait(SCAN_EVERY)

    def stop(self):
        """SIGINT, like Ctrl+C, so the bridge stops the FPGA transport on its way out."""
        self._halt.set()
        if self.is_alive():
            self.join(3.0)                           # so no bridge starts after this
        proc = self.proc
        if proc is not None and proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
