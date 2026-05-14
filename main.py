import sys

from pdfsplitter.cli import main as cli_main


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv or argv == ["--gui"]:
        from pdfsplitter.gui import launch_gui

        launch_gui()
        raise SystemExit(0)
    raise SystemExit(cli_main(argv))
