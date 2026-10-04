@echo off
chcp 65001 >nul
setlocal
title Русификатор Final Fantasy (PSP)

rem Поиск Python 3.8+ (py-лаунчер или python в PATH)
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul && set "PY=py -3"
if defined PY goto run
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul && set "PY=python"
if defined PY goto run

echo.
echo Не найден Python 3.8 или новее.
echo Скачайте его с https://www.python.org/downloads/ и при установке
echo отметьте галочку "Add python.exe to PATH". Потом запустите этот файл снова.
echo.
pause
exit /b 1

:run
%PY% "%~dp0ff1_rus.py" %*
echo.
pause
