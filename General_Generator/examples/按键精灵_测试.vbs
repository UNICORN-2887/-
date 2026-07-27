' 按键精灵接入 game-automator REST API
' 每次按键后自动上报位置到 /api/report, 浏览器会看到红点移动
' 用法: python -m game_automator.server serve grid_reachable.png --map grid_map.jpg

Const BASE = "http://127.0.0.1:5001"

Function HTTPPost(url, body)
    Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
    http.Open "POST", url, False
    http.SetRequestHeader "Content-Type", "application/json"
    If body <> "" Then http.Send body Else http.Send
    HTTPPost = http.ResponseText
End Function

Function JSONGet(json, key)
    Dim p, v
    p = InStr(json, """" & key & """:")
    If p = 0 Then JSONGet = "" : Exit Function
    p = p + Len(key) + 3
    If Mid(json, p, 1) = """" Then
        p = p + 1 : v = InStr(p, json, """") : JSONGet = Mid(json, p, v - p)
    Else
        v = p
        Do While Mid(json, v, 1) <> "," And Mid(json, v, 1) <> "}"
            v = v + 1
        Loop
        JSONGet = Mid(json, p, v - p)
    End If
End Function

Sub ReportPos(px, py)
    HTTPPost BASE & "/api/report", "{""x"":" & px & ",""y"":" & py & "}"
End Sub

' Main
TracePrint "=== KeySprite REST API Test ==="
Dim result, posX, posY, action, arrived, i

result = HTTPPost(BASE & "/api/plan", "{""start"":[150,150],""goal"":[750,750]}")
TracePrint "Plan: " & JSONGet(result, "length") & " points"

posX = 150 : posY = 150
ReportPos posX, posY

For i = 1 To 80
    result = HTTPPost(BASE & "/api/step", "{""x"":" & posX & ",""y"":" & posY & "}")
    action = JSONGet(result, "action")
    arrived = JSONGet(result, "arrived")

    If arrived = "true" Or action = "" Then
        TracePrint "Arrived! (" & posX & "," & posY & ")"
        Exit For
    End If

    Select Case action
        Case "MOVE_N":  KeyPress "W", 1 : posY = posY - 10
        Case "MOVE_S":  KeyPress "S", 1 : posY = posY + 10
        Case "MOVE_W":  KeyPress "A", 1 : posX = posX - 10
        Case "MOVE_E":  KeyPress "D", 1 : posX = posX + 10
        Case "MOVE_NE": KeyPress "W", 1 : KeyPress "D", 1 : posX = posX + 7 : posY = posY - 7
        Case "MOVE_NW": KeyPress "W", 1 : KeyPress "A", 1 : posX = posX - 7 : posY = posY - 7
        Case "MOVE_SE": KeyPress "S", 1 : KeyPress "D", 1 : posX = posX + 7 : posY = posY + 7
        Case "MOVE_SW": KeyPress "S", 1 : KeyPress "A", 1 : posX = posX - 7 : posY = posY + 7
    End Select

    ReportPos posX, posY  ' 通知浏览器更新圆点位置

    If i Mod 5 = 0 Then
        TracePrint "Step" & i & ": (" & posX & "," & posY & ") " & action
    End If

    Delay 300
Next

TracePrint "Done!"
