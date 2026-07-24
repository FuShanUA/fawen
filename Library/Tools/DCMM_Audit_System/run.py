#!/usr/bin/env python3
"""Top-level entry point: python run.py --engine glm --batch-dir "..." """

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dcmm.cli import main

if __name__ == "__main__":
    main()
