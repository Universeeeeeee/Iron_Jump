VERSION 5.00
Begin VB.Form Form1 
   Caption         =   "读写器例子程序"
   ClientHeight    =   3315
   ClientLeft      =   60
   ClientTop       =   450
   ClientWidth     =   7965
   ForeColor       =   &H8000000F&
   LinkTopic       =   "Form1"
   ScaleHeight     =   3315
   ScaleWidth      =   7965
   StartUpPosition =   3  'Windows Default
   Begin VB.CommandButton Command10 
      Caption         =   "写设备存储区2"
      Height          =   540
      Left            =   6000
      TabIndex        =   11
      Top             =   2040
      Width           =   1815
   End
   Begin VB.CommandButton Command9 
      Caption         =   "读设备存储区2"
      Height          =   540
      Left            =   4050
      TabIndex        =   10
      Top             =   2040
      Width           =   1815
   End
   Begin VB.CommandButton Command8 
      Caption         =   "读设备存储区1"
      Height          =   540
      Left            =   150
      TabIndex        =   9
      Top             =   2040
      Width           =   1815
   End
   Begin VB.CommandButton Command7 
      Caption         =   "写设备存储区1"
      Height          =   540
      Left            =   2100
      TabIndex        =   8
      Top             =   2040
      Width           =   1815
   End
   Begin VB.CommandButton Command6 
      Caption         =   "改AB密码及控制字"
      Height          =   540
      Left            =   6000
      TabIndex        =   7
      Top             =   1320
      Width           =   1815
   End
   Begin VB.CommandButton Command5 
      Caption         =   "读出设备全球唯一的设备编号，作为加密狗用"
      Height          =   540
      Left            =   150
      TabIndex        =   4
      Top             =   1305
      Width           =   5685
   End
   Begin VB.CommandButton Command4 
      Caption         =   "让设备发出声响"
      Height          =   540
      Left            =   6000
      TabIndex        =   3
      Top             =   150
      Width           =   1815
   End
   Begin VB.CommandButton Command3 
      Caption         =   "改单区密码"
      Height          =   540
      Left            =   4050
      TabIndex        =   2
      Top             =   150
      Width           =   1815
   End
   Begin VB.CommandButton Command2 
      Caption         =   "轻松写卡"
      Height          =   540
      Left            =   2100
      TabIndex        =   1
      Top             =   150
      Width           =   1815
   End
   Begin VB.CommandButton Command1 
      Caption         =   "轻松读卡"
      Height          =   540
      Left            =   150
      TabIndex        =   0
      Top             =   150
      Width           =   1815
   End
   Begin VB.Label Label3 
      Caption         =   "每个按钮只调用到一个函数，以上4个函数可以轻松应付各类应用，可以节省大量的开发时间"
      ForeColor       =   &H00C0C000&
      Height          =   240
      Left            =   240
      TabIndex        =   6
      Top             =   840
      Width           =   7365
   End
   Begin VB.Label Label2 
      Caption         =   "建议将OUR_MIFARE.dll复制到应用程序同一目录下"
      ForeColor       =   &H00C0C000&
      Height          =   240
      Left            =   240
      TabIndex        =   5
      Top             =   2880
      Width           =   6090
   End
End
Attribute VB_Name = "Form1"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
'轻松读卡
Private Declare Function piccreadex Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByVal serial As Long, ByVal area As Byte, ByVal keyA1B0 As Byte, ByVal picckey As Long, ByVal piccdata0_2 As Long) As Byte

'轻松写卡
Private Declare Function piccwriteex Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByVal serial As Long, ByVal area As Byte, ByVal keyA1B0 As Byte, ByVal picckey As Long, ByVal piccdata0_2 As Long) As Byte

'修改单区函数声明
Private Declare Function piccchangesinglekey Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByVal serial As Long, ByVal area As Byte, ByVal keyA1B0 As Byte, ByVal piccoldkey As Long, ByVal piccnewkey As Long) As Byte

Private Declare Function piccchangesinglekeyex Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByVal serial As Long, ByVal area As Byte, ByVal keyA1B0 As Byte, ByVal piccoldkey As Long, ByVal piccnewkey As Long) As Byte

