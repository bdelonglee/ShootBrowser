#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
python server.py --root "/Volumes/MACGUFF001/POSEIDON/SHOOT_BROWSER" --port 5001
