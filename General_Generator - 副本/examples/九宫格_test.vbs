' 按键精灵九宫格测试
' 先启动: game-automator serve grid_reachable.png

Const URL = "http://127.0.0.1:5001"

Function HTTPPost(url, body)
    Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
    http.Open "POST", url, False
    http.SetRequestHeader "Content-Type", "application/json"
    http.Send body
    HTTPPost = http.ResponseText
End Function

Function GetField(json, field)
    ' 提取 "field":"value" 或 "field":true/false
    key = """" & field & """:"
    p = InStr(json, key)
    If p = 0 Then GetField = "" : Exit Function
    p = p + Len(key)
    If Mid(json, p, 1) = """" Then
        ' 字符串值
        p = p + 1
        e = InStr(p, json, """")
        GetField = Mid(json, p, e - p)
    ElseIf Mid(json, p, 4) = "true" Then
        GetField = "true"
    ElseIf Mid(json, p, 5) = "false" Then
        GetField = "false"
    Else
        GetField = ""
    End If
End Function

' 主程序
TracePrint "=== 九宫格测试 ==="

' 1. 规划
result = HTTPPost(URL & "/api/plan", "{""start"":[150,150],""goal"":[280,280]}")
TracePrint "Plan: " & Left(result, 60)

' 2. 模拟导航
Dim posX, posY
posX = 150
posY = 150
Dim action, arrived

For i = 1 To 30
    result = HTTPPost(URL & "/api/step", "{""x"":" & posX & ",""y"":" & posY & "}")
    action = GetField(result, "action")
    arrived = GetField(result, "arrived")

    If arrived = "true" Or action = "" Then
        TracePrint "Arrived! (" & posX & "," & posY & ")"
        Exit For
    End If

    If action = "MOVE_N" Then posY = posY - 10
    If action = "MOVE_S" Then posY = posY + 10
    If action = "MOVE_W" Then posX = posX - 10
    If action = "MOVE_E" Then posX = posX + 10
    If action = "MOVE_NE" Then posX = posX + 10 : posY = posY - 10
    If action = "MOVE_NW" Then posX = posX - 10 : posY = posY - 10
    If action = "MOVE_SE" Then posX = posX + 10 : posY = posY + 10
    If action = "MOVE_SW" Then posX = posX - 10 : posY = posY + 10

    If i Mod 3 = 0 Then
        TracePrint "Step" & i & ": (" & posX & "," & posY & ") " & action
    End If

    Delay 100
Next

TracePrint "Test done!"