'让设备发出声响函数声明
Private Declare Function pcdbeep Lib "OUR_MIFARE.dll" (ByVal xms As Long) As Byte

'读取设备编号函数声明
Private Declare Function pcdgetdevicenumber Lib "OUR_MIFARE.dll" (ByVal devicenumber As Long) As Byte

'读设备存储区1
Private Declare Function pcdgetcustomizedata1 Lib "OUR_MIFARE.dll" (ByVal readerdata As Long) As Byte

'写设备存储区1
Private Declare Function pcdsetcustomizedata1 Lib "OUR_MIFARE.dll" (ByVal readerdata As Long) As Byte


'读设备存储区2
Private Declare Function pcdgetcustomizedata2 Lib "OUR_MIFARE.dll" (ByVal readerdata As Long, ByVal devicenumber As Long) As Byte

'写设备存储区2
Private Declare Function pcdsetcustomizedata2 Lib "OUR_MIFARE.dll" (ByVal readerdata As Long) As Byte

        
'控制字定义,控制字指定,控制字的含义请查看本公司网站提供的动态库说明
Private Const BLOCK0_EN = &H1
Private Const BLOCK1_EN = &H2
Private Const BLOCK2_EN = &H4
Private Const NEEDSERIAL = &H8
Private Const EXTERNKEY = &H10
Private Const NEEDHALT = &H20


Private Sub Command1_Click()
'轻松读卡
'技术支持:
'网站:
Dim status As Byte '存放返回值

Dim myareano As Byte '区号
Dim authmode As Byte '密码类型，用A密码或B密码
Dim myctrlword As Byte '控制字
Dim mypicckey(0 To 5) As Byte '密码
Dim mypiccserial(0 To 3) As Byte '卡序列号
Dim mypiccdata(0 To 47) As Byte '卡数据缓冲



'控制字指定,控制字的含义请查看本公司网站提供的动态库说明
myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY

'指定区号
myareano = 8 '指定为第8区
'批定密码模式
authmode = 1 '大于0表示用A密码认证，推荐用A密码认证

'指定密码
mypicckey(0) = &HFF
mypicckey(1) = &HFF
mypicckey(2) = &HFF
mypicckey(3) = &HFF
mypicckey(4) = &HFF
mypicckey(5) = &HFF

status = piccreadex(myctrlword, VarPtr(mypiccserial(0)), myareano, authmode, VarPtr(mypicckey(0)), VarPtr(mypiccdata(0)))
'在下面设定断点，然后查看mypiccserial、mypiccdata，
'调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
'开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
'处理返回函数
Select Case status

    Case 0:
    
        MsgBox "操作成功"
        
    Case 8:
    
        MsgBox "请将卡放在感应区"
        
    Case 21 '没有动态库
        MsgBox "找不到动态库ICUSB.DLL请将ICUSB.DLL拷贝到VB安装后的目录VB98下"
    
    Case Else
        MsgBox "异常"

End Select



'返回解释
'#define ERR_REQUEST 8'寻卡错误
'#define ERR_READSERIAL 9'读序列吗错误
'#define ERR_SELECTCARD 10'选卡错误
'#define ERR_LOADKEY 11'装载密码错误
'#define ERR_AUTHKEY 12'密码认证错误
'#define ERR_READ 13'读卡错误
'#define ERR_WRITE 14'写卡错误
'#define ERR_NONEDLL 21'没有动态库
'#define ERR_DRIVERORDLL 22'动态库或驱动程序异常
'#define ERR_DRIVERNULL 23'驱动程序错误或尚未安装
'#define ERR_TIMEOUT 24'操作超时，一般是动态库没有反映
'#define ERR_TXSIZE 25'发送字数不够
'#define ERR_TXCRC 26'发送的CRC错
'#define ERR_RXSIZE 27'接收的字数不够
'#define ERR_RXCRC 28'接收的CRC错



End Sub

Private Sub Command10_Click()
'写设备存储区2

'技术支持:
'网站:
Dim status As Byte

Dim devdata(0 To 7) As Byte  '设备存储器数据

devdata(0) = 11
devdata(1) = 12
devdata(2) = 13
devdata(3) = 14
devdata(4) = 15
devdata(5) = 16
devdata(6) = 17
devdata(7) = 18

