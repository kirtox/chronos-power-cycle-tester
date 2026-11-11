# Build a single-file, windowed Chronos.exe with PyInstaller.
# Run from the project root with the project's venv active, e.g.:
#   .\build.ps1
# Note: PyInstaller writes a benign "not necessary to run as admin" notice to
# stderr when the terminal has elevated rights; we check $LASTEXITCODE instead
# of relying on stderr content so that notice isn't mistaken for a failure.

& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE" }

& .\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name Chronos `
    --hidden-import win32timezone `
    run.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

Write-Host "Build complete: dist\Chronos.exe"
