<#
.SYNOPSIS
    Strict D:\FEA Coursework\Workspace environment isolation for X-57 DEP CFD Coursework.
    Dot-source this script before running any Python, Fluent, MAPDL, or post-processing command:
        . "D:\FEA Coursework\Workspace\scripts\env_d_only.ps1"
#>

$WorkspaceRoot = "D:\FEA Coursework\Workspace"
$TmpDir        = Join-Path $WorkspaceRoot "_tmp"
$CacheDir      = Join-Path $WorkspaceRoot "_cache"
$MplDir        = Join-Path $CacheDir "matplotlib"
$PipDir        = Join-Path $CacheDir "pip"
$UvDir         = Join-Path $CacheDir "uv"
$XdgDir        = Join-Path $CacheDir "xdg"

foreach ($d in @($TmpDir, $CacheDir, $MplDir, $PipDir, $UvDir, $XdgDir)) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Force -Path $d | Out-Null
    }
}

# Redirect ALL temporary, scratch, and cache paths strictly to D:\FEA Coursework\Workspace (ZERO C:/E:/F: writes!)
$env:TEMP                   = $TmpDir
$env:TMP                    = $TmpDir
$env:TMPDIR                 = $TmpDir
$env:FLUENT_TMPDIR          = $TmpDir
$env:AWP_TEMP_DIR           = $TmpDir
$env:ANSYS_TEMP_DIR         = $TmpDir
$env:ANSYS_SCRATCH_DIR      = $TmpDir
$env:AWP_LOCALE252          = "en-us"
$env:FLUENT_NO_WEB_BROWSER  = "1"

# Python / package caches strictly inside D:\FEA Coursework\Workspace
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:MPLCONFIGDIR            = $MplDir
$env:PIP_CACHE_DIR           = $PipDir
$env:UV_CACHE_DIR            = $UvDir
$env:XDG_CACHE_HOME          = $XdgDir
$env:PYTHONUTF8              = "1"

# Canonical tool paths on D:
$env:X57_WORKSPACE = $WorkspaceRoot
$env:X57_PYTHON    = "D:\anaconda3\python.exe"
$env:X57_FLUENT    = "D:\Ansys\ANSYS Inc\ANSYS Student\v252\fluent\ntbin\win64\fluent.exe"
$env:X57_MAPDL     = "D:\Ansys\ANSYS Inc\ANSYS Student\v252\ansys\bin\winx64\MAPDL.exe"
$env:X57_ANSYS_PY  = "D:\Ansys\ANSYS Inc\ANSYS Student\v252\commonfiles\CPython\3_10\winx64\Release\python\python.exe"

# Keep application configuration, plotting preferences, and PyVista caches inside workspace
$env:NATURE_FIGURE_CONFIG  = Join-Path $CacheDir "nature-figure.json"
$env:PYVISTA_USERDATA_PATH = Join-Path $CacheDir "pyvista"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $CacheDir "uv-python"
$env:UV_TOOL_DIR           = Join-Path $CacheDir "uv-tools"
$env:PYTHONPYCACHEPREFIX   = Join-Path $CacheDir "pycache"
$env:NUMBA_CACHE_DIR       = Join-Path $CacheDir "numba"

# Prefer workspace-local venv on D:
$LocalVenvPy = Join-Path $WorkspaceRoot ".venv\Scripts\python.exe"
if (Test-Path $LocalVenvPy) {
    $env:X57_PYTHON = $LocalVenvPy
}

$drive = Get-PSDrive D
$freeGB = [math]::Round($drive.Free / 1GB, 2)
Write-Host "[D-WORKSPACE ENV] Active | TEMP/TMP/CACHE -> $WorkspaceRoot | D: Free = ${freeGB} GB | Python = $env:X57_PYTHON"
if ($freeGB -lt 10.0) {
    Write-Warning "[D-WORKSPACE ENV] Low disk space on D: (${freeGB} GB free)! Clean _tmp or old intermediate checkpoints before continuing."
}