status = pcdsetcustomizedata2(VarPtr(devdata(0)))

Select Case status

    Case 0:
    
        MsgBox "操作成功"
        
    Case 21 '没有动态库
        MsgBox "找不到动态库ICUSB.DLL请将ICUSB.DLL拷贝到VB安装后的目录VB98下"
    
    Case Else
        MsgBox "异常" + CStr(status)

End Select


'返回解释
'#define ERR_REQUEST 8'寻卡错误
'#define ERR_READSERIAL 9'读序列吗错误
'#define ERR_SELECTCARD 10'选卡错误
'#define ERR_LOADKEY 11'装载密码错误
'#define ERR_AUTHKEY 12'密码认证错误
'#define ERR_READ 13'读卡错误
'#define ERR_WRITE 14'写卡错误
'#define ERR_NONEDLL 21'没有动态库
'#define ERR_DRIVERORDLL 22'动态库或驱动程序异常
'#define ERR_DRIVERNULL 23'驱动程序错误或尚未安装
'#define ERR_TIMEOUT 24'操作超时，一般是动态库没有反映
'#define ERR_TXSIZE 25'发送字数不够
'#define ERR_TXCRC 26'发送的CRC错
'#define ERR_RXSIZE 27'接收的字数不够
'#define ERR_RXCRC 28'接收的CRC错

End Sub

Private Sub Command2_Click()
'轻松写卡
'技术支持:
'网站:
Dim i As Integer

Dim status As Byte '存放返回值
Dim myareano As Byte '区号
Dim authmode As Byte '密码类型，用A密码或B密码
Dim myctrlword As Byte '控制字
Dim mypicckey(0 To 5) As Byte '密码
Dim mypiccserial(0 To 3) As Byte '卡序列号
Dim mypiccdata(0 To 47) As Byte '卡数据缓冲







        


'控制字指定,控制字的含义请查看本公司网站提供的动态库说明
myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY

'指定区号
myareano = 8 '指定为第8区
'批定密码模式
authmode = 1 '大于0表示用A密码认证，推荐用A密码认证

'指定密码
mypicckey(0) = &HFF
mypicckey(1) = &HFF
mypicckey(2) = &HFF
mypicckey(3) = &HFF
mypicckey(4) = &HFF
mypicckey(5) = &HFF

'指定卡数据
For i = 0 To 47
    mypiccdata(i) = i
Next i

status = piccwriteex(myctrlword, VarPtr(mypiccserial(0)), myareano, authmode, VarPtr(mypicckey(0)), VarPtr(mypiccdata(0)))
'在下面设定断点，然后查看mypiccserial、mypiccdata，
'调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
'开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
'处理返回函数
Select Case status

    Case 0:
    
        MsgBox "操作成功"
        
    Case 8:
    
        MsgBox "请将卡放在感应区"
        
    Case 21 '没有动态库
        MsgBox "找不到动态库ICUSB.DLL请将ICUSB.DLL拷贝到VB安装后的目录VB98下"
    
    Case Else
        MsgBox "异常"

End Select



'返回解释
'#define ERR_REQUEST 8'寻卡错误
'#define ERR_READSERIAL 9'读序列吗错误
'#define ERR_SELECTCARD 10'选卡错误
'#define ERR_LOADKEY 11'装载密码错误
'#define ERR_AUTHKEY 12'密码认证错误
'#define ERR_READ 13'读卡错误
'#define ERR_WRITE 14'写卡错误
'#define ERR_NONEDLL 21'没有动态库
'#define ERR_DRIVERORDLL 22'动态库或驱动程序异常
'#define ERR_DRIVERNULL 23'驱动程序错误或尚未安装
'#define ERR_TIMEOUT 24'操作超时，一般是动态库没有反映
'#define ERR_TXSIZE 25'发送字数不够
'#define ERR_TXCRC 26'发送的CRC错
'#define ERR_RXSIZE 27'接收的字数不够
'#define ERR_RXCRC 28'接收的CRC错
End Sub

Private Sub Command3_Click()
'修改单区密码
'技术支持:
'网站:
Dim i As Integer

