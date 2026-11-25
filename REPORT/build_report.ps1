<#
.SYNOPSIS
    D:-Drive isolated XeLaTeX build script for DI41015 X-57 DEP Coursework Report.
    Compiles main.tex + references.bib (IEEE style) -> X57_DEP_CFD_Coursework_Report.pdf and renders page previews.
#>
param(
    [switch]$RenderPreviews
)

$ErrorActionPreference = "Stop"
$ReportDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$WsRoot    = Split-Path -Parent $ReportDir
$BuildDir  = Join-Path $ReportDir "_build"
$TmpDir    = Join-Path $WsRoot "_tmp"
$OutPdf    = Join-Path $ReportDir "X57_DEP_CFD_Coursework_Report.pdf"

New-Item -ItemType Directory -Force -Path $BuildDir, $TmpDir | Out-Null
$env:TEMP = $TmpDir
$env:TMP  = $TmpDir

function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $Exe @Arguments 2>&1
        $rc = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    if ($rc -ne 0) {
        $out | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        throw "$Exe failed with exit code $rc"
    }
}

Push-Location $ReportDir
try {
    Write-Host "[LaTeX] Pass 1/3 (xelatex)..." -ForegroundColor Cyan
    Invoke-Native "xelatex" @("-interaction=nonstopmode", "-halt-on-error", "-output-directory=$BuildDir", "main.tex")

    Write-Host "[LaTeX] BibTeX pass (IEEE ieeetr)..." -ForegroundColor Cyan
    $env:BIBINPUTS = "$ReportDir;"
    Push-Location $BuildDir
    try {
        Invoke-Native "bibtex" @("main")
    } finally {
        Pop-Location
    }

    Write-Host "[LaTeX] Pass 2/3 (xelatex)..." -ForegroundColor Cyan
    Invoke-Native "xelatex" @("-interaction=nonstopmode", "-halt-on-error", "-output-directory=$BuildDir", "main.tex")

    Write-Host "[LaTeX] Pass 3/3 (xelatex — resolve LastPage & cleveref)..." -ForegroundColor Cyan
    Invoke-Native "xelatex" @("-interaction=nonstopmode", "-halt-on-error", "-output-directory=$BuildDir", "main.tex")

    Copy-Item -Force (Join-Path $BuildDir "main.pdf") $OutPdf
    $sz = [math]::Round((Get-Item $OutPdf).Length / 1KB, 1)
    Write-Host "[OK] Built $OutPdf ($sz KB)" -ForegroundColor Green

    if ($RenderPreviews) {
        $vpy = Join-Path $WsRoot ".venv\Scripts\python.exe"
        $prevDir = Join-Path $BuildDir "page_previews"
        New-Item -ItemType Directory -Force -Path $prevDir | Out-Null
        Get-ChildItem -Path $prevDir -Filter 'page_*.png' -ErrorAction SilentlyContinue | Remove-Item -Force
        & $vpy -c "import pymupdf, pathlib; doc=pymupdf.open(r'$OutPdf'); out=pathlib.Path(r'$prevDir'); [p.get_pixmap(dpi=160).save(str(out/f'page_{i+1:02d}.png')) for i,p in enumerate(doc)]; print(f'[OK] Rendered {len(doc)} preview PNGs to {out}')"
    }
} finally {
    Pop-Location
}
