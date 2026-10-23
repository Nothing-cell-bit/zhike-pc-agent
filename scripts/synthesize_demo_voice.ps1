$ErrorActionPreference='Stop'
$voiceRoot=Split-Path -Parent $PSScriptRoot
$voiceOut=Join-Path $voiceRoot 'output\competition-video-voice-20261023'
$voicePlan=Get-Content -LiteralPath (Join-Path $voiceOut 'voice-plan.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$demoSpeaker=New-Object System.Speech.Synthesis.SpeechSynthesizer
$demoSpeaker.SelectVoice('Microsoft Huihui Desktop')
$demoSpeaker.Rate=1
$demoSpeaker.Volume=100
try {
 foreach($line in $voicePlan) {
  $voiceFile=Join-Path $voiceOut ('voice-{0:D2}.wav' -f [int]$line.index)
  $demoSpeaker.SetOutputToWaveFile($voiceFile)
  $demoSpeaker.Speak([string]$line.narration)
  $demoSpeaker.SetOutputToNull()
 }
} finally {$demoSpeaker.Dispose()}
Write-Output '25 Chinese narration clips synthesized'
