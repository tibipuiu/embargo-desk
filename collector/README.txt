EMBARGO DESK FETCHER
====================

This collects new embargoed releases from EurekAlert! on your computer and
uploads them to Embargo Desk, which picks the promising ones for the team board.

This folder contains your personal upload key (in fetcher.json).
Don't share it. If it leaks, use "Revoke my key" on the Fetch page.


ONE-TIME SETUP
--------------
1. If you don't have Python yet, install it from https://www.python.org/downloads/
   (Windows: on the installer's first screen, tick "Add python.exe to PATH").
   The setup step below tells you if this is needed and opens the page for you.

2. Move this folder somewhere permanent (e.g. Documents), then:
     Windows: double-click   1 - Set up (Windows)
     Mac:     right-click    1 - Set up (Mac)   and choose Open
              (the first time, macOS asks whether to open a file from the internet; choose Open)
   It downloads the fetcher's own copy of Chromium (about 150 MB). Your normal
   browser isn't touched.


TO FETCH
--------
  Windows: double-click   2 - Fetch embargoes (Windows)
  Mac:     double-click   2 - Fetch embargoes (Mac)

A browser window opens on EurekAlert!. The first time, log in with your own
EurekAlert! reporter account; it's remembered after that. Leave the window open
until the black window says "Done". Fetching usually takes 2-5 minutes.

Releases someone else already fetched are skipped, so it doesn't matter who
fetches or how often. Once a day, in the morning, is plenty.


IF SOMETHING GOES WRONG
-----------------------
Take a screenshot of the black window and send it to whoever runs Embargo Desk.