Dim status As Byte '存放返回值
Dim myareano As Byte '区号
Dim authmode As Byte '密码类型，用A密码或B密码
Dim myctrlword As Byte '控制字
Dim mypiccserial(0 To 3) As Byte '卡序列号
Dim mypiccoldkey(0 To 5) As Byte '旧密码
Dim mypiccnewkey(0 To 5) As Byte '新密码




        


'控制字指定,控制字的含义请查看本公司网站提供的动态库说明
myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY

'指定区号
myareano = 8 '指定为第8区
'批定密码模式
authmode = 1 '大于0表示用A密码认证，推荐用A密码认证

'指定旧密码
mypiccoldkey(0) = &HFF
mypiccoldkey(1) = &HFF
mypiccoldkey(2) = &HFF
mypiccoldkey(3) = &HFF
mypiccoldkey(4) = &HFF
mypiccoldkey(5) = &HFF

'指定新密码,注意：指定新密码时一定要记住，否则有可能找不回密码，导致该卡报废。
mypiccnewkey(0) = &HFF
mypiccnewkey(1) = &HFF
mypiccnewkey(2) = &HFF
mypiccnewkey(3) = &HFF
mypiccnewkey(4) = &HFF
mypiccnewkey(5) = &HFF

status = piccchangesinglekey(myctrlword, VarPtr(mypiccserial(0)), myareano, authmode, VarPtr(mypiccoldkey(0)), VarPtr(mypiccnewkey(0)))

'处理返回函数
Select Case status

    Case 0:
    
        MsgBox "操作成功"
        
    Case 8:
    
        MsgBox "请将卡放在感应区"
        
    Case 21 '没有动态库
        MsgBox "找不到动态库ICUSB.DLL请将ICUSB.DLL拷贝到VB安装后的目录VB98下"
    
    Case Else
        MsgBox "异常"

End Select



'返回解释
'#define ERR_REQUEST 8'寻卡错误
'#define ERR_READSERIAL 9'读序列吗错误
'#define ERR_SELECTCARD 10'选卡错误
'#define ERR_LOADKEY 11'装载密码错误
'#define ERR_AUTHKEY 12'密码认证错误
'#define ERR_READ 13'读卡错误
'#define ERR_WRITE 14'写卡错误
'#define ERR_NONEDLL 21'没有动态库
'#define ERR_DRIVERORDLL 22'动态库或驱动程序异常
'#define ERR_DRIVERNULL 23'驱动程序错误或尚未安装
'#define ERR_TIMEOUT 24'操作超时，一般是动态库没有反映
'#define ERR_TXSIZE 25'发送字数不够
'#define ERR_TXCRC 26'发送的CRC错
'#define ERR_RXSIZE 27'接收的字数不够
'#define ERR_RXCRC 28'接收的CRC错
End Sub

Private Sub Command4_Click()
'让设备发出声音
'技术支持:
'网站:
    pcdbeep 50
End Sub

Private Sub Command5_Click()
'读取设备编号，可做为软件加密狗用,也可以根据此编号在公司网站上查询保修期限

'技术支持:
'网站:
Dim status As Byte

Dim devno(0 To 3) As Byte '设备编号

status = pcdgetdevicenumber(VarPtr(devno(0)))

If status = 0 Then
    MsgBox CStr(devno(0)) + "-" + CStr(devno(1)) + "-" + CStr(devno(2)) + "-" + CStr(devno(3))
End If




'返回解释
'#define ERR_REQUEST 8'寻卡错误
'#define ERR_READSERIAL 9'读序列吗错误
'#define ERR_SELECTCARD 10'选卡错误
'#define ERR_LOADKEY 11'装载密码错误
'#define ERR_AUTHKEY 12'密码认证错误
'#define ERR_READ 13'读卡错误
'#define ERR_WRITE 14'写卡错误
'#define ERR_NONEDLL 21'没有动态库
'#define ERR_DRIVERORDLL 22'动态库或驱动程序异常
'#define ERR_DRIVERNULL 23'驱动程序错误或尚未安装
'#define ERR_TIMEOUT 24'操作超时，一般是动态库没有反映
'#define ERR_TXSIZE 25'发送字数不够
'#define ERR_TXCRC 26'发送的CRC错
'#define ERR_RXSIZE 27'接收的字数不够
'#define ERR_RXCRC 28'接收的CRC错
End Sub

