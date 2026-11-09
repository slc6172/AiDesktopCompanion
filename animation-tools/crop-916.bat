@echo off
chcp 65001 >nul
setlocal
rem Drag one or more images onto this file. For each image it writes NAME_916.EXT next to the original,
rem cropped around the center to exactly 9:16. The original is not changed.
rem   Wider than 9:16 (for example 2:3): the left and right sides are cropped. This is the normal case.
rem   Taller than 9:16: the top and bottom are cropped instead.
rem   Already 9:16: the picture is copied unchanged.

where ffmpeg >nul 2>nul || (echo ffmpeg not found. Run this in PowerShell: winget install Gyan.FFmpeg then close and reopen the window. & pause & exit /b 1)

if "%~1"=="" goto noargs

:next
if "%~1"=="" goto end
set "NAME=%~n1"
if /i "%NAME:~-4%"=="_916" goto skip916
echo Processing "%~nx1" ...
ffmpeg -hide_banner -loglevel error -y -i "%~1" -vf "crop=w='min(iw,trunc(ih*9/16/2)*2)':h='min(ih,trunc(iw*16/9/2)*2)'" -q:v 2 "%~dpn1_916%~x1"
if errorlevel 1 goto failed
echo   OK: "%~n1_916%~x1"
goto nextfile

:skip916
echo Skipping "%~nx1" because the name already ends with _916
goto nextfile

:failed
echo   FAILED: "%~nx1"

:nextfile
shift
goto next

:noargs
echo Drag one or more image files onto this file.
pause
exit /b 1

:end
echo.
echo Done. The new files are next to the originals, with _916 added to the name.
pause
