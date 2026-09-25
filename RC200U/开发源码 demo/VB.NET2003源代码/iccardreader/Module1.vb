Module Module1

    '读卡函数声明
    Public Declare Function piccreadex Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByRef serial As Byte, ByVal area As Byte, ByVal keyA1B0 As Byte, ByRef picckey As Byte, ByRef piccdata0_2 As Byte) As Byte
    '写卡函数声明
    Public Declare Function piccwriteex Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByRef serial As Byte, ByVal area As Byte, ByVal keyA1B0 As Byte, ByRef picckey As Byte, ByRef piccdata0_2 As Byte) As Byte
    '修改单区函数声明
    Public Declare Function piccchangesinglekey Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByRef serial As Byte, ByVal area As Byte, ByVal keyA1B0 As Byte, ByRef piccoldkey As Byte, ByRef piccnewkey As Byte) As Byte
    '让设备发出声响函数声明
    Public Declare Function pcdbeep Lib "OUR_MIFARE.dll" (ByVal xms As Long) As Byte
    '读取设备编号函数声明
    Public Declare Function pcdgetdevicenumber Lib "OUR_MIFARE.dll" (ByRef devicenumber As Byte) As Byte
    '控制字定义,控制字指定,控制字的含义请查看本公司网站提供的动态库说明
    Public Const BLOCK0_EN = &H1 '操作第0块
    Public Const BLOCK1_EN = &H2 '操作第1块
    Public Const BLOCK2_EN = &H4 '操作第2块
    Public Const NEEDSERIAL = &H8 '仅对指定序列号的卡号操作
    Public Const EXTERNKEY = &H10 '需要在参数中指定认证密码
    Public Const NEEDHALT = &H20 '操作后休眠该卡，必须拿开卡再放回感应区才能重新感应到卡
End Module
