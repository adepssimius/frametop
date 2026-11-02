# Frametop's monitor alignment: shows the markers it finds each monitor by. Vibepollo runs this as the app
# FrametopAlign, on the headset's request, and ends it when the headset quits the app. Each monitor has its own
# four AprilTags (36h11): \\.\DISPLAYn shows 4(n-1) to 4(n-1)+3. They're placed as fractions of the screen, so
# resolution and scaling don't matter; align/solver.cpp has the same layout.
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type -Name Dpi -Namespace Native -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
[void][Native.Dpi]::SetProcessDPIAware()

$Tag = 0.43; $Margin = 0.056; $Quiet = 0.031
# Each tag's six rows of six cells, 1 white, inside its black border.
$Codes = @('21a146bab', '92d18fe9b', '7089014bb', '193979e27', '44153d3d7', '35cd5b8cf', 'a10ba56a0', '2b874a608', 'b57fb8d44', '4e20b5a64', '61d897f2c', 'ab3469ffc', '594ca45c2', 'fa1c2d2e2', '97c24b972', '75928624a', '1caafe99a', '3236ddc16', '884e527d6', '5771a8c7e', 'f52925b81', '2e59cc1a1', '7fa58ab31', 'eb43384f9', '3913d5345', 'd79b1a3b5', '0dfbe768d', '5cd7a031d', 'b9c8f7a4b', '46987e06b', '6e0c5d527', '5bc567bb4')

function Draw-Screen($g, $w, $h, $firstId) {
    $g.Clear([Drawing.Color]::Black)
    $side = $Tag * $h; $edge = $Margin * $h; $q = $Quiet * $h; $cell = $side / 8
    $white = [Drawing.Brushes]::White; $black = [Drawing.Brushes]::Black
    $places = @(@($edge, $edge), @(($w - $edge - $side), $edge), @($edge, ($h - $edge - $side)), @(($w - $edge - $side), ($h - $edge - $side)))
    for ($t = 0; $t -lt 4; $t++) {
        $x = [single]$places[$t][0]; $y = [single]$places[$t][1]
        $g.FillRectangle($white, [single]($x - $q), [single]($y - $q), [single]($side + 2 * $q), [single]($side + 2 * $q))
        $g.FillRectangle($black, $x, $y, [single]$side, [single]$side)
        $code = [Convert]::ToInt64($Codes[$firstId + $t], 16)
        for ($row = 0; $row -lt 6; $row++) {
            for ($col = 0; $col -lt 6; $col++) {
                if (($code -shr (35 - ($row * 6 + $col))) -band 1) {
                    $g.FillRectangle($white, [single]($x + ($col + 1) * $cell), [single]($y + ($row + 1) * $cell), [single]$cell, [single]$cell)
                }
            }
        }
    }
}

foreach ($s in [Windows.Forms.Screen]::AllScreens) {
    if ($s.DeviceName -notmatch 'DISPLAY(\d+)$') { continue }
    $firstId = ([int]$Matches[1] - 1) * 4
    if ($firstId + 4 -gt $Codes.Count) { continue }
    $image = New-Object Drawing.Bitmap $s.Bounds.Width, $s.Bounds.Height
    $g = [Drawing.Graphics]::FromImage($image)
    $g.SmoothingMode = 'None'; $g.PixelOffsetMode = 'Half'
    Draw-Screen $g $s.Bounds.Width $s.Bounds.Height $firstId
    $g.Dispose()
    $f = New-Object Windows.Forms.Form
    $f.FormBorderStyle = 'None'; $f.StartPosition = 'Manual'; $f.TopMost = $true
    $f.ShowInTaskbar = $false; $f.BackColor = 'Black'; $f.Bounds = $s.Bounds
    $f.BackgroundImage = $image; $f.BackgroundImageLayout = 'None'
    # Vibepollo asks the windows to close; without this the process stays and it force-closes after 5 s.
    $f.Add_FormClosed({ [Windows.Forms.Application]::Exit() })
    $f.Show(); $f.Bounds = $s.Bounds
}
$t = New-Object Windows.Forms.Timer
$t.Interval = 600000     # a last resort: Vibepollo ends it
$t.Add_Tick({ [Windows.Forms.Application]::Exit() })
$t.Start()
[Windows.Forms.Application]::Run()
