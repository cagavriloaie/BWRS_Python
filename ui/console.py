"""Console UI utilities — key-wait helper used by tests/validation.py."""
import sys
import os


def wait_key():
    """Block until a key is pressed when running in a real terminal.
    Does nothing when stdin is not a tty (e.g. redirected in GUI mode)."""
    if not sys.stdin.isatty():
        return
    if os.name == "nt":
        import msvcrt
        msvcrt.getch()
    else:
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
