@echo off
chcp 65001 >nul
setlocal
rem ===== SETTINGS =====
rem KEY: the REAL background color of your video, as 0xRRGGBB. Do not guess. Pick it from a frame with the Paint eyedropper. 0x00FF00 only works if the background is truly pure green
set KEY=0x00AB11
set SPILL=green
rem SIM: key sensitivity. Haze left on the background: raise it a little at a time, for example 0.16 then 0.18. Character edges or dark or skin colors getting eaten: lower it
set SIM=0.14
set BLEND=0.05
rem OUTFIT: the outfit this clip belongs to. The finished clip goes to the clips folder of the project, into the sub-folder with this name: clips\OUTFIT\NAME.webm (created if missing). The program's default outfit is named 日常. Change this line to make clips for another outfit, for example the pajamas.
set OUTFIT=日常
rem HEIGHT: output height in pixels. 960 is full size at 150 percent scale. Use 1280 for sharper, 720 for lighter
set HEIGHT=960
rem PREVIEW: set to 1 to skip making the video. It writes a black and white mask picture, NAME_mask.png, next to this file. Black = transparent, white = solid, gray = haze. Use it to tune KEY and SIM quickly
set PREVIEW=0
rem Watermark cover, bottom-right corner. Set WM=1 to turn it on. All units are pixels of the ORIGINAL video.
rem WM_W and WM_H = width and height of the cover box. WM_MX and WM_MY = gap between the box and the right and bottom edges.
set WM=0
set WM_W=300
set WM_H=300
set WM_MX=0
set WM_MY=0
rem ====================

set PRE=
if "%WM%"=="1" set PRE=drawbox=x=iw-%WM_W%-%WM_MX%:y=ih-%WM_H%-%WM_MY%:w=%WM_W%:h=%WM_H%:color=%KEY%:t=fill,
set KEYCHAIN=scale=-2:%HEIGHT%,chromakey=%KEY%:%SIM%:%BLEND%,despill=type=%SPILL%:mix=0.5:expand=0.1,format=yuva420p,lut=a='clip((val-90)*255/(200-60)\,0\,255)'

where ffmpeg >nul 2>nul || (echo ffmpeg not found. Run this in PowerShell: winget install Gyan.FFmpeg then close and reopen the window. & pause & exit /b 1)
set OUT=%~dp0..\clips\%OUTFIT%
if not exist "%OUT%" mkdir "%OUT%"

:next
if "%~1"=="" goto end
echo Processing %~nx1 ...
if "%PREVIEW%"=="1" goto preview
ffmpeg -hide_banner -loglevel error -y -i "%~1" -filter_complex "[0:v]%PRE%%KEYCHAIN%,split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0,format=yuva420p[v]" -map "[v]" -an -c:v libvpx-vp9 -pix_fmt yuva420p -b:v 0 -crf 32 -auto-alt-ref 0 -row-mt 1 "%OUT%\%~n1.webm"
goto checked
:preview
ffmpeg -hide_banner -loglevel error -y -i "%~1" -frames:v 1 -filter_complex "[0:v]%PRE%%KEYCHAIN%,alphaextract" "%~dp0%~n1_mask.png"
:checked
if errorlevel 1 echo FAILED: %~nx1
shift
goto next

:end
echo.
echo Done. Video output goes to the clips\%OUTFIT% folder of the project, named as the input name plus .webm. In PREVIEW mode the mask picture is next to this file.
echo So rename the source files first, for example idle.mp4 or talking-neutral.mp4, then drag them in.
pause