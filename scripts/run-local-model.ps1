param(
  [Parameter(Mandatory = $true, Position = 0)]
  [ValidateSet('start', 'status', 'stop')]
  [string]$Action,
  [string]$ProjectPath,
  [string]$CachePath = 'D:/Codex/Caches/fsp-llm',
  [string]$ModelDirectory,
  [string]$ManifestPath,
  [string]$AdapterDirectory,
  [string]$AdapterManifestPath,
  [string]$APIKeyFile,
  [ValidateRange(0, 65535)]
  [int]$LoopbackPort = 0
)

$ErrorActionPreference = 'Stop'
if ($Action -eq 'start' -and $APIKeyFile) {
  $taskKeyFile = (Resolve-Path -LiteralPath $APIKeyFile).Path
  $taskKeyContent = [System.IO.File]::ReadAllText($taskKeyFile).Trim()
  if ($taskKeyContent -notmatch '^FSP_LOCAL_MODEL_API_KEY=([A-Za-z0-9_+/=-]{32,256})$') {
    throw 'Файл должен содержать только одну непустую строку FSP_LOCAL_MODEL_API_KEY допустимой длины'
  }
  if ($env:FSP_LOCAL_MODEL_API_KEY -and $env:FSP_LOCAL_MODEL_API_KEY -cne $Matches[1]) {
    throw 'Ключ окружения не совпадает с файлом; запуск остановлен без вывода значений'
  }
  $taskKeyContent = $null
}
if ($LoopbackPort -gt 0 -and -not $env:FSP_LOCAL_MODEL_API_KEY -and -not $APIKeyFile) {
  throw 'Для loopback-доступа задайте FSP_LOCAL_MODEL_API_KEY; ключ не выводится в журнал.'
}
if ($Action -eq 'start' -and $LoopbackPort -gt 0 -and $env:FSP_LOCAL_MODEL_API_KEY -and
    $env:FSP_LOCAL_MODEL_API_KEY -notmatch '^[A-Za-z0-9_+/=-]{32,256}$') {
  throw 'Ключ окружения для loopback должен содержать 32–256 допустимых символов'
}
if (-not $ProjectPath) { $ProjectPath = Split-Path -Parent $PSScriptRoot }
$taskProject = (Resolve-Path -LiteralPath $ProjectPath).Path
if (-not $ModelDirectory) {
  $ModelDirectory = Join-Path $taskProject 'ml/models/qwen3-4b-instruct-2507-serving-v3'
}
if (-not $ManifestPath) {
  $ManifestPath = Join-Path $taskProject 'ml/release/model-serving-v3-manifest.json'
}
if (-not (Test-Path -LiteralPath (Join-Path $taskProject 'ml/local_model.py') -PathType Leaf)) {
  throw 'ProjectPath должен указывать на FSP с ml/local_model.py'
}

