@echo off
title Monitor PC Agent
cd /d "%~dp0"
echo ===================================================
echo Iniciando agente de monitoreo para monitorPC...
echo ===================================================
echo.

:: 1. Detect where main.py is
set "AGENT_SCRIPT="
if exist "main.py" (
    set "AGENT_SCRIPT=main.py"
) else if exist "src\main.py" (
    set "AGENT_SCRIPT=src\main.py"
)

if "%AGENT_SCRIPT%"=="" (
    echo [ERROR] No se pudo encontrar el archivo main.py.
    echo Asegurate de que run_agent.bat este en la misma carpeta que main.py.
    echo.
    pause
    exit /b
)

:: 2. Check if python is installed
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python no esta instalado en este sistema o no esta en el PATH.
    echo Por favor, descarga e instala Python desde: https://www.python.org/downloads/
    echo *IMPORTANTE: Marca la opcion "Add Python to PATH" durante la instalacion.*
    echo.
    pause
    exit /b
)

:: 3. Check and install dependencies
echo Verificando dependencias necesarias (flask, psutil, pillow)...
python -c "import flask, psutil, PIL" >nul 2>nul
if %errorlevel% neq 0 (
    echo [INFO] Instalando dependencias faltantes...
    python -m pip install --upgrade pip
    python -m pip install flask psutil pillow
    if %errorlevel% neq 0 (
        echo [ERROR] Fallo la instalacion de dependencias. Verifica tu conexion a internet.
        pause
        exit /b
    )
    echo Dependencias instaladas con exito.
    echo.
)

:: 4. Run agent
echo Iniciando el agente de monitoreo...
start "" pythonw "%AGENT_SCRIPT%"
if %errorlevel% neq 0 (
    echo.
    echo Ocurrio un error al ejecutar el agente.
    pause
)
