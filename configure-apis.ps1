param([switch]$NoRestart)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = 'QOSYU - API setup'
$form.Size = New-Object System.Drawing.Size(560, 365)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$intro = New-Object System.Windows.Forms.Label
$intro.Location = New-Object System.Drawing.Point(20, 15)
$intro.Size = New-Object System.Drawing.Size(510, 55)
$intro.Text = 'Paste your keys below. They are saved only in the local QOSYU .env file, never in chat. Leave a field empty to keep its existing value.'
$form.Controls.Add($intro)
$inputs = @{}
$row = 0
foreach ($entry in @(@('DGIS_API_KEY', '2GIS API key'), @('GEMINI_API_KEY', 'Google AI Studio / Gemini key'))) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $entry[1]
    $label.Location = New-Object System.Drawing.Point(20, (80 + $row * 75))
    $label.Size = New-Object System.Drawing.Size(505, 24)
    $form.Controls.Add($label)
    $inputBox = New-Object System.Windows.Forms.TextBox
    $inputBox.Location = New-Object System.Drawing.Point(20, (105 + $row * 75))
    $inputBox.Size = New-Object System.Drawing.Size(505, 28)
    $inputBox.UseSystemPasswordChar = $true
    $form.Controls.Add($inputBox)
    $inputs[$entry[0]] = $inputBox
    $row++
}
$feedback = New-Object System.Windows.Forms.Label
$feedback.Location = New-Object System.Drawing.Point(20, 225)
$feedback.Size = New-Object System.Drawing.Size(505, 38)
$feedback.Text = 'No API requests are sent by this window.'
$form.Controls.Add($feedback)
$save = New-Object System.Windows.Forms.Button
$save.Text = 'Save and connect'
$save.Location = New-Object System.Drawing.Point(325, 270)
$save.Size = New-Object System.Drawing.Size(200, 36)
$form.Controls.Add($save)
$form.AcceptButton = $save
$save.Add_Click({
    $save.Enabled = $false
    try {
        $envFile = Join-Path $PSScriptRoot '.env'
        if (-not (Test-Path -LiteralPath $envFile)) { throw 'Local configuration file not found.' }
        $values = @{}
        foreach ($keyName in $inputs.Keys) {
            $value = $inputs[$keyName].Text.Trim()
            if ($value) {
                if ($value -notmatch '^[A-Za-z0-9._-]{20,200}$') { throw 'Check the key format. Nothing was changed.' }
                $values[$keyName] = $value
            }
        }
        if ($values.Count -eq 0) { throw 'Enter at least one API key.' }
        $values['AI_PROVIDER'] = 'gemini'
        $existing = [IO.File]::ReadAllLines($envFile)
        if (-not ($existing -match '^\s*GEMINI_MODEL\s*=')) { $values['GEMINI_MODEL'] = 'gemini-3.5-flash-lite' }
        $keep = @($existing | Where-Object {
            if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=') { -not $values.ContainsKey($Matches[1]) } else { $true }
        })
        foreach ($keyName in $values.Keys) { $keep += ($keyName + '=' + $values[$keyName]) }
        [IO.File]::WriteAllLines($envFile, $keep, [Text.UTF8Encoding]::new($false))
        foreach ($inputBox in $inputs.Values) { $inputBox.Clear() }
        $values.Clear()
        if (-not $NoRestart) {
            $feedback.Text = 'Saved. Reconnecting the local server...'
            $form.Refresh()
            Push-Location -LiteralPath $PSScriptRoot
            try {
                $ErrorActionPreference = 'Continue'
                docker compose up -d backend 2>&1 | Out-Null
                $ErrorActionPreference = 'Stop'
                if ($LASTEXITCODE -ne 0) { throw 'Keys saved. Start Docker Desktop, then run start-qosyu.ps1.' }
            } finally { Pop-Location }
        }
        $feedback.Text = 'Saved. Refresh localhost:8080. API validity is checked when you use a service.'
    } catch {
        $feedback.Text = 'Could not complete setup. Check the key format and that Docker Desktop is running.'
    } finally { $save.Enabled = $true }
})
[void]$form.ShowDialog()
$form.Dispose()
