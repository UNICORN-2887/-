' 按键精灵九宫格测试 - 通过 REST API 调用框架导航
' 使用方法:
'   1. 先启动导航服务: game-automator serve grid_reachable.png
'   2. 在按键精灵中导入本脚本运行

Const BASE_URL = "http://127.0.0.1:5001"

Function HTTPPost(url, jsonBody)
    Set http = CreateObject("MSXML2.XMLHTTP")
    http.Open "POST", url, False
    http.SetRequestHeader "Content-Type", "application/json"
    http.Send jsonBody
    HTTPPost = http.ResponseText
End Function

' 简单的JSON解析 (提取action字段)
Function GetAction(jsonStr)
    pos = InStr(jsonStr, """action"":""")
    If pos = 0 Then
        GetAction = ""
        Exit Function
    End If
    start = pos + 10
    endPos = InStr(start, jsonStr, """")
    If endPos = 0 Then
        GetAction = ""
        Exit Function
    End If
    GetAction = Mid(jsonStr, start, endPos - start)
End Function

Function GetArrived(jsonStr)
    GetArrived = (InStr(jsonStr, """arrived"":true") > 0)
End Function

' === 主程序 ===

' 1. 规划路径: 中心→右下角
TracePrint "规划: (150,150) → (280,280)"
result = HTTPPost(BASE_URL & "/api/plan", "{""start"":[150,150],""goal"":[280,280]}")
TracePrint "返回: " & Left(result, 80)

' 2. 模拟位置 (测试用)
posX = 150
posY = 150

' 3. 导航循环
For i = 1 To 20
    result = HTTPPost(BASE_URL & "/api/step", "{""x"":" & posX & ",""y"":" & posY & "}")
    action = GetAction(result)
    arrived = GetArrived(result)

    If arrived Or action = "" Then
        TracePrint "到达! (" & posX & "," & posY & ")"
        Exit For
    End If

    ' 映射动作到按键
    Select Case action
        Case "MOVE_N":  KeyPress "W", 1
            posY = posY - 10
        Case "MOVE_S":  KeyPress "S", 1
            posY = posY + 10
        Case "MOVE_W":  KeyPress "A", 1
            posX = posX - 10
        Case "MOVE_E":  KeyPress "D", 1
            posX = posX + 10
        Case "MOVE_NE": KeyPress "W", 1 : KeyPress "D", 1
            posX = posX + 10 : posY = posY - 10
        Case "MOVE_NW": KeyPress "W", 1 : KeyPress "A", 1
            posX = posX - 10 : posY = posY - 10
        Case "MOVE_SE": KeyPress "S", 1 : KeyPress "D", 1
            posX = posX + 10 : posY = posY + 10
        Case "MOVE_SW": KeyPress "S", 1 : KeyPress "A", 1
            posX = posX - 10 : posY = posY + 10
    End Select

    If i Mod 3 = 0 Then
        TracePrint "步" & i & ": pos=(" & posX & "," & posY & ") action=" & action
    End If

    Delay 200
Next

TracePrint "测试完成!"