Private Sub Command6_Click()
'修改单区密码
'技术支持:
'网站:
Dim i As Integer

Dim status As Byte '存放返回值
Dim myareano As Byte '区号
Dim authmode As Byte '密码类型，用A密码或B密码
Dim myctrlword As Byte '控制字
Dim mypiccserial(0 To 3) As Byte '卡序列号
Dim mypiccoldkey(0 To 5) As Byte '旧密码
Dim mypiccnewkey(0 To 16) As Byte '新密码




        


'控制字指定,控制字的含义请查看本公司网站提供的动态库说明
myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY

'指定区号
myareano = 10 '指定为第8区
'批定密码模式
authmode = 1 '大于0表示用A密码认证，推荐用A密码认证

'指定旧密码
mypiccoldkey(0) = &HFF
mypiccoldkey(1) = &HFF
mypiccoldkey(2) = &HFF
mypiccoldkey(3) = &HFF
mypiccoldkey(4) = &HFF
mypiccoldkey(5) = &HFF

'指定新密码,注意：指定新密码时一定要记住，否则有可能找不回密码，导致该卡报废。
mypiccnewkey(0) = &HFF  'A密码
mypiccnewkey(1) = &HFF
mypiccnewkey(2) = &HFF
mypiccnewkey(3) = &HFF
mypiccnewkey(4) = &HFF
mypiccnewkey(5) = &HFF

mypiccnewkey(6) = &HFF  '控制字
mypiccnewkey(7) = &H7
mypiccnewkey(8) = &H80
mypiccnewkey(9) = &H69

mypiccnewkey(10) = &HFF  'B密码
mypiccnewkey(11) = &HFF
mypiccnewkey(12) = &HFF
mypiccnewkey(13) = &HFF
mypiccnewkey(14) = &HFF
mypiccnewkey(15) = &HFF

mypiccnewkey(16) = &H3  '3是表示同时更改A、B、 密码权限访问字，为2表示密码权限访问字不更改，只改A、B密码，为0表示只改A密码


status = piccchangesinglekeyex(myctrlword, VarPtr(mypiccserial(0)), myareano, authmode, VarPtr(mypiccoldkey(0)), VarPtr(mypiccnewkey(0)))

'处理返回函数
Select Case status

    Case 0:
    
        MsgBox "操作成功"
        
    Case 8:
    
        MsgBox "请将卡放在感应区"
        
    Case 21 '没有动态库
        MsgBox "找不到动态库ICUSB.DLL请将ICUSB.DLL拷贝到VB安装后的目录VB98下"
    
    Case Else
        MsgBox "异常"

End Select



'返回解释
'#define ERR_REQUEST 8'寻卡错误
'#define ERR_READSERIAL 9'读序列吗错误
'#define ERR_SELECTCARD 10'选卡错误
'#define ERR_LOADKEY 11'装载密码错误
'#define ERR_AUTHKEY 12'密码认证错误
'#define ERR_READ 13'读卡错误
'#define ERR_WRITE 14'写卡错误
'#define ERR_NONEDLL 21'没有动态库
'#define ERR_DRIVERORDLL 22'动态库或驱动程序异常
'#define ERR_DRIVERNULL 23'驱动程序错误或尚未安装
'#define ERR_TIMEOUT 24'操作超时，一般是动态库没有反映
'#define ERR_TXSIZE 25'发送字数不够
'#define ERR_TXCRC 26'发送的CRC错
'#define ERR_RXSIZE 27'接收的字数不够
'#define ERR_RXCRC 28'接收的CRC错
End Sub

Private Sub Command7_Click()
'写设备存储区1

'技术支持:
'网站:
Dim status As Byte

Dim devdata(0 To 3) As Byte  '设备存储器数据

devdata(0) = 1
devdata(1) = 2
devdata(2) = 3
devdata(3) = 4


status = pcdsetcustomizedata1(VarPtr(devdata(0)))

Select Case status

    Case 0:
    
        MsgBox "操作成功"
        
    Case 21 '没有动态库
        MsgBox "找不到动态库ICUSB.DLL请将ICUSB.DLL拷贝到VB安装后的目录VB98下"
    
    Case Else
        MsgBox "异常" + CStr(status)

