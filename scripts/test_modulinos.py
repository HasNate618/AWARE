#!/usr/bin/env python3
"""Quick test script for Modulinos on the Arduino UNO Q.

Run on the board:
    source ~/aware/.venv/bin/activate
    python scripts/test_modulinos.py
"""
from __future__ import annotations

import json
import sys
import time

try:
    import serial  # type: ignore[import-untyped]
except ImportError:
    print("ERROR: pyserial not installed. Run: pip install pyserial")
    sys.exit(1)

PORT = "/dev/ttyACM0"
BAUD = 115200
TIMEOUT = 0.5


def main() -> None:
    print(f"Connecting to MCU on {PORT} @ {BAUD}...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=TIMEOUT)
    except Exception as e:
        print(f"ERROR: Cannot open {PORT}: {e}")
        print("Check USB connection and serial permissions.")
        sys.exit(1)

    print("Connected! Sending READ_ALL command...\n")

    for i in range(10):
        try:
            ser.write(b"READ_ALL\n")
            line = ser.readline().decode().strip()
            if line:
                try:
                    data = json.loads(line)
                    print(f"[{i+1}] Sensors:")
                    for name, val in data.items():
                        print(f"  {name}: {val}")
                except json.JSONDecodeError:
                    print(f"[{i+1}] Raw: {line}")
            else:
                print(f"[{i+1}] No response")
        except Exception as e:
            print(f"[{i+1}] Error: {e}")
        time.sleep(1)

    ser.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
