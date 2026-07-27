' 按键精灵 - 直接沿路径坐标移动
Const BASE = "http://127.0.0.1:5001"
Dim posX, posY, i, res, pathLen, step

Function Post(url, body)
    Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
    http.Open "POST", url, False
    http.SetRequestHeader "Content-Type", "application/json"
    If body <> "" Then http.Send body Else http.Send
    Post = http.ResponseText
End Function

' 1. Plan
res = Post(BASE & "/api/plan", "{""start"":[150,150],""goal"":[150,750]}")
TracePrint Left(res, 80)

' 2. Step loop (server follows path coordinates)
posX = 150 : posY = 150
For i = 1 To 200
    res = Post(BASE & "/api/step", "{""x"":" & posX & ",""y"":" & posY & "}")
    ' Extract waypoint from JSON: "waypoint":[xx,yy]
    Dim wp, p1, p2
    p1 = InStr(res, """waypoint"":[")
    If p1 > 0 Then
        p1 = p1 + 12
        p2 = InStr(p1, res, ",")
        If p2 > 0 Then
            wpX = CLng(Mid(res, p1, p2 - p1))
            p1 = p2 + 1
            p2 = InStr(p1, res, "]")
            wpY = CLng(Mid(res, p1, p2 - p1))
            ' Move toward waypoint
            Dim dx, dy, dist
            dx = wpX - posX : dy = wpY - posY
            dist = Sqr(dx*dx + dy*dy)
            If dist > 1 Then
                posX = posX + CLng(dx / dist * 8)
                posY = posY + CLng(dy / dist * 8)
            End If
        End If
    End If
    If InStr(res, """arrived"":true") > 0 Then
        TracePrint "Arrived! (" & posX & "," & posY & ")"
        Exit For
    End If
    Post BASE & "/api/report", "{""x"":" & posX & ",""y"":" & posY & "}"
    If i Mod 10 = 0 Then
        TracePrint "Step" & i & ": (" & posX & "," & posY & ")"
    End If
    Delay 200
Next
TracePrint "Done!"
