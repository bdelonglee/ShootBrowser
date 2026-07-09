#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
python server.py --root "/Volumes/Crucial X10/POSEIDON/STRUCTURE" --port 5001
