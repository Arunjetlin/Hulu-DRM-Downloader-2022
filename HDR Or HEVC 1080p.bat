@@ECHO OFF
set/p URL="URL :- "

hulu.py %URL% -q 1080p --hdr
pause.

@@ECHO OFF
