#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
python server.py --data-path "/Volumes/MACGUFF001/POSEIDON/DATA" --port 5001
