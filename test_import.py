#!/usr/bin/env python3
import sys
import os
from pathlib import Path

print(f"Current directory: {os.getcwd()}")
print(f"Script directory: {Path(__file__).parent.absolute()}")

try:
    import main
    print(" Successfully imported main")
    print(f"main.py location: {main.__file__}")
except ImportError as e:
    print(f" Failed to import main: {e}")
    
    # Check if file exists
    if Path("main.py").exists():
        print(" main.py exists in current directory")
    else:
        print(" main.py NOT found in current directory")
