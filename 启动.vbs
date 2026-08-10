' 无窗口启动器：双击本文件启动程序，不弹出任何 cmd 窗口
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
Set ws = CreateObject("Wscript.Shell")
ws.Run """" & base & "\start.bat"" h", 0, False
