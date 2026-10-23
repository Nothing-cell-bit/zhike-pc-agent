"""Compatibility entry point for the current submission manual."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[1]/'output/pdf/build_submission_manual.py'),run_name='__main__')
