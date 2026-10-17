# Автозапуск ПТО Сервера (Планировщик заданий Windows) и правило брандмауэра.
# Запуск: двойной щелчок по «Настроить_автозапуск_сервера.bat» (сам запросит права администратора).
#   -Mode Logon  : сервер с окном стартует при входе пользователя в Windows (по умолчанию, пароль не нужен)
#   -Mode Boot   : сервер без окна стартует при включении компьютера, ещё до входа в Windows (потребуется пароль Windows)
#   -Remove      : удалить задание и правило брандмауэра
param(
    [ValidateSet('Logon','Boot')][string]$Mode = 'Logon',
    [string]$Exe = '',
    [int]$Port = 8765,
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$TaskName = 'ПТО Сервер'
$RuleName = 'PTO Server'

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host 'Нужны права администратора: запустите через .bat-файл или «От имени администратора».' -ForegroundColor Red; exit 1 }

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    Write-Host 'Автозапуск и правило брандмауэра удалены.' -ForegroundColor Green
    exit 0
}

# --- где лежит PTO_Server.exe
if (-not $Exe) {
    $candidates = @(
        (Join-Path $PSScriptRoot 'PTO_Server.exe'),
        (Join-Path (Split-Path $PSScriptRoot -Parent) 'PTO_Server.exe'),
        (Join-Path $env:ProgramFiles 'ПТО\PTO_Server.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'ПТО\PTO_Server.exe')
    )
    $Exe = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (-not $Exe -or -not (Test-Path $Exe)) {
    $Exe = Read-Host 'Не нашёл PTO_Server.exe. Введите полный путь к нему'
    if (-not (Test-Path $Exe)) { Write-Host 'Файл не найден.' -ForegroundColor Red; exit 1 }
}
Write-Host "Сервер: $Exe"

$me = "$env:USERDOMAIN\$env:USERNAME"
Write-Host "Задание будет работать от имени $me — база берётся из папки этого пользователя (C:\Users\$env:USERNAME\.smetagaz)." -ForegroundColor Yellow
Write-Host 'Это должна быть та же учётная запись Windows, под которой вы уже создали администратора сервера.' -ForegroundColor Yellow

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew

if ($Mode -eq 'Logon') {
    $action = New-ScheduledTaskAction -Execute $Exe
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
    $principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Host 'Готово: при входе в Windows откроется окно «ПТО Сервер».' -ForegroundColor Green
} else {
    $cred = Get-Credential -UserName $me -Message 'Пароль Windows этого пользователя (нужен, чтобы сервер стартовал до входа в систему)'
    $action = New-ScheduledTaskAction -Execute $Exe -Argument "--console --port $Port" -WorkingDirectory (Split-Path $Exe -Parent)
    $trigger = New-ScheduledTaskTrigger -AtStartup
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -User $cred.UserName `
        -Password $cred.GetNetworkCredential().Password -RunLevel Limited -Settings $settings -Force | Out-Null
    Write-Host 'Готово: сервер без окна запустится при включении компьютера.' -ForegroundColor Green
    Write-Host 'Чтобы добавить пользователей, остановите задание («Планировщик заданий» → ПТО Сервер → Завершить) и откройте окно ПТО Сервера.'
}

# --- брандмауэр: входящие подключения клиентов
Remove-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Private,Domain | Out-Null
Write-Host "Порт $Port открыт для частных и доменных сетей." -ForegroundColor Green

# --- сон отключаем: спящий сервер недоступен
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change hibernate-timeout-ac 0 | Out-Null
Write-Host 'Сон и гибернация от сети отключены.'

if ((Read-Host 'Запустить сервер сейчас? (д/н)') -match '^[дДyY]') { Start-ScheduledTask -TaskName $TaskName; Write-Host 'Запущено.' }
$ips = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' }).IPAddress -join ', '
Write-Host "Клиенты подключаются по адресу: $ips (порт $Port)" -ForegroundColor Cyan
Read-Host 'Нажмите Enter для выхода'
