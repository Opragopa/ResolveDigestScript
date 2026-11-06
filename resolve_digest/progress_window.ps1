$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Resolve Digest'
$form.ClientSize = New-Object System.Drawing.Size(620, 340)
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$form.StartPosition = 'Manual'
$area = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$form.Location = New-Object System.Drawing.Point(($area.X + [int](($area.Width - $form.Width) / 2)), ($area.Y + [int](($area.Height - $form.Height) / 2)))

$heading = New-Object System.Windows.Forms.Label
$heading.SetBounds(20, 18, 580, 48)
$heading.Text = 'Подготовка выпуска…'
$heading.Font = New-Object System.Drawing.Font('Segoe UI', 12, [System.Drawing.FontStyle]::Bold)
$bar = New-Object System.Windows.Forms.ProgressBar
$bar.SetBounds(20, 74, 530, 24)
$percent = New-Object System.Windows.Forms.Label
$percent.SetBounds(555, 76, 55, 24)
$percent.Text = '0%'
$details = New-Object System.Windows.Forms.TextBox
$details.SetBounds(20, 114, 580, 160)
$details.Multiline = $true
$details.ReadOnly = $true
$details.ScrollBars = 'Vertical'
$details.TabStop = $true
$button = New-Object System.Windows.Forms.Button
$button.SetBounds(440, 290, 160, 32)
$button.Text = 'Отменить'
$form.Controls.AddRange(@($heading, $bar, $percent, $details, $button))
$script:finished = $false
$script:cancelSent = $false
$script:canCancel = $true

function Request-Cancel {
    if (-not $script:cancelSent -and $script:canCancel) {
        $script:cancelSent = $true
        [Console]::Out.WriteLine('CANCEL')
        [Console]::Out.Flush()
        $heading.Text = 'Отмена — ожидаем завершения текущего запроса…'
        $button.Enabled = $false
    }
}
$button.Add_Click({
    if ($script:finished) { $form.Close() } else { Request-Cancel }
})
$form.Add_FormClosing({
    param($sender, $eventArgs)
    if (-not $script:finished) {
        $eventArgs.Cancel = $true
        Request-Cancel
    }
})

# Async pipe reads keep the UI message loop free even during network waits.
$reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)
$script:pending = $reader.ReadLineAsync()
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 100
$timer.Add_Tick({
    try {
        # Drain all queued messages before painting the latest state.
        $count = 0
        while ($script:pending.IsCompleted -and $count -lt 100) {
            $line = $script:pending.GetAwaiter().GetResult()
            if ($null -eq $line) {
                $timer.Stop()
                if (-not $script:finished) {
                    $script:finished = $true
                    $heading.Text = 'Связь со скриптом прервана'
                    $details.Text = 'Проверьте консоль и журнал Resolve Digest.'
                    $button.Text = 'Закрыть'
                    $button.Enabled = $true
                }
                break
            }
            $state = $line | ConvertFrom-Json
            $bar.Value = [Math]::Max(0, [Math]::Min(100, [int]$state.percent))
            $percent.Text = [string]$bar.Value + '%'
            if (-not $script:cancelSent -or $state.status -ne 'working') {
                $heading.Text = [string]$state.message
                $details.Text = ([string]$state.detail).Replace("`n", "`r`n")
            }
            $script:canCancel = [bool]$state.cancellable
            if ($state.status -ne 'working') {
                $script:finished = $true
                $button.Text = 'Закрыть'
                $button.Enabled = $true
                if ($state.status -eq 'error') {
                    $heading.ForeColor = [System.Drawing.Color]::Firebrick
                }
                [Console]::Out.WriteLine('FINISHED')
                [Console]::Out.Flush()
            } else {
                $button.Enabled = $script:canCancel -and -not $script:cancelSent
            }
            $script:pending = $reader.ReadLineAsync()
            $count++
        }
    } catch {
        $timer.Stop()
        $script:finished = $true
        $heading.Text = 'Ошибка окна прогресса'
        $details.Text = $_.Exception.Message
        [Console]::Out.WriteLine('UI_ERROR: ' + $_.Exception.Message)
        [Console]::Out.Flush()
        $button.Text = 'Закрыть'
        $button.Enabled = $true
    }
})
$form.Add_Shown({
    $timer.Start()
    [Console]::Out.WriteLine('READY')
    [Console]::Out.Flush()
})
try { [System.Windows.Forms.Application]::Run($form) }
finally { $timer.Dispose(); $form.Dispose() }
