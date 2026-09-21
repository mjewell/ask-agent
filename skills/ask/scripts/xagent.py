#!/usr/bin/env python3
"""Compatibility entry point for the renamed ask-agent runner."""

from pathlib import Path
import runpy


runpy.run_path(str(Path(__file__).with_name("ask-agent.py")), run_name="__main__")