# Имя привязано к рабочей копии: stop не может затронуть соседний проект.
$taskBytes = [System.Text.Encoding]::UTF8.GetBytes($taskProject.ToLowerInvariant())
$taskSha = [System.Security.Cryptography.SHA256]::Create()
$taskHashBytes = $taskSha.ComputeHash($taskBytes)
$taskHash = (($taskHashBytes | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 10)
$taskContainer = "fsp-local-model-$taskHash"
$taskNetwork = "fsp-local-model-net-qwen3-$taskHash"
$taskLabel = 'fsp.local-model.owner'
$taskOwner = "qwen3-4b-$taskHash"

function Get-TaskContainer {
  $taskNames = @(docker container ls -a --filter "name=^/$taskContainer`$" --format '{{.Names}}')
  if ($LASTEXITCODE -ne 0) { throw 'Не удалось проверить контейнеры Docker' }
  if ($taskNames -notcontains $taskContainer) { return $null }
  $taskValue = docker container inspect $taskContainer --format '{{json .Config.Labels}}'
  if ($LASTEXITCODE -ne 0) { throw 'Не удалось проверить метки контейнера' }
  $taskLabels = $taskValue | ConvertFrom-Json
  if ($taskLabels.$taskLabel -ne $taskOwner) {
    throw 'Контейнер с таким именем принадлежит другой задаче'
  }
  return $taskContainer
}

$taskExisting = Get-TaskContainer
if ($Action -eq 'stop') {
  if ($taskExisting) {
    & docker stop --time 10 $taskContainer | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось остановить контейнер модели' }
  }
  [pscustomobject]@{ container = $taskContainer; status = 'stopped' } | ConvertTo-Json -Compress
  exit 0
}

if ($Action -eq 'status') {
  if (-not $taskExisting) {
    [pscustomobject]@{ container = $taskContainer; status = 'stopped' } | ConvertTo-Json -Compress
    exit 0
  }
  $taskState = docker container inspect $taskContainer --format '{{.State.Status}}'
  if ($LASTEXITCODE -ne 0) { throw 'Не удалось получить состояние контейнера' }
  $taskReady = $false
  if ($taskState -eq 'running') {
    try {
      $taskHealthJson = docker exec $taskContainer /usr/local/bin/python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health',timeout=3).read().decode())" 2>$null
      if ($LASTEXITCODE -eq 0) {
        $taskHealth = $taskHealthJson | ConvertFrom-Json
        $taskReady = $taskHealth.status -eq 'ready'
      }
    } catch { $taskReady = $false }
  }
  [pscustomobject]@{ container = $taskContainer; status = $taskState;
                     ready = $taskReady; network = $taskNetwork;
                     url = "http://${taskContainer}:8001/v1" } | ConvertTo-Json -Compress
  exit 0
}

if ($taskExisting) { throw 'Контейнер модели уже существует; проверьте status или выполните stop' }

$taskCacheFull = [System.IO.Path]::GetFullPath($CachePath)
if ([System.IO.Path]::GetPathRoot($taskCacheFull) -notmatch '^D:\\$') {
  throw 'Кэш модели должен находиться на диске D'
}
New-Item -ItemType Directory -Path $taskCacheFull -Force | Out-Null
$taskCache = (Resolve-Path -LiteralPath $taskCacheFull).Path
$taskModel = (Resolve-Path -LiteralPath $ModelDirectory).Path
$taskManifest = (Resolve-Path -LiteralPath $ManifestPath).Path
foreach ($taskPath in @($taskProject, $taskCache, $taskModel, $taskManifest)) {
  if ([System.IO.Path]::GetPathRoot($taskPath) -notmatch '^D:\\$') {
    throw 'Проект, кэш, модель и manifest должны находиться на диске D'
  }
}
if (-not (Test-Path -LiteralPath $taskModel -PathType Container) -or
    -not (Test-Path -LiteralPath $taskManifest -PathType Leaf)) {
  throw 'Каталог serving-модели или manifest отсутствует'
}
if ($taskManifest.StartsWith($taskModel + [System.IO.Path]::DirectorySeparatorChar,
                             [System.StringComparison]::OrdinalIgnoreCase)) {
  throw 'Manifest должен находиться вне каталога модели'
}
$taskManifestData = Get-Content -LiteralPath $taskManifest -Raw -Encoding UTF8 | ConvertFrom-Json
if ($taskManifestData.model_id -ne 'Qwen/Qwen3-4B-Instruct-2507' -or
    $taskManifestData.revision -ne 'cdbee75f17c01a7cc42f958dc650907174af0554') {
  throw 'Manifest должен указывать закреплённую Qwen3-4B-Instruct-2507'
}
& docker build --file (Join-Path $taskProject 'docker/model.Dockerfile') --tag fsp-model $taskProject
if ($LASTEXITCODE -ne 0) { throw 'Не удалось собрать собственный образ fsp-model' }

$taskNetworkIds = @(docker network ls --filter "name=^$taskNetwork`$" --format '{{.Name}}')
if ($LASTEXITCODE -ne 0) { throw 'Не удалось проверить Docker-сети' }
if ($taskNetworkIds -contains $taskNetwork) {
  $taskNetworkValue = docker network inspect $taskNetwork --format '{{json .}}' | ConvertFrom-Json
  if ($LASTEXITCODE -ne 0 -or -not $taskNetworkValue.Internal -or
      $taskNetworkValue.Driver -ne 'bridge' -or
      $taskNetworkValue.Labels.$taskLabel -ne $taskOwner) {
    throw 'Сеть с таким именем не соответствует частной сети этой задачи'
  }
} else {
  & docker network create --driver bridge --internal --label "$taskLabel=$taskOwner" $taskNetwork | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать частную Docker-сеть' }
}
$taskPrimaryNetwork = $taskNetwork
if ($LoopbackPort -gt 0) {
  # Публикация loopback не работает в сети internal без шлюза. Отдельная
  # bridge-сеть нужна только для этого режима; bind всегда 127.0.0.1.
  $taskLoopbackNetwork = "$taskNetwork-loopback"
  $taskLoopbackNames = @(docker network ls --filter "name=^$taskLoopbackNetwork`$" --format '{{.Name}}')
  if ($taskLoopbackNames -contains $taskLoopbackNetwork) {
    $taskLoopbackValue = docker network inspect $taskLoopbackNetwork --format '{{json .}}' | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $taskLoopbackValue.Internal -or $taskLoopbackValue.Driver -ne 'bridge' -or
        $taskLoopbackValue.Labels.$taskLabel -ne $taskOwner) { throw 'Loopback-сеть принадлежит другой задаче' }
  } else {
    & docker network create --driver bridge --label "$taskLabel=$taskOwner" $taskLoopbackNetwork | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать loopback-сеть' }
  }
  $taskPrimaryNetwork = $taskLoopbackNetwork
}

