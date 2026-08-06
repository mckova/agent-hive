param(
  [Parameter(Mandatory = $true)][string]$RunRoot,
  [string]$Model = "gpt-5.5",
  [ValidateSet("normal", "caveman", "ralph", "loop-engineering", "agent-hive")]
  [string[]]$OnlyArm = @()
)

$ErrorActionPreference = "Stop"
$RunRoot = [System.IO.Path]::GetFullPath($RunRoot)
if (-not (Test-Path -LiteralPath (Join-Path $RunRoot "provenance.json"))) {
  throw "Run root was not prepared: $RunRoot"
}

Remove-Item Env:CODEX_SANDBOX_NETWORK_DISABLED -ErrorAction SilentlyContinue
Remove-Item Env:CODEX_THREAD_ID -ErrorAction SilentlyContinue
$allRuns = [System.Collections.Generic.List[object]]::new()
$selectedArms = if ($OnlyArm.Count -gt 0) { $OnlyArm } else { @("normal", "caveman", "ralph", "loop-engineering", "agent-hive") }

function Invoke-CodexPhase {
  param([string]$Arm, [string]$Phase, [string]$Prompt)
  $armDirectory = Join-Path $RunRoot $Arm
  $benchDirectory = Join-Path $armDirectory ".bench"
  New-Item -ItemType Directory -Force -Path $benchDirectory | Out-Null
  $stderrPath = Join-Path $benchDirectory "$Phase.stderr.log"
  $jsonlPath = Join-Path $benchDirectory "$Phase.events.jsonl"
  $messagePath = Join-Path $benchDirectory "$Phase.final.md"
  $timer = [System.Diagnostics.Stopwatch]::StartNew()
  $previousErrorPreference = $ErrorActionPreference
  Push-Location $armDirectory
  try {
    $ErrorActionPreference = "Continue"
    $rawLines = @($Prompt | & codex exec --skip-git-repo-check --ephemeral -s workspace-write -m $Model -c service_tier='fast' -c model_reasoning_effort='medium' --json - 2> $stderrPath)
    $exitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previousErrorPreference
    Pop-Location
    $timer.Stop()
  }
  [System.IO.File]::WriteAllLines($jsonlPath, [string[]]$rawLines, [System.Text.UTF8Encoding]::new($false))
  $events = foreach ($line in $rawLines) {
    try { $line | ConvertFrom-Json -ErrorAction Stop } catch { }
  }
  $turn = $events | Where-Object { $_.type -eq "turn.completed" } | Select-Object -Last 1
  $messages = $events | Where-Object { $_.type -eq "item.completed" -and $_.item.type -eq "agent_message" } | ForEach-Object { $_.item.text }
  $message = ($messages -join "`n")
  [System.IO.File]::WriteAllText($messagePath, $message, [System.Text.UTF8Encoding]::new($false))
  $inputTokens = if ($null -ne $turn.usage.input_tokens) { [int64]$turn.usage.input_tokens } else { 0 }
  $cachedInputTokens = if ($null -ne $turn.usage.cached_input_tokens) { [int64]$turn.usage.cached_input_tokens } else { 0 }
  $outputTokens = if ($null -ne $turn.usage.output_tokens) { [int64]$turn.usage.output_tokens } else { 0 }
  $reasoningOutputTokens = if ($null -ne $turn.usage.reasoning_output_tokens) { [int64]$turn.usage.reasoning_output_tokens } else { 0 }
  $result = [pscustomobject]@{
    arm = $Arm
    phase = $Phase
    exitCode = $exitCode
    elapsedMs = $timer.ElapsedMilliseconds
    inputTokens = $inputTokens
    cachedInputTokens = $cachedInputTokens
    outputTokens = $outputTokens
    reasoningOutputTokens = $reasoningOutputTokens
    finalMessage = $message
  }
  $script:allRuns.Add($result)
  Write-Host ("{0}/{1}: exit={2}, input={3}, cached={4}, output={5}, reasoning={6}, ms={7}" -f $Arm,$Phase,$exitCode,$result.inputTokens,$result.cachedInputTokens,$result.outputTokens,$result.reasoningOutputTokens,$result.elapsedMs)
  return $result
}

