"""Entry point — BWRS Gas Flow Calculator (GUI)."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    try:
        from ui.gui import run
        run()
    except Exception:
        import traceback
        msg = traceback.format_exc()

        # Write a log file next to the executable (or script) so the error
        # is always recoverable even when no window can be shown.
        _base = os.path.dirname(
            sys.executable if getattr(sys, "frozen", False)
            else os.path.abspath(__file__)
        )
        try:
            with open(os.path.join(_base, "bwrs_error.log"), "w", encoding="utf-8") as _f:
                _f.write(msg)
        except OSError:
            pass

        # Best-effort messagebox — may itself fail if tkinter is broken.
        try:
            import tkinter
            import tkinter.messagebox
            _root = tkinter.Tk()
            _root.withdraw()
            tkinter.messagebox.showerror("BWRS — Startup error", msg)
            _root.destroy()
        except Exception:
            pass

        sys.exit(1)
