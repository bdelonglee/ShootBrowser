@echo off
:: ── VFX Shoot Browser launcher ────────────────────────────────────────────────
:: Edit DATA_PATH to match the drive letter of your shoot data on this machine.
set DATA_PATH=D:\POSEIDON\DATA

cd /d "%~dp0"
call venv\Scripts\activate
python server.py --data-path "%DATA_PATH%"
pause
