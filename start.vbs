' start.vbs - 无窗口启动器（双击本文件启动程序，不弹出任何 cmd 窗口）
' 优先使用项目虚拟环境 pythonw，其次系统 PATH 中的 pythonw
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
Set ws = CreateObject("Wscript.Shell")

pyw = ""
For Each c In Array(base & "\venv\Scripts\pythonw.exe", base & "\env\Scripts\pythonw.exe")
    If fso.FileExists(c) Then
        pyw = c
        Exit For
    End If
Next
If pyw = "" Then pyw = "pythonw.exe"

ws.CurrentDirectory = base
ws.Run """" & pyw & """ """ & base & "\app.py""", 0, False
