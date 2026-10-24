# Run Elle over exported histories.
#   -Java   path to a Java 21+ java.exe
#   -Jar    elle-cli-0.1.11-standalone.jar (built from github.com/ligurio/elle-cli, commit 9c2a18b)
#   -Clj    elle_check.clj
#   -Root   folder with one sub-folder per workload, each containing h\*.edn and index.csv
# For each workload it writes four result files next to index.csv:
#   elle_cli_default.txt   unmodified elle-cli:  -m rw-register  (defaults: strict-serializable)
#   elle_wfr.txt           Elle library, :wfr-keys? true
#   elle_lin.txt           Elle library, :linearizable-keys? true
#   elle_wfr_lin.txt       Elle library, both
param([string]$Java, [string]$Jar, [string]$Clj, [string]$Root, [int]$Parallel = 4)
$ErrorActionPreference = 'Stop'
$jobs = @()
foreach ($w in Get-ChildItem $Root -Directory) {
    $h = Join-Path $w.FullName 'h'
    $files = Get-ChildItem $h -Filter *.edn | Sort-Object Name | ForEach-Object { $_.Name }
    Set-Content -Encoding ascii (Join-Path $w.FullName 'list.txt') $files
    # elle-cli takes files as arguments: batches of 150 keep the command line short
    $cli = Join-Path $w.FullName 'run_cli.cmd'
    $lines = @('@echo off', "cd /d `"$h`"")
    for ($i = 0; $i -lt $files.Count; $i += 150) {
        $batch = $files[$i..([Math]::Min($i + 149, $files.Count - 1))] -join ' '
        $lines += "`"$Java`" -jar `"$Jar`" -m rw-register $batch"
    }
    Set-Content -Encoding ascii $cli $lines
    $jobs += , @($w.FullName, 'elle_cli_default.txt', 'cmd.exe', "/c `"$cli`"")
    foreach ($cfg in @(@('elle_wfr.txt', '{:consistency-models [:strict-serializable] :wfr-keys? true}'),
                       @('elle_lin.txt', '{:consistency-models [:strict-serializable] :linearizable-keys? true}'),
                       @('elle_wfr_lin.txt', '{:consistency-models [:strict-serializable] :wfr-keys? true :linearizable-keys? true}'))) {
        $c = Join-Path $w.FullName ('run_' + $cfg[0] + '.cmd')
        Set-Content -Encoding ascii $c @('@echo off', "cd /d `"$h`"", "`"$Java`" -cp `"$Jar`" clojure.main `"$Clj`" `"$($cfg[1])`" ..\list.txt")
        $jobs += , @($w.FullName, $cfg[0], 'cmd.exe', "/c `"$c`"")
    }
}
$running = @()
foreach ($j in $jobs) {
    while (@($running | Where-Object { -not $_.HasExited }).Count -ge $Parallel) { Start-Sleep -Seconds 2 }
    $out = Join-Path $j[0] $j[1]
    $running += Start-Process -FilePath $j[2] -ArgumentList $j[3] -RedirectStandardOutput $out -RedirectStandardError ($out + '.err') -NoNewWindow -PassThru
    "started $out"
}
$running | ForEach-Object { $_.WaitForExit() }
"all done"
