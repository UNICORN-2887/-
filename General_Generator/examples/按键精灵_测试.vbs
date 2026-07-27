' 按键精灵纯REST API测试 - 不依赖KeyPress, 全部走HTTP
' 用法: python -m game_automator.server serve grid_reachable.png --map grid_map.jpg
'       浏览器打开 http://127.0.0.1:5001 点 Ext Control 模式
'       按键精灵运行本脚本

Const BASE = "http://127.0.0.1:5001"
Dim posX, posY, action, result, i

Function Post(url, body)
    Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
    http.Open "POST", url, False
    http.SetRequestHeader "Content-Type", "application/json"
    If body <> "" Then http.Send body Else http.Send
    Post = http.ResponseText
End Function

Function GetVal(json, key)
    Dim p, v, e
    p = InStr(json, """" & key & """:")
    If p = 0 Then GetVal = "" : Exit Function
    p = p + Len(key) + 3
    If Mid(json, p, 1) = """" Then
        p = p + 1 : e = InStr(p, json, """") : GetVal = Mid(json, p, e - p)
    Else
        e = p
        Do While Mid(json, e, 1) <> "," And Mid(json, e, 1) <> "}" And e < Len(json)
            e = e + 1
        Loop
        GetVal = Mid(json, p, e - p)
    End If
End Function

' 速度表: 每个动作的方向位移
Function DX(act) : Select Case act
    Case "MOVE_E","MOVE_NE","MOVE_SE" : DX = 6
    Case "MOVE_W","MOVE_NW","MOVE_SW" : DX = -6
    Case Else : DX = 0
End Select : End Function

Function DY(act) : Select Case act
    Case "MOVE_N","MOVE_NE","MOVE_NW" : DY = -6
    Case "MOVE_S","MOVE_SE","MOVE_SW" : DY = 6
    Case Else : DY = 0
End Select : End Function

' === 主程序 ===
TracePrint "=== REST API Drived Demo ==="

' 1. 规划
result = Post(BASE & "/api/plan", "{""start"":[150,150],""goal"":[750,750]}")
TracePrint "Plan: " & GetVal(result, "length") & " pts"

' 2. 初始化位置
posX = 150 : posY = 150
Post BASE & "/api/report", "{""x"":" & posX & ",""y"":" & posY & "}"

' 3. 导航循环
For i = 1 To 80
    result = Post(BASE & "/api/step", "{""x"":" & posX & ",""y"":" & posY & "}")
    action = GetVal(result, "action")

    If GetVal(result, "arrived") = "true" Or action = "" Then
        TracePrint "Arrived! (" & posX & "," & posY & ")"
        Exit For
    End If

    ' 更新位置
    posX = posX + DX(action)
    posY = posY + DY(action)

    ' 通知浏览器
    Post BASE & "/api/report", "{""x"":" & posX & ",""y"":" & posY & "}"

    If i Mod 5 = 0 Then
        TracePrint "Step" & i & ": (" & posX & "," & posY & ") " & action
    End If

    Delay 400
Next

TracePrint "Done! " & i & " steps"
