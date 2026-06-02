# PostOS 2.0 Launcher
Clear-Host
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "   🚀 POSTFDRY 2.0 | Professional Dispatcher" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
$url = Read-Host " 🔗 URL/Path"
if ($url) {
    # Added --internal-run to prevent redundant window spawning
    python "/Users/shanfu/cc/Library/Tools/postfdry/scripts/postfdry-os.py" "$url" "--internal-run"
}
Read-Host "Press Enter to exit"