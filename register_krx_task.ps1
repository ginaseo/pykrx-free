# =====================================================================
# register_krx_task.ps1  — 작업 스케줄러 등록 (견고 버전)
#   월~금 08:05 에 run_morning.ps1 무인 실행.
#   schtasks 기본값(배터리 스킵·절전 안깨움·놓치면 안돎)을 피하려
#   PowerShell 로 전원/깨우기/따라잡기 설정까지 박아서 등록한다.
#
#   실행: register_krx_task.bat 우클릭 > 관리자 권한으로 실행
#         (또는)  powershell -ExecutionPolicy Bypass -File register_krx_task.ps1
# =====================================================================
$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

$TaskName = "KRX_Morning_Data"
$Ps1      = Join-Path $PSScriptRoot "run_morning.ps1"
if (-not (Test-Path $Ps1)) { Write-Error "run_morning.ps1 없음: $Ps1"; exit 1 }

$action  = New-ScheduledTaskAction -Execute "powershell" `
            -Argument "-ExecutionPolicy Bypass -NoProfile -File `"$Ps1`""

$trigger = New-ScheduledTaskTrigger -Weekly `
            -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 08:05

# 핵심: 배터리에서도 시작·중단 안 함 / 절전이면 깨움 / 놓친 실행 따라잡기
$settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -WakeToRun `
            -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# 현재 사용자로, 로그인 시 실행(비번 저장 불필요)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
            -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "[OK] 작업 '$TaskName' 등록됨 — 월~금 08:05" -ForegroundColor Green
Write-Host "     배터리 무관 시작 / 절전 깨우기 / 놓친 실행 따라잡기 적용" -ForegroundColor Green

# --- 전원 깨우기 타이머 (전원 구성표 전역 설정) ---------------------
# WakeToRun 은 OS 의 '절전 모드 해제 타이머 허용' 이 켜져 있어야 실제로 깨운다.
# 이건 작업이 아니라 PC 전원 구성표 전역 설정이라, 동의 후에만 변경한다.
$ac = $null; $dc = $null
try {
    # 언어/인코딩 무관 파싱: 현재값만 '0x........' 형식(가능한 설정은 000/001/002).
    # 첫 매치 = AC 현재, 둘째 = DC 현재.
    $q   = (powercfg /query SCHEME_CURRENT SUB_SLEEP RTCWAKE) -join "`n"
    $hex = [regex]::Matches($q, '0x[0-9A-Fa-f]{8}') | ForEach-Object { $_.Value }
    if ($hex.Count -ge 2) { $ac = $hex[0]; $dc = $hex[1] }
} catch {}

if ($ac -ne "0x00000001" -or $dc -ne "0x00000001") {
    Write-Host ""
    Write-Host "[주의] 절전 모드 해제 타이머가 꺼져있거나 '중요만' 으로 제한됨 (AC=$ac DC=$dc)." -ForegroundColor Yellow
    Write-Host "       이대로면 PC 가 절전이면 08:05 에 안 깨어나 실행이 스킵될 수 있다." -ForegroundColor Yellow
    $ans = if ([Environment]::UserInteractive) {
        Read-Host "       지금 전원 구성표의 깨우기 타이머를 켤까? (전역 설정 변경) [y/N]"
    } else { "n" }   # 비대화형 실행이면 멈추지 않고 건너뜀
    if ($ans -match '^[Yy]') {
        powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
        powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
        powercfg /setactive SCHEME_CURRENT
        Write-Host "[OK] 깨우기 타이머 AC/DC 모두 켬." -ForegroundColor Green
    } else {
        Write-Host "       건너뜀. 절전 깨우기가 필요하면 나중에 직접 켤 것:" -ForegroundColor DarkYellow
        Write-Host "       powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1" -ForegroundColor DarkYellow
        Write-Host "       powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1; powercfg /setactive SCHEME_CURRENT" -ForegroundColor DarkYellow
    }
} else {
    Write-Host "[OK] 절전 모드 해제 타이머 AC/DC 모두 켜짐 — 절전이어도 깨워서 실행." -ForegroundColor Green
}

Write-Host ""
Write-Host "확인:  schtasks /query /tn $TaskName /v /fo LIST" -ForegroundColor Cyan
