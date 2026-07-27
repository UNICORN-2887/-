' 按键精灵接入 game-automator REST API
' 使用方法:
'   1. 终端运行: python -m game_automator.server serve grid_reachable.png --map grid_map.jpg
'   2. 浏览器打开 http://127.0.0.1:5001 配置起终点
'   3. 按键精灵中导入运行本脚本

Const BASE = "http://127.0.0.1:5001"

Function HTTPPost(url, body)
    Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
    http.Open "POST", url, False
    http.SetRequestHeader "Content-Type", "application/json"
    If body <> "" Then http.Send body Else http.Send
    HTTPPost = http.ResponseText
End Function

' 简单JSON解析: "key":"string" 或 "key":number
Function JSONGet(json, key)
    Dim p, v
    p = InStr(json, """" & key & """:")
    If p = 0 Then JSONGet = "" : Exit Function
    p = p + Len(key) + 3
    If Mid(json, p, 1) = """" Then
        p = p + 1
        v = InStr(p, json, """")
        JSONGet = Mid(json, p, v - p)
    Else
        v = p
        Do While Mid(json, v, 1) <> "," And Mid(json, v, 1) <> "}" And v < Len(json)
            v = v + 1
        Loop
        JSONGet = Mid(json, p, v - p)
    End If
End Function

' === 主程序 ===
TracePrint "=== game-automator REST API Test ==="

' 1. 规划路径
Dim result, pathLen, posX, posY, action, arrived, i
result = HTTPPost(BASE & "/api/plan", "{""start"":[150,150],""goal"":[750,750]}")
pathLen = JSONGet(result, "length")
TracePrint "Path: " & pathLen & " points"

' 2. 模拟位置
posX = 150
posY = 150

' 3. 导航循环 (最多50步)
For i = 1 To 50
    result = HTTPPost(BASE & "/api/step", "{""x"":" & posX & ",""y"":" & posY & "}")
    action = JSONGet(result, "action")
    arrived = JSONGet(result, "arrived")

    If arrived = "true" Or action = "" Then
        TracePrint "== Arrived! (" & posX & "," & posY & ") =="
        Exit For
    End If

    ' 按键映射 (8方向)
    Select Case action
        Case "MOVE_N":  KeyPress "W", 1 : posY = posY - 10
        Case "MOVE_S":  KeyPress "S", 1 : posY = posY + 10
        Case "MOVE_W":  KeyPress "A", 1 : posX = posX - 10
        Case "MOVE_E":  KeyPress "D", 1 : posX = posX + 10
        Case "MOVE_NE": KeyPress "W", 1 : KeyPress "D", 1 : posX = posX + 10 : posY = posY - 10
        Case "MOVE_NW": KeyPress "W", 1 : KeyPress "A", 1 : posX = posX - 10 : posY = posY - 10
        Case "MOVE_SE": KeyPress "S", 1 : KeyPress "D", 1 : posX = posX + 10 : posY = posY + 10
        Case "MOVE_SW": KeyPress "S", 1 : KeyPress "A", 1 : posX = posX - 10 : posY = posY + 10
    End Select

    If i Mod 5 = 0 Then
        TracePrint "Step" & i & ": (" & posX & "," & posY & ") " & action
    End If

    Delay 300
Next

TracePrint "=== Test Complete ==="
