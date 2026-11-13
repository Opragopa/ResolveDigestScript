$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)
$prefs = $reader.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Resolve Digest — настройки выпуска'
$form.ClientSize = New-Object System.Drawing.Size(640, 450)
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$form.StartPosition = 'Manual'
$area = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$form.Location = New-Object System.Drawing.Point(($area.X + [int](($area.Width - $form.Width) / 2)), ($area.Y + [int](($area.Height - $form.Height) / 2)))
$label = New-Object System.Windows.Forms.Label
$label.Text = 'Документ с пятью новостями'
$label.SetBounds(20, 18, 590, 24)
$path = New-Object System.Windows.Forms.TextBox
$path.SetBounds(20, 46, 490, 28)
$path.Text = [string]$prefs.docx
$browse = New-Object System.Windows.Forms.Button
$browse.Text = 'Выбрать…'
$browse.SetBounds(520, 44, 100, 30)
$browse.Add_Click({
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Filter = 'Документы Word (*.docx)|*.docx'
    if ($dialog.ShowDialog($form) -eq 'OK') { $path.Text = $dialog.FileName }
    $dialog.Dispose()
})
$gapLabel = New-Object System.Windows.Forms.Label
$gapLabel.Text = 'Отступ title → body, пикселей исходного кадра'
$gapLabel.SetBounds(20, 98, 450, 24)
$gap = New-Object System.Windows.Forms.NumericUpDown
$gap.SetBounds(500, 94, 120, 28)
$gap.Minimum = 0
$gap.Maximum = 1000
$gap.Increment = 10
$gap.Value = [Math]::Max(0, [Math]::Min(1000, [decimal]$prefs.body_gap_pixels))
$only = New-Object System.Windows.Forms.CheckBox
$only.Text = 'Только переверстать текст — без DOCX и скачивания'
$only.SetBounds(20, 142, 600, 28)
$only.Add_CheckedChanged({ $path.Enabled = -not $only.Checked; $browse.Enabled = -not $only.Checked })
$only.Checked = [bool]$prefs.layout_only
$path.Enabled = -not $only.Checked
$browse.Enabled = -not $only.Checked
$update = New-Object System.Windows.Forms.CheckBox
$update.Text = 'Проверять обновления с GitHub при запуске скрипта'
$update.SetBounds(20, 185, 600, 28)
$update.Checked = [bool]$prefs.auto_update
$help = New-Object System.Windows.Forms.Label
$help.Text = 'Текст останется между верхним и нижним краями фото. Если места не хватит, размер шрифта будет уменьшен.'
$help.SetBounds(20, 230, 600, 48)
$version = New-Object System.Windows.Forms.Label
$version.Text = [string]$prefs.update_status
$version.SetBounds(20, 320, 600, 68)
$version.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$check = New-Object System.Windows.Forms.Button
$check.Text = 'Проверить обновления'
$check.SetBounds(20, 282, 220, 32)
$check.Add_Click({
    $script:result = @{action='check_updates'; docx=$path.Text; clip_name=''; body_gap_pixels=[double]$gap.Value; layout_only=$only.Checked; auto_update=$update.Checked}
    $form.DialogResult = 'OK'
    $form.Close()
})
$start = New-Object System.Windows.Forms.Button
$start.Text = 'Применить'
$start.SetBounds(370, 402, 120, 32)
$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = 'Отмена'
$cancel.SetBounds(500, 402, 120, 32)
$cancel.DialogResult = 'Cancel'
$form.CancelButton = $cancel
$start.Add_Click({
    if (-not $only.Checked -and -not [System.IO.File]::Exists($path.Text)) {
        [System.Windows.Forms.MessageBox]::Show($form, 'Выберите существующий DOCX-файл.', 'Resolve Digest') | Out-Null
        return
    }
    $script:result = @{docx=$path.Text; clip_name=''; body_gap_pixels=[double]$gap.Value; layout_only=$only.Checked; auto_update=$update.Checked}
    $form.DialogResult = 'OK'
    $form.Close()
})
$form.Controls.AddRange(@($label, $path, $browse, $gapLabel, $gap, $only, $update, $help, $check, $version, $start, $cancel))
try {
    if ($form.ShowDialog() -eq 'OK') { [Console]::Out.Write(($script:result | ConvertTo-Json -Compress)) }
} finally { $form.Dispose() }
