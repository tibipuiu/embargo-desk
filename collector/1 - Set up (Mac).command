#!/bin/bash
cd "$(dirname "$0")" || exit 1
echo "Setting up the Embargo Desk fetcher. The first time takes a few minutes."
echo

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
  echo "The fetcher needs Python 3.10 or newer, which isn't installed yet."
  echo "Opening python.org: download and run the macOS installer, then open this setup file again."
  open "https://www.python.org/downloads/"
  read -r -p "Press Enter to close this window."
  exit 1
fi

fail() {
  echo
  echo "Setup didn't finish. Take a screenshot of this window and send it to whoever runs Embargo Desk."
  read -r -p "Press Enter to close this window."
  exit 1
}

echo "Creating a private Python environment for the fetcher..."
python3 -m venv .venv || fail
echo "Installing components..."
.venv/bin/python -m pip install --upgrade pip --quiet --disable-pip-version-check || fail
.venv/bin/python -m pip install -r requirements.txt --quiet --disable-pip-version-check || fail
echo "Downloading the fetcher's own copy of Chromium, about 150 MB. Your normal browser isn't touched."
.venv/bin/python -m playwright install chromium || fail
echo
echo "All set. From now on, open \"2 - Fetch embargoes (Mac)\" to fetch."
read -r -p "Press Enter to close this window."
