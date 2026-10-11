param(
  [Parameter(Mandatory = $true, Position = 0)]
  [ValidateSet('start', 'status', 'stop')][string]$Action,
  [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$NasAlias = 'nas',
  [ValidatePattern('^/Volume1/projects/[A-Za-z0-9_-]+$')]
  [string]$NasProject = '/Volume1/projects/Fsp-llm-workspace',
  [ValidateRange(1024, 65535)][int]$LoopbackPort = 18001
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskDirectory = Join-Path $taskRoot 'local-data/model-tunnel'
New-Item -ItemType Directory -Force -Path $taskDirectory | Out-Null
$taskReceipt = Join-Path $taskDirectory 'connection.json'
$taskSocket = "$NasProject/local-data/model-tunnel/gpu.sock"
$taskProbeCommand = "cd '$NasProject' && docker run --rm --pull never --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --env-file local-data/model-tunnel/gpu-client.env --mount type=bind,src=$NasProject/local-data/model-tunnel,dst=/model-tunnel,readonly --mount type=bind,src=$NasProject/scripts/check_remote_model.py,dst=/check.py,readonly --entrypoint python fspdelivery-tools /check.py"
function Test-NasToolsImage {
  $taskLabelsText = & ssh -o BatchMode=yes $NasAlias "docker image inspect fspdelivery-tools --format '{{json .Config.Labels}}'" 2>$null
  if ($LASTEXITCODE -ne 0) { throw 'Сначала соберите локальный fspdelivery-tools из этой рабочей копии; загрузка образа запрещена' }
  $taskLabels = $taskLabelsText | ConvertFrom-Json
  if ($taskLabels.'org.fsp.project' -ne 'career-profile' -or $taskLabels.'org.fsp.component' -ne 'tools') {
    throw 'Образ не имеет меток проектной сборки tools; ключ модели не передан'
  }
}
function Stop-OwnedSshProcess {
  param([Parameter(Mandatory = $true)][int]$ProcessId)
  Stop-Process -Id $ProcessId -ErrorAction SilentlyContinue
  Wait-Process -Id $ProcessId -Timeout 5 -ErrorAction SilentlyContinue
}
function Get-SshErrorSummary {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  $taskErrorSummary = ((Get-Content -LiteralPath $Path -Tail 5 -ErrorAction SilentlyContinue) -join ' ').Trim()
  if ($taskErrorSummary.Length -gt 500) { return $taskErrorSummary.Substring(0, 500) }
  return $taskErrorSummary
}
function Remove-OwnedDisconnectedSocket {
  param([AllowNull()]$Connection)
  & ssh -o BatchMode=yes $NasAlias "if [ -S '$taskSocket' ]; then exit 0; elif [ -e '$taskSocket' ]; then exit 4; else exit 3; fi" 2>$null
  $taskSocketState = $LASTEXITCODE
  if ($taskSocketState -eq 3) { return }
  if ($taskSocketState -eq 4) {
    throw 'Путь удалённого socket занят не socket-файлом; он не будет удалён'
  }
  if ($taskSocketState -ne 0) {
    throw 'Не удалось безопасно проверить удалённый socket; он не будет удалён'
  }
  # The receipt is the ownership boundary. Never unlink a socket discovered without it.
  if (-not $Connection) {
    throw 'Удалённый socket уже существует без квитанции этого подключения; он не будет удалён'
  }

  # The trusted tools image receives neither the model key nor networking here. It
  # unlinks only the fixed bind-mounted socket and only after connect(2) says that
  # no listener accepts it. Other errors are deliberately treated as ambiguous.
  $taskSocketCleanupPython = 'import errno,os,socket,stat,sys;p="/model-tunnel/gpu.sock";not stat.S_ISSOCK(os.lstat(p).st_mode) and sys.exit(12);s=socket.socket(socket.AF_UNIX);s.settimeout(2);r=s.connect_ex(p);r==0 and sys.exit(11);r not in (errno.ENOENT,errno.ECONNREFUSED) and sys.exit(13);os.unlink(p)'
  $taskSocketCleanupCommand = "docker run --rm --pull never --network none --read-only --user 0:0 --cap-drop ALL --security-opt no-new-privileges:true --mount type=bind,src=$NasProject/local-data/model-tunnel,dst=/model-tunnel --entrypoint python fspdelivery-tools -c '$taskSocketCleanupPython'"
  & ssh -o BatchMode=yes $NasAlias $taskSocketCleanupCommand 2>$null
  $taskCleanupExit = $LASTEXITCODE
  if ($taskCleanupExit -eq 0) { return }
  if ($taskCleanupExit -eq 11) {
    throw 'Удалённый socket принимает подключения; живой или чужой socket не будет удалён'
  }
  if ($taskCleanupExit -eq 12) {
    throw 'Путь изменился и больше не является socket-файлом; он не будет удалён'
  }
  if ($taskCleanupExit -eq 13) {
    throw 'Состояние удалённого socket неоднозначно; он не будет удалён'
  }
  & ssh -o BatchMode=yes $NasAlias "test ! -e '$taskSocket'" 2>$null
  if ($LASTEXITCODE -eq 0) { return }
  throw 'Не удалось безопасно удалить отключённый socket этого подключения'
}
$taskConnection = $null
if (Test-Path -LiteralPath $taskReceipt) {
  $taskConnection = Get-Content -LiteralPath $taskReceipt -Raw | ConvertFrom-Json
  if ($taskConnection.nas -ne $NasAlias -or $taskConnection.socket -ne $taskSocket) {
    throw 'Квитанция принадлежит другому подключению; используйте записанные параметры'
  }
}
$taskProcess = if ($taskConnection) {
  Get-CimInstance Win32_Process -Filter "ProcessId=$($taskConnection.process_id)" -ErrorAction SilentlyContinue
} else { $null }
if ($taskProcess -and ($taskProcess.Name -ne 'ssh.exe' -or -not $taskProcess.CommandLine.Contains($taskSocket))) {
  throw 'PID принадлежит другому процессу; он не будет остановлен'
}
if ($Action -eq 'status') {
  $taskModelReady = $false
  if ($taskProcess) {
    Test-NasToolsImage
    $taskProbe = & ssh -o BatchMode=yes $NasAlias "$taskProbeCommand --health-only" 2>$null
    if ($LASTEXITCODE -eq 0) {
      $taskModelReady = [bool](($taskProbe | ConvertFrom-Json).identity_verified)
    }
  }
  [pscustomobject]@{ ssh_process_alive = [bool]$taskProcess; model_ready = $taskModelReady;
    nas = $NasAlias; socket = $taskSocket } | ConvertTo-Json -Compress
  exit 0
}
if ($Action -eq 'stop') {
  if (-not $taskConnection) {
    Write-Output 'SSH-подключение модели уже остановлено'
    exit 0
  }
  if ($taskProcess) { Stop-OwnedSshProcess -ProcessId $taskProcess.ProcessId }
  $taskProcessAfterStop = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskConnection.process_id)" -ErrorAction SilentlyContinue
  if ($taskProcessAfterStop) { throw 'SSH-процесс не завершился; удалённый socket не будет затронут' }
  Test-NasToolsImage
  Remove-OwnedDisconnectedSocket -Connection $taskConnection
  Remove-Item -LiteralPath $taskReceipt -Force -ErrorAction SilentlyContinue
  Write-Output 'SSH-подключение модели остановлено'
  exit 0
}
if ($taskProcess) { throw 'Подключение уже работает; проверьте status' }
Test-NasToolsImage
$taskHealth = Invoke-RestMethod "http://127.0.0.1:$LoopbackPort/health" -TimeoutSec 5
if ($taskHealth.status -ne 'ready' -or $taskHealth.model -ne 'Qwen/Qwen3-4B-Instruct-2507' -or
    $taskHealth.revision -ne 'cdbee75f17c01a7cc42f958dc650907174af0554' -or $taskHealth.adapter -or
    $taskHealth.quantization.type -ne 'nf4' -or $taskHealth.quantization.placement -ne 'cuda:0') {
  throw 'Сначала дождитесь готовности закреплённой базовой GPU-модели без адаптера'
}
& ssh -o BatchMode=yes $NasAlias "mkdir -p '$NasProject/local-data/model-tunnel' && chmod 755 '$NasProject/local-data/model-tunnel'"
if ($LASTEXITCODE -ne 0) { throw 'Не удалось подготовить каталог отдельного сокета' }
Remove-OwnedDisconnectedSocket -Connection $taskConnection
$taskArguments = @('-N', '-T', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
  '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
  '-R', "${taskSocket}:127.0.0.1:$LoopbackPort", $NasAlias)
$taskErrorLog = Join-Path $taskDirectory 'ssh-error.log'
$taskOutputLog = Join-Path $taskDirectory 'ssh-output.log'
Remove-Item -LiteralPath $taskErrorLog, $taskOutputLog -Force -ErrorAction SilentlyContinue
$taskStarted = Start-Process ssh -ArgumentList $taskArguments -PassThru -WindowStyle Hidden `
  -RedirectStandardError $taskErrorLog -RedirectStandardOutput $taskOutputLog
[pscustomobject]@{ process_id = $taskStarted.Id; nas = $NasAlias; socket = $taskSocket;
  loopback_port = $LoopbackPort; state = 'starting'; started_at = [DateTime]::UtcNow.ToString('o') } |
  ConvertTo-Json | Set-Content -LiteralPath $taskReceipt -Encoding utf8
Start-Sleep -Seconds 2
$taskStarted.Refresh()
if ($taskStarted.HasExited) {
  $taskSshFailure = Get-SshErrorSummary -Path $taskErrorLog
  if ($taskSshFailure) { throw "SSH forward не запущен: $taskSshFailure" }
  throw 'SSH forward не запущен; журнал local-data/model-tunnel/ssh-error.log пуст'
}
& ssh -o BatchMode=yes $NasAlias "test -S '$taskSocket' && chmod 666 '$taskSocket'"
if ($LASTEXITCODE -ne 0) {
  $taskStarted.Refresh()
  if (-not $taskStarted.HasExited) { Stop-OwnedSshProcess -ProcessId $taskStarted.Id }
  throw 'Удалённый Unix socket не готов'
}
$taskAuthenticatedProbe = & ssh -o BatchMode=yes $NasAlias $taskProbeCommand
if ($LASTEXITCODE -ne 0) {
  $taskStarted.Refresh()
  if (-not $taskStarted.HasExited) { Stop-OwnedSshProcess -ProcessId $taskStarted.Id }
  throw 'Туннель не прошёл проверку точной модели и авторизации; SSH остановлен'
}
[pscustomobject]@{ process_id = $taskStarted.Id; nas = $NasAlias; socket = $taskSocket;
  loopback_port = $LoopbackPort; model_verification = ($taskAuthenticatedProbe | ConvertFrom-Json);
  started_at = [DateTime]::UtcNow.ToString('o') } |
  ConvertTo-Json | Set-Content -LiteralPath $taskReceipt -Encoding utf8
Write-Output 'SSH Unix socket модели готов; сетевой порт на NAS не открывается'
