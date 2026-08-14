@echo off
REM Opens the Song Marker in your browser, and the folder of songs waiting to be marked.
REM Nothing is uploaded anywhere - the marker runs entirely inside your own browser.
REM
REM Every ( and ) below is escaped as ^( ^). A bare ')' in an echo ends an if/else block as far as
REM cmd.exe is concerned, and the whole script dies before it runs - which is exactly how
REM Start-Grinder.bat silently failed on 2026-08-12. tests/test_launcher.py enforces this.

echo.
echo   Opening the Song Marker...
echo.
echo   1. Click "Import CSV" FIRST and choose:  scripts\song_marks.csv
echo      ^(this loads the marks you have already made - do it BEFORE marking,
echo       or importing later will overwrite your new work^)
echo.
echo   2. Click "Choose your song folder" and pick:  mark-these-songs\needs-marking
echo.
echo   3. Mark each song, then click "Export CSV" and tell Claude where it saved.
echo.

start "" "%~dp0scripts\mark_drops.html"
start "" "%~dp0mark-these-songs\needs-marking"

echo   Both windows should now be open. You can close this one.
echo.
pause
