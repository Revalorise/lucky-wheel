#!/bin/bash
set -e

APP_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$APP_DIR"
exec python3 Wheel_of_Fortune_Raspberry_Pi_4.py