$common = @"
עבדי רק בתיקייה הנוכחית. אל תקראי תיקיות אב או sibling ואל תחפשי grader נסתר.
קראי את TASK.md, ממשי את כל הדרישות ב-src/rate_limiter.py, והריצי python -m unittest discover -s checks -v.
אל תשני checks/. בדקי את העבודה לפני סיום ודווחי בקצרה על הראיות.
"@

if ($selectedArms -contains "normal") {
  Invoke-CodexPhase -Arm "normal" -Phase "implement" -Prompt $common | Out-Null
}

$cavemanPrompt = @"
קראי תחילה את .agents/skills/caveman/SKILL.md במלואו ופעלי לפיו ברמת full.
$common
"@
if ($selectedArms -contains "caveman") {
  Invoke-CodexPhase -Arm "caveman" -Phase "implement" -Prompt $cavemanPrompt | Out-Null
}

$ralphPrompt = @"
עבדי רק בתיקייה הנוכחית ואל תקראי תיקיות אב או sibling.
קראי .agent/BENCHMARK_PROMPT.md, .agent/tasks.json ואת קובץ המשימה המתאים.
בצעי invocation אחד בלבד לפי שיטת Ralph וסיימי בתג המוגדר. אין git ב-fixture הזה.
"@
if ($selectedArms -contains "ralph") {
  Invoke-CodexPhase -Arm "ralph" -Phase "iteration-1" -Prompt $ralphPrompt | Out-Null
  Invoke-CodexPhase -Arm "ralph" -Phase "iteration-2" -Prompt $ralphPrompt | Out-Null
}

$loopMaker = @"
עבדי רק בתיקייה הנוכחית ואל תקראי תיקיות אב או sibling.
קראי TASK.md, LOOP.md, STATE.md, loop-budget.md, loop-constraints.md ואת .agents/skills/minimal-fix/SKILL.md.
פעלי כ-maker: ממשי את המשימה ב-src/rate_limiter.py בלבד, הריצי python -m unittest discover -s checks -v, ועדכני STATE.md ל-awaiting_verification. אל תסמני את עבודתך כמאושרת.
"@
if ($selectedArms -contains "loop-engineering") {
Invoke-CodexPhase -Arm "loop-engineering" -Phase "maker" -Prompt $loopMaker | Out-Null
$loopVerifier = @"
עבדי רק בתיקייה הנוכחית ואל תקראי תיקיות אב או sibling.
קראי TASK.md, LOOP.md, STATE.md, loop-constraints.md ואת .agents/skills/loop-verifier/SKILL.md.
פעלי כ-checker עצמאי. בדקי את הקוד בפועל, הריצי python -m unittest discover -s checks -v, והשווי כל דרישה. אל תשני קוד. החזירי Verdict לפי הסקיל.
"@
$loopVerdict = Invoke-CodexPhase -Arm "loop-engineering" -Phase "verifier" -Prompt $loopVerifier
if ($loopVerdict.finalMessage -match "(?im)^## Verdict:\s*REJECT\b") {
  $loopRepair = @"
עבדי רק בתיקייה הנוכחית. קראי TASK.md, loop-constraints.md, .agents/skills/minimal-fix/SKILL.md ואת .bench/verifier.final.md.
זהו repair attempt אחרון. תקני רק את הליקויים הספציפיים, הריצי python -m unittest discover -s checks -v ועדכני STATE.md. אל תקראי תיקיות אב או sibling.
"@
  Invoke-CodexPhase -Arm "loop-engineering" -Phase "repair" -Prompt $loopRepair | Out-Null
  Invoke-CodexPhase -Arm "loop-engineering" -Phase "verifier-2" -Prompt $loopVerifier | Out-Null
}
}

