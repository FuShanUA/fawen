param($inputPath)

$scriptPath = "$PSScriptRoot/interactive_styler.py"
# 使用 Start-Process 启动新终端窗口，并运行 Python 脚本
# 传递 $inputPath 以便显示预览
Start-Process powershell -ArgumentList "-NoExit", "-Command", "chcp 65001; python '$scriptPath' '$inputPath'" -WindowStyle Normal