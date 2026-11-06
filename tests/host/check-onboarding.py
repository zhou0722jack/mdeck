#!/usr/bin/env python3
"""Compatibility entry point for the replacement native startup checks."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).with_name('check-deck-startup.py')), run_name='__main__')