$taskDiagnosticsRoot = Join-Path $taskProject 'local-data/llm-model'
New-Item -ItemType Directory -Path $taskDiagnosticsRoot -Force | Out-Null
$taskRunId = 'start-{0}-{1}' -f [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'),
                         [guid]::NewGuid().ToString('N')
$taskDiagnostics = Join-Path $taskDiagnosticsRoot $taskRunId
New-Item -ItemType Directory -Path $taskDiagnostics -ErrorAction Stop | Out-Null
$taskDiagnostics = (Resolve-Path -LiteralPath $taskDiagnostics).Path
if ([System.IO.Path]::GetPathRoot($taskDiagnostics) -notmatch '^D:\\$') {
  throw 'Диагностический каталог должен находиться на диске D'
}
$taskReport = Join-Path $taskDiagnostics 'startup.json'
$taskGpuCache = Join-Path $taskCache 'gpu-serving'
New-Item -ItemType Directory -Path $taskGpuCache -Force | Out-Null

$taskArguments = @('run', '-d', '--rm', '--pull', 'never', '--log-driver', 'none',
  '--name', $taskContainer, '--label', "$taskLabel=$taskOwner",
  '--network', $taskPrimaryNetwork,
  '--gpus', 'all', '--cpus', '8', '--memory', '12g', '--pids-limit', '256',
  '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
  '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=512m',
  '--mount', "type=bind,source=$taskGpuCache,target=/gpu-cache",
  '--mount', "type=bind,source=$taskModel,target=/model,readonly",
  '--mount', "type=bind,source=$taskManifest,target=/model-manifest.json,readonly",
  '--mount', "type=bind,source=$taskDiagnostics,target=/diagnostics",
  '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'TMPDIR=/tmp',
  '-e', 'OMP_NUM_THREADS=8',
  '-e', 'TRITON_CACHE_DIR=/gpu-cache/triton',
  '-e', 'TORCHINDUCTOR_CACHE_DIR=/gpu-cache/torchinductor', '-e', 'CUDA_CACHE_PATH=/gpu-cache/cuda',
  '-e', 'HF_HOME=/tmp/hf', '-e', 'HF_HUB_OFFLINE=1',
  '-e', 'TRANSFORMERS_OFFLINE=1', '-e', 'HF_HUB_DISABLE_TELEMETRY=1',
  '-e', 'FSP_LOCAL_MODEL_PATH=/model',
  '-e', 'FSP_LOCAL_MODEL_MANIFEST=/model-manifest.json',
  '-e', 'FSP_LOCAL_MODEL_STARTUP_REPORT=/diagnostics/startup.json')
if ($LoopbackPort -gt 0) {
  $taskArguments += @('--publish', "127.0.0.1:${LoopbackPort}:8001")
}
if ($APIKeyFile) {
  $taskKeyFile = (Resolve-Path -LiteralPath $APIKeyFile).Path
  if ([System.IO.Path]::GetPathRoot($taskKeyFile) -notmatch '^D:\\$') { throw 'Файл ключа должен находиться на диске D' }
  $taskArguments += @('--env-file', $taskKeyFile)
}
if ($AdapterDirectory) {
  # LoRA-адаптер: только чтение, сверка SHA-256 по manifest выполняется внутри сервиса.
  $taskAdapter = (Resolve-Path -LiteralPath $AdapterDirectory).Path
  $taskAdapterManifest = (Resolve-Path -LiteralPath $AdapterManifestPath).Path
  foreach ($taskPath in @($taskAdapter, $taskAdapterManifest)) {
    if ([System.IO.Path]::GetPathRoot($taskPath) -notmatch '^D:\\$') { throw 'Адаптер и manifest должны находиться на диске D' }
  }
  $taskArguments += @('--mount', "type=bind,source=$taskAdapter,target=/adapter,readonly",
    '--mount', "type=bind,source=$taskAdapterManifest,target=/adapter-manifest.json,readonly",
    '-e', 'FSP_LOCAL_ADAPTER_PATH=/adapter', '-e', 'FSP_LOCAL_ADAPTER_MANIFEST=/adapter-manifest.json')
}
if ($env:FSP_LOCAL_MODEL_API_KEY) {
  # Docker берёт значение из окружения PowerShell, оно не попадает в командную строку.
  $taskArguments += @('-e', 'FSP_LOCAL_MODEL_API_KEY')
}
$taskArguments += @('fsp-model')
& docker @taskArguments | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Не удалось запустить локальный сервис модели. Отчёт: $taskReport" }
if ($LoopbackPort -gt 0) {
  & docker network connect $taskNetwork $taskContainer
  if ($LASTEXITCODE -ne 0) { throw 'Не удалось подключить модель к частной проектной сети' }
}
[pscustomobject]@{ container = $taskContainer; status = 'starting';
                   network = $taskNetwork; url = "http://${taskContainer}:8001/v1";
                   startup_report = $taskReport } | ConvertTo-Json -Compress
