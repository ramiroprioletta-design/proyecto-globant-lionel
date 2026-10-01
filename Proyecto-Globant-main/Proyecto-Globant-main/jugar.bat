@echo off
setlocal
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

if not exist "%PYTHON%" set "PYTHON=%LOCALAPPDATA%\Python\pythoncore-3.12-64\python.exe"

if not exist "%PYTHON%" (
  echo No se encontro Python 3.12 en las rutas conocidas.
  pause
  exit /b 1
)

"%PYTHON%" "%~dp0main.py"
if errorlevel 1 pause
