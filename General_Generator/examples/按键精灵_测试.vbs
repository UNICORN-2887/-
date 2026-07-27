' 按键精灵自主驱动 - 无需网页配合, 自己规划+步进
Const BASE = "http://127.0.0.1:5001"
Dim posX, posY, act, res, i, pathLen

Function Post(url, body)
    Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
    http.Open "POST", url, False
    http.SetRequestHeader "Content-Type", "application/json"
    If body <> "" Then http.Send body Else http.Send
    Post = http.ResponseText
End Function

Function GetV(json, key)
    Dim p, e
    p = InStr(json, """" & key & """:")
    If p = 0 Then GetV = "" : Exit Function
    p = p + Len(key) + 3
    If Mid(json, p, 1) = """" Then
        p = p + 1 : e = InStr(p, json, """") : GetV = Mid(json, p, e - p)
    Else
        e = p
        Do While Mid(json, e, 1) <> "," And Mid(json, e, 1) <> "}" And e < Len(json)
            e = e + 1
        Loop
        GetV = Mid(json, p, e - p)
    End If
End Function

Function GetNum(json, key)
    GetNum = Int(GetV(json, key))
End Function

' === 1. 规划 ===
res = Post(BASE & "/api/plan", "{""start"":[150,150],""goal"":[750,750]}")
pathLen = GetNum(res, "length")
TracePrint "Plan: " & pathLen & " pts"
If pathLen = 0 Then TracePrint "Plan FAILED" : WScript.Quit

' === 2. 导航 ===
posX = 150 : posY = 150
For i = 1 To 200
    res = Post(BASE & "/api/step", "{""x"":" & posX & ",""y"":" & posY & "}")
    act = GetV(res, "action")
    If GetV(res, "arrived") = "true" Or act = "" Then
        TracePrint "Arrived! (" & posX & "," & posY & ")"
        Exit For
    End If
    If GetV(res, "error") <> "" Then
        TracePrint "Error: " & GetV(res, "error")
        Exit For
    End If

    ' 朝waypoint移动 (不按固定方向硬走)
    Dim wpX, wpY, dx, dy, dist
    wpX = Int(GetV(res, "waypointX"))
    wpY = Int(GetV(res, "waypointY"))
    If wpX > 0 And wpY > 0 Then
        dx = wpX - posX : dy = wpY - posY
        dist = Sqr(dx*dx + dy*dy)
        If dist > 1 Then
            posX = posX + CInt(dx / dist * 8)
            posY = posY + CInt(dy / dist * 8)
        End If
    End If

    Post BASE & "/api/report", "{""x"":" & posX & ",""y"":" & posY & "}"

    If i Mod 10 = 0 Then
        TracePrint "Step" & i & ": (" & posX & "," & posY & ") " & act
    End If
    Delay 200
Next
TracePrint "Done!"
