' 在背景啟動「地籍圖 / 使用分區查詢」伺服器，不開任何視窗。
'
' 用 pythonw.exe 執行，所以不會有黑色終端機跳出來。
' 啟動後，目前的網址會寫在同資料夾的「目前網址.txt」裡
' （IP 是 DHCP 取得的，重開機後可能會變，從那個檔案看最準）。
'
' 要停止：工作管理員找 pythonw.exe 結束它，或執行同資料夾的「停止伺服器.bat」。
' 要取消開機自動啟動：把「啟動」資料夾裡的這個捷徑刪掉即可
'   （Win+R 輸入 shell:startup 就會開啟那個資料夾）。

Option Explicit

Dim sh, fso, here, pyw, args
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

here = fso.GetParentFolderName(WScript.ScriptFullName)

' 找 pythonw.exe：先用 Microsoft Store 版的路徑，找不到就退回 PATH
pyw = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe")
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"

sh.CurrentDirectory = here
args = """" & pyw & """ start.py --lan --https --no-browser"

' 第三個參數 False = 不等它結束；第二個 0 = 完全隱藏視窗
sh.Run args, 0, False
