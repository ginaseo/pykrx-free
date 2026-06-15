# =====================================================================
# run_morning.ps1  — 작업 스케줄러용 진입점
#   이 스크립트와 같은 폴더(pykrx-free)의 전용 venv 로 브리핑+스크리너 실행.
#   산출 JSON(briefing_data.json / kospi200_screen.json)은 파이썬 OUT_DIR
#   규칙에 따라 이 폴더 아래 results\ 에 생성된다.
#
# 수동 실행:  powershell -ExecutionPolicy Bypass -File run_morning.ps1
# =====================================================================
$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$env:PYTHONIOENCODING = "utf-8"

$Free = $PSScriptRoot                          # pykrx-free (스크립트/venv 위치)
$Out  = Join-Path $Free "results"              # 파이썬 OUT_DIR 과 동일(results 폴더)
$Py   = Join-Path $Free ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { Write-Error "venv 파이썬 없음: $Py"; exit 1 }
Set-Location $Free

Write-Host "[run_morning] 1/2 briefing..." -ForegroundColor Cyan
& $Py (Join-Path $Free "krx_briefing_fetch.py")
if (-not (Test-Path (Join-Path $Out "briefing_data.json"))) { Write-Error "briefing 실패"; exit 1 }

Write-Host "[run_morning] 2/2 screener..." -ForegroundColor Cyan
& $Py (Join-Path $Free "krx_screener_api.py")
if (-not (Test-Path (Join-Path $Out "kospi200_screen.json"))) { Write-Error "screener 실패"; exit 1 }

Write-Host "[run_morning] 완료 -> $Out\briefing_data.json + kospi200_screen.json" -ForegroundColor Green
