' 按键精灵驱动浏览器导航
' 流程: 网页设起点→Plan Path→Ext Control→运行本脚本
Const BASE = "http://127.0.0.1:5001"
Dim posX, posY, act, res, i

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
        p = p + 1
        e = InStr(p, json, """")
        GetV = Mid(json, p, e - p)
    Else
        e = p
        Do While Mid(json, e, 1) <> "," And Mid(json, e, 1) <> "}" And e < Len(json)
            e = e + 1
        Loop
        GetV = Mid(json, p, e - p)
    End If
End Function

Sub Report(px,py):Post BASE&"/api/report","{""x"":"&px&",""y"":"&py&"}":End Sub

' 读取网页设定的起点 (Ext Control 保存的)
res = Post(BASE & "/api/position", "")
posX = CInt(GetV(res, "posX"))
posY = CInt(GetV(res, "posY"))
If posX = 0 And posY = 0 Then posX = 150 : posY = 150 ' fallback
TracePrint "Start pos: (" & posX & "," & posY & ")"

Report posX, posY

For i = 1 To 120
    res = Post(BASE & "/api/step", "{""x"":" & posX & ",""y"":" & posY & "}")
    act = GetV(res, "action")
    If GetV(res, "arrived") = "true" Or act = "" Then
        TracePrint "Arrived! (" & posX & "," & posY & ")"
        Exit For
    End If

    ' 按方向更新位置 (步长6px)
    Select Case act
        Case "MOVE_N":  posY = posY - 6
        Case "MOVE_S":  posY = posY + 6
        Case "MOVE_W":  posX = posX - 6
        Case "MOVE_E":  posX = posX + 6
        Case "MOVE_NE": posX = posX + 4 : posY = posY - 4
        Case "MOVE_NW": posX = posX - 4 : posY = posY - 4
        Case "MOVE_SE": posX = posX + 4 : posY = posY + 4
        Case "MOVE_SW": posX = posX - 4 : posY = posY + 4
    End Select

    Report posX, posY

    If i Mod 10 = 0 Then
        TracePrint "Step" & i & ": (" & posX & "," & posY & ") " & act
    End If
    Delay 300
Next
TracePrint "Done!"
