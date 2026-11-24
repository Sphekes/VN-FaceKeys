"""Console-free entry point; same service and rotating logs as normal startup."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys


def run():
    try:
        from facekeys_server import main
        return main(background=True)
    except Exception:
        # Fallback for import/launcher failures before the service logger exists.
        folder = Path(__file__).resolve().parent / "logs"
        folder.mkdir(exist_ok=True)
        handler = RotatingFileHandler(folder / "launcher.log", maxBytes=256 * 1024,
                                      backupCount=1, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log = logging.getLogger("vn-facekeys-launcher")
        log.addHandler(handler)
        log.critical("VN FaceKeys launcher failed", exc_info=True)
        handler.close()
        return 1


if __name__ == "__main__":
    sys.exit(run())
