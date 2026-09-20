"""Read the actual OpenCV window content size on macOS.

On Cocoa, getWindowImageRect can keep reporting the old image dimensions after
the user resizes a window. The NSView bounds reflect the new size immediately.
"""

import ctypes
from functools import lru_cache
import platform
import sys


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _Size(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _Rect(ctypes.Structure):
    _fields_ = [("origin", _Point), ("size", _Size)]


@lru_cache(maxsize=1)
def _objc():
    objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
    object_message = ctypes.CFUNCTYPE(
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(address)
    count_message = ctypes.CFUNCTYPE(
        ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p)(address)
    indexed_message = ctypes.CFUNCTYPE(
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)(address)
    rect_message = ctypes.CFUNCTYPE(
        _Rect, ctypes.c_void_p, ctypes.c_void_p)(address)
    return objc, object_message, count_message, indexed_message, rect_message


def content_size(title):
    """Return the Cocoa content size in points, or None on other platforms."""
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return None
    try:
        objc, object_message, count_message, indexed_message, rect_message = _objc()
        selector = lambda name: objc.sel_registerName(name.encode("ascii"))
        send = lambda target, name: object_message(target, selector(name))

        application = send(objc.objc_getClass(b"NSApplication"), "sharedApplication")
        windows = send(application, "windows")
        count = count_message(windows, selector("count"))
        for index in range(count):
            window = indexed_message(windows, selector("objectAtIndex:"), index)
            window_title = send(window, "title")
            utf8 = send(window_title, "UTF8String")
            if utf8 and ctypes.string_at(utf8) == title.encode("utf-8"):
                bounds = rect_message(send(window, "contentView"), selector("bounds"))
                width, height = round(bounds.size.width), round(bounds.size.height)
                if width > 0 and height > 0:
                    return width, height
    except (AttributeError, OSError, ValueError):
        pass
    return None
