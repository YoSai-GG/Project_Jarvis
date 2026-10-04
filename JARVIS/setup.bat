@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if not exist "vosk-model-small-en-us-0.15" (
  ".venv\Scripts\python.exe" -c "import urllib.request,zipfile; u='https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip'; p='vosk-model.zip'; urllib.request.urlretrieve(u,p); zipfile.ZipFile(p).extractall('.'); __import__('os').remove(p)"
)
".venv\Scripts\python.exe" app.py
pause
