param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

$uicCmd = "$PythonExe -m PySide6.scripts.pyside_tool uic"

if (Test-Path "ui/main_window.ui") {
    Invoke-Expression "$uicCmd ui/main_window.ui -o src/ui/ui_main_window.py"
    Write-Host "Generated src/ui/ui_main_window.py"
} else {
    Write-Host "Skip: ui/main_window.ui not found"
}

if (Test-Path "ui/element_editor_dialog.ui") {
    Invoke-Expression "$uicCmd ui/element_editor_dialog.ui -o src/ui/ui_element_editor_dialog.py"
    Write-Host "Generated src/ui/ui_element_editor_dialog.py"
} else {
    Write-Host "Skip: ui/element_editor_dialog.ui not found"
}
