@@ECHO OFF
set/p URL="URL :- "

hulu.py %URL% -q 1080p --h264
pause.

@@ECHO OFF
