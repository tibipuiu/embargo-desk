#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "The fetcher isn't set up yet. Open \"1 - Set up (Mac)\" first."
  read -r -p "Press Enter to close this window."
  exit 1
fi
.venv/bin/python collect.py "$@"
echo
read -r -p "Press Enter to close this window."