End Select






'返回解释
'#define ERR_REQUEST 8'寻卡错误
'#define ERR_READSERIAL 9'读序列吗错误
'#define ERR_SELECTCARD 10'选卡错误
'#define ERR_LOADKEY 11'装载密码错误
'#define ERR_AUTHKEY 12'密码认证错误
'#define ERR_READ 13'读卡错误
'#define ERR_WRITE 14'写卡错误
'#define ERR_NONEDLL 21'没有动态库
'#define ERR_DRIVERORDLL 22'动态库或驱动程序异常
'#define ERR_DRIVERNULL 23'驱动程序错误或尚未安装
'#define ERR_TIMEOUT 24'操作超时，一般是动态库没有反映
'#define ERR_TXSIZE 25'发送字数不够
'#define ERR_TXCRC 26'发送的CRC错
'#define ERR_RXSIZE 27'接收的字数不够
'#define ERR_RXCRC 28'接收的CRC错
End Sub

Private Sub Command8_Click()
'读设备存储区1

'技术支持:
'网站:
Dim status As Byte

Dim devdata(0 To 3) As Byte  '设备存储器数据

status = pcdgetcustomizedata1(VarPtr(devdata(0)))

If status = 0 Then
    MsgBox CStr(devdata(0)) + "-" + CStr(devdata(1)) + "-" + CStr(devdata(2)) + "-" + CStr(devdata(3))
End If



'返回解释
'#define ERR_REQUEST 8'寻卡错误
'#define ERR_READSERIAL 9'读序列吗错误
'#define ERR_SELECTCARD 10'选卡错误
'#define ERR_LOADKEY 11'装载密码错误
'#define ERR_AUTHKEY 12'密码认证错误
'#define ERR_READ 13'读卡错误
'#define ERR_WRITE 14'写卡错误
'#define ERR_NONEDLL 21'没有动态库
'#define ERR_DRIVERORDLL 22'动态库或驱动程序异常
'#define ERR_DRIVERNULL 23'驱动程序错误或尚未安装
'#define ERR_TIMEOUT 24'操作超时，一般是动态库没有反映
'#define ERR_TXSIZE 25'发送字数不够
'#define ERR_TXCRC 26'发送的CRC错
'#define ERR_RXSIZE 27'接收的字数不够
'#define ERR_RXCRC 28'接收的CRC错
End Sub

Private Sub Command9_Click()
'读设备存储区2

'技术支持:
'网站:
Dim status As Byte

Dim devdata(0 To 7) As Byte  '设备存储器数据
Dim devno(0 To 3) As Byte '设备编号


status = pcdgetcustomizedata2(VarPtr(devdata(0)), VarPtr(devno(0)))

If status = 0 Then
    MsgBox "数据：" + CStr(devdata(0)) + "-" + CStr(devdata(1)) + "-" + CStr(devdata(2)) + "-" + CStr(devdata(3)) + "-" + CStr(devdata(4)) + "-" + CStr(devdata(5)) + "-" + CStr(devdata(6)) + "-" + CStr(devdata(7)) + _
    "设备编号：" + CStr(devno(0)) + "-" + CStr(devno(1)) + "-" + CStr(devno(2)) + "-" + CStr(devno(3))
End If



'返回解释
'#define ERR_REQUEST 8'寻卡错误
'#define ERR_READSERIAL 9'读序列吗错误
'#define ERR_SELECTCARD 10'选卡错误
'#define ERR_LOADKEY 11'装载密码错误
'#define ERR_AUTHKEY 12'密码认证错误
'#define ERR_READ 13'读卡错误
'#define ERR_WRITE 14'写卡错误
'#define ERR_NONEDLL 21'没有动态库
'#define ERR_DRIVERORDLL 22'动态库或驱动程序异常
'#define ERR_DRIVERNULL 23'驱动程序错误或尚未安装
'#define ERR_TIMEOUT 24'操作超时，一般是动态库没有反映
'#define ERR_TXSIZE 25'发送字数不够
'#define ERR_TXCRC 26'发送的CRC错
'#define ERR_RXSIZE 27'接收的字数不够
'#define ERR_RXCRC 28'接收的CRC错
End Sub
