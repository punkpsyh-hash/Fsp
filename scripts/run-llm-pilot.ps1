param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[a-z][a-z0-9-]{0,31}$')]
  [string]$Step,
  [Parameter(Mandatory = $true)]
  [ValidateNotNullOrEmpty()]
  [string[]]$PythonArguments,
  [switch]$Online,
  [string]$Interpreter = '/cache/pilot-venv/bin/python',
  [string]$ProjectPath,
  [string]$CachePath = 'D:/Codex/Caches/fsp-llm',
  [string]$LogDirectory
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectPath) { $ProjectPath = Split-Path -Parent $PSScriptRoot }
$taskProject = (Resolve-Path -LiteralPath $ProjectPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $taskProject 'ml/pilot.py') -PathType Leaf)) {
  throw 'ProjectPath должен указывать на проект с ml/pilot.py'
}
if (-not $LogDirectory) { $LogDirectory = Join-Path $taskProject 'local-data/llm-pilot' }

$taskWritable = @('ml/models', 'ml/adapters', 'ml/runs', 'ml/datasets/raw',
                  'ml/datasets/curated', 'ml/datasets/splits')
foreach ($taskDirectory in $taskWritable) {
  New-Item -ItemType Directory -Force -Path (Join-Path $taskProject $taskDirectory) | Out-Null
}
foreach ($taskDirectory in @($CachePath, (Join-Path $CachePath 'tmp'),
                             (Join-Path $CachePath 'hf'), (Join-Path $CachePath 'pip'),
                             $LogDirectory)) {
  New-Item -ItemType Directory -Force -Path $taskDirectory | Out-Null
}
$taskCache = (Resolve-Path -LiteralPath $CachePath).Path
$taskLogs = (Resolve-Path -LiteralPath $LogDirectory).Path

# Уникальное имя исключает перезапись диагностического лога или квитанции.
$taskRunId = '{0}-{1}-{2}' -f $Step, (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssfffZ'),
  ([guid]::NewGuid().ToString('N').Substring(0, 8))
$taskLog = Join-Path $taskLogs "$taskRunId.log"
$taskReceiptPath = Join-Path $taskLogs "$taskRunId-receipt.json"
$taskLogFile = [System.IO.File]::Open($taskLog, [System.IO.FileMode]::CreateNew,
                                      [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
$taskLogFile.Dispose()

$taskImage = 'hermes-dashboard-fastapi:latest'
$taskContainer = "fsp-llm-$taskRunId"
$taskDockerArguments = @('run', '--rm', '--pull', 'never', '--log-driver', 'none',
  '--name', $taskContainer, '--gpus', 'all', '--cpus', '8', '--memory', '12g',
  '--shm-size', '512m', '--pids-limit', '256', '--read-only', '--cap-drop', 'ALL',
  '--security-opt', 'no-new-privileges:true',
  '--mount', "type=bind,source=$taskProject,target=/workspace/Fsp,readonly",
  '--mount', "type=bind,source=$taskCache,target=/cache",
  '-w', '/workspace/Fsp', '-e', 'PYTHONPATH=/cache/site-packages:/workspace/Fsp',
  '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'TMPDIR=/cache/tmp',
  '-e', 'HF_HOME=/cache/hf', '-e', 'PIP_CACHE_DIR=/cache/pip',
  '-e', 'TRITON_CACHE_DIR=/cache/triton',
  '-e', 'TORCHINDUCTOR_CACHE_DIR=/cache/torchinductor', '-e', 'CUDA_CACHE_PATH=/cache/cuda',
  '-e', 'OMP_NUM_THREADS=8', '-e', 'HF_HUB_DISABLE_XET=1')
foreach ($taskDirectory in $taskWritable) {
  $taskSource = Join-Path $taskProject $taskDirectory
  $taskTarget = '/workspace/Fsp/' + ($taskDirectory -replace '\\', '/')
  $taskDockerArguments += @('--mount', "type=bind,source=$taskSource,target=$taskTarget")
}
if (-not $Online) { $taskDockerArguments += @('--network', 'none', '-e', 'HF_HUB_OFFLINE=1') }
$taskDockerArguments += @('--entrypoint', $Interpreter, $taskImage)
$taskDockerArguments += $PythonArguments

$taskStarted = [DateTime]::UtcNow
$taskExit = -1
try {
  & docker @taskDockerArguments *>> $taskLog
  $taskExit = $LASTEXITCODE
} catch {
  # В журнал попадает только диагностическое сообщение, аргументы с возможными
  # приватными путями и содержимым запроса не записываются в квитанцию.
  Add-Content -LiteralPath $taskLog -Value $_.Exception.Message
}
$taskFinished = [DateTime]::UtcNow
$taskReceipt = [ordered]@{
  step = $Step
  started_utc = $taskStarted.ToString('o')
  finished_utc = $taskFinished.ToString('o')
  seconds = ($taskFinished - $taskStarted).TotalSeconds
  exit_code = $taskExit
  log = $taskLog
  image = $taskImage
  container = $taskContainer
  online = [bool]$Online
}
$taskReceiptJson = $taskReceipt | ConvertTo-Json -Depth 4
$taskBytes = [System.Text.UTF8Encoding]::new($false).GetBytes($taskReceiptJson + "`n")
$taskReceiptFile = [System.IO.File]::Open($taskReceiptPath, [System.IO.FileMode]::CreateNew,
                                          [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
try { $taskReceiptFile.Write($taskBytes, 0, $taskBytes.Length) }
finally { $taskReceiptFile.Dispose() }
if ($taskExit -ne 0) { throw "GPU step $Step failed; см. $taskLog" }
$taskReceipt | ConvertTo-Json -Compress