$hiveSurvey = @"
עבדי רק בתיקייה הנוכחית. קראי TASK.md, .hive/payloads/survey.hive ואת .bench/run-agent-hive/references/worker-roles.md.
בצעי scout read-only: מפה דרישות, edge cases וסיכוני security. כתבי רק את המפה ל-.hive/survey.md; אל תשני source/tests. אל תקראי תיקיות אב או sibling.
"@
if ($selectedArms -contains "agent-hive") {
if (Test-Path -LiteralPath (Join-Path $RunRoot "agent-hive\.hive\payloads\survey.hive")) {
$survey = Invoke-CodexPhase -Arm "agent-hive" -Phase "survey" -Prompt $hiveSurvey
$surveyUsed = $survey.inputTokens + $survey.outputTokens + $survey.reasoningOutputTokens
& python "$PSScriptRoot\..\..\..\hive.py" record survey --status done --used $surveyUsed --artifact .hive/survey.md --evidence "scout completed" --plan "$RunRoot\agent-hive\.hive\plan.json" --usage "$RunRoot\agent-hive\.hive\usage.json" | Out-Null
}

$hiveBuild = @"
עבדי רק בתיקייה הנוכחית. קראי TASK.md, .hive/payloads/build.hive ו-.hive/survey.md.
בצעי builder cell: ממשי רק src/rate_limiter.py, אל תשני checks, הריצי python -m unittest discover -s checks -v והחזירי status/artifacts/evidence/blockers/spent/reusable_context. אל תקראי תיקיות אב או sibling.
"@
$build = Invoke-CodexPhase -Arm "agent-hive" -Phase "build" -Prompt $hiveBuild
$buildUsed = $build.inputTokens + $build.outputTokens + $build.reasoningOutputTokens
& python "$PSScriptRoot\..\..\..\hive.py" record build --status done --used $buildUsed --artifact src/rate_limiter.py --evidence "public tests" --plan "$RunRoot\agent-hive\.hive\plan.json" --usage "$RunRoot\agent-hive\.hive\usage.json" | Out-Null

$hiveGuard = @"
עבדי רק בתיקייה הנוכחית. קראי TASK.md, .hive/payloads/verify.hive, .hive/survey.md ואת הקוד בפועל.
פעלי כ-guard עצמאי read-only. הריצי python -m unittest discover -s checks -v, אמתִי כל דרישה, security ו-scope. החזירי status: done רק אם הכול תקין; אחרת status: partial עם blockers מדויקים. אל תשני קוד ואל תקראי תיקיות אב או sibling.
"@
$guard = Invoke-CodexPhase -Arm "agent-hive" -Phase "guard" -Prompt $hiveGuard
if ($guard.finalMessage -notmatch "status:\s*done") {
  $hiveRepair = @"
עבדי רק בתיקייה הנוכחית. קראי TASK.md, .hive/payloads/build.hive ואת .bench/guard.final.md.
בצעי repair ממוקד של blockers בלבד ב-src/rate_limiter.py, הריצי python -m unittest discover -s checks -v והחזירי חוזה HIVE/1. אל תקראי תיקיות אב או sibling.
"@
  Invoke-CodexPhase -Arm "agent-hive" -Phase "repair" -Prompt $hiveRepair | Out-Null
  $guard = Invoke-CodexPhase -Arm "agent-hive" -Phase "guard-2" -Prompt $hiveGuard
}
$guardUsed = $guard.inputTokens + $guard.outputTokens + $guard.reasoningOutputTokens
$guardStatus = if ($guard.finalMessage -match "status:\s*done") { "done" } else { "partial" }
& python "$PSScriptRoot\..\..\..\hive.py" record verify --status $guardStatus --used $guardUsed --evidence "guard completed" --plan "$RunRoot\agent-hive\.hive\plan.json" --usage "$RunRoot\agent-hive\.hive\usage.json" | Out-Null
}

$summaries = $allRuns | Group-Object arm | ForEach-Object {
  [pscustomobject]@{
    arm = $_.Name
    turns = $_.Count
    elapsedMs = ($_.Group | Measure-Object elapsedMs -Sum).Sum
    inputTokens = ($_.Group | Measure-Object inputTokens -Sum).Sum
    cachedInputTokens = ($_.Group | Measure-Object cachedInputTokens -Sum).Sum
    outputTokens = ($_.Group | Measure-Object outputTokens -Sum).Sum
    reasoningOutputTokens = ($_.Group | Measure-Object reasoningOutputTokens -Sum).Sum
    successfulTurns = @($_.Group | Where-Object exitCode -eq 0).Count
  }
}
$measurement = [pscustomobject]@{
  schemaVersion = 1
  generatedAt = (Get-Date).ToUniversalTime().ToString("o")
  model = $Model
  phases = $allRuns
  arms = $summaries
}
$measurement | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $RunRoot "measurements.json") -Encoding utf8
$summaries | Format-Table -AutoSize
