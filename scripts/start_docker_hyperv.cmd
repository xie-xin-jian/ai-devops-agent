@echo off
set "LOCALAPPDATA=D:\Docker\AppData\Local"
set "APPDATA=D:\Docker\AppData\Roaming"
if not defined DOCKER_DESKTOP_EXE set "DOCKER_DESKTOP_EXE=D:\Docker\DockerDesktop\Docker Desktop.exe"
start "" "%DOCKER_DESKTOP_EXE%"
