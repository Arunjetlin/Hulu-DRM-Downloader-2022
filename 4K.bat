@@ECHO OFF
set/p URL="URL :- "

hulu.py %URL% -q 2160p --hdr
pause.

@@ECHO OFF
