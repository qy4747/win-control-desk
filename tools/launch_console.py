"""Project-local entry point for the independent Windows launcher."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
os.chdir(root)
os.environ['CONSOLE_DATA_DIR'] = str(root / 'data')
os.environ['CONSOLE_LOG_DIR'] = str(root / 'data' / 'logs')
os.environ['PYTHONUTF8'] = '1'
sys.path.insert(0, str(root))

if __name__ == '__main__':
    import server
    if '--no-browser' in sys.argv:
        server.main(open_browser=False, log_to_file=True)
    else:
        server.launcher_main()
