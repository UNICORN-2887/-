' 按键精灵 REST API 测试
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

' 1. Plan
res = Post(BASE & "/api/plan", "{""start"":[150,150],""goal"":[750,750]}")
pathLen = CLng(GetV(res, "length"))
TracePrint "Plan: " & pathLen & " pts"

' 2. Navigate
posX = 150 : posY = 150
For i = 1 To 200
    res = Post(BASE & "/api/step", "{""x"":" & posX & ",""y"":" & posY & "}")
    act = GetV(res, "action")
    If GetV(res, "arrived") = "true" Or act = "" Then
        TracePrint "Arrived! (" & posX & "," & posY & ")"
        Exit For
    End If

    Select Case act
        Case "MOVE_N":  posY = posY - 5
        Case "MOVE_S":  posY = posY + 5
        Case "MOVE_W":  posX = posX - 5
        Case "MOVE_E":  posX = posX + 5
        Case "MOVE_NE": posX = posX + 4 : posY = posY - 4
        Case "MOVE_NW": posX = posX - 4 : posY = posY - 4
        Case "MOVE_SE": posX = posX + 4 : posY = posY + 4
        Case "MOVE_SW": posX = posX - 4 : posY = posY + 4
    End Select

    Post BASE & "/api/report", "{""x"":" & posX & ",""y"":" & posY & "}"

    If i Mod 10 = 0 Then
        TracePrint "Step" & i & ": (" & posX & "," & posY & ") " & act
    End If
    Delay 200
Next
TracePrint "Done!"
