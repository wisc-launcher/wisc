"""Start Wisc from source or a Windows package."""

from wisc.services import updates

if __name__ == "__main__":
    updates.startup_guard()

from wisc.app import run

if __name__ == "__main__":
    run()
