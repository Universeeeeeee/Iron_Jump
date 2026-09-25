VERSION 5.00
Begin VB.Form Form1 
   Caption         =   "Form1"
   ClientHeight    =   7455
   ClientLeft      =   60
   ClientTop       =   450
   ClientWidth     =   8175
   ForeColor       =   &H8000000F&
   LinkTopic       =   "Form1"
   ScaleHeight     =   7455
   ScaleWidth      =   8175
   StartUpPosition =   3  'Windows Default
   Begin VB.Frame Frame2 
      Caption         =   "Mifare Ultralight卡操作"
      Height          =   2295
      Left            =   120
      TabIndex        =   11
      Top             =   2880
      Width           =   7935
      Begin VB.CommandButton Command12 
         Caption         =   "读多块信息"
         Height          =   495
         Left            =   120
         TabIndex        =   16
         Top             =   1560
         Width           =   3735
      End
      Begin VB.CommandButton Command11 
         Caption         =   "写多块信息"
         Height          =   495
         Left            =   4080
         TabIndex        =   15
         Top             =   1560
         Width           =   3735
      End
      Begin VB.CommandButton Command10 
         Caption         =   "写单块信息"
         Height          =   495
         Left            =   4080
         TabIndex        =   14
         Top             =   960
         Width           =   3735
      End
      Begin VB.CommandButton Command9 
         Caption         =   "读单块信息"
         Height          =   495
         Left            =   120
         TabIndex        =   13
         Top             =   960
         Width           =   3735
      End
      Begin VB.CommandButton Command8 
         Caption         =   "读出7个字节序列号"
         Height          =   495
         Left            =   120
         TabIndex        =   12
         Top             =   360
         Width           =   3735
      End
   End
   Begin VB.Frame Frame1 
      Caption         =   "S70 操作"
      Height          =   1095
      Left            =   120
      TabIndex        =   8
      Top             =   1560
      Width           =   7935
      Begin VB.CommandButton Command6 
         Caption         =   "读S70卡32或39区的16块数据块"
         Height          =   540
         Left            =   120
         TabIndex        =   10
         Top             =   360
         Width           =   3735
      End
      Begin VB.CommandButton Command7 
         Caption         =   "写S70卡32或39区的16块数据块"
         Height          =   540
         Left            =   4080
         TabIndex        =   9
         Top             =   360
         Width           =   3735
      End
   End
   Begin VB.CommandButton Command5 
      Caption         =   "读出设备全球唯一的设备编号，作为加密狗用"
      Height          =   540
      Left            =   240
      TabIndex        =   4
      Top             =   840
      Width           =   7665
   End
   Begin VB.CommandButton Command4 
      Caption         =   "让设备发出声响"
      Height          =   540
      Left            =   6120
      TabIndex        =   3
      Top             =   120
      Width           =   1815
   End
   Begin VB.CommandButton Command3 
      Caption         =   "改单区密码"
      Height          =   540
      Left            =   4170
      TabIndex        =   2
      Top             =   150
      Width           =   1815
   End
   Begin VB.CommandButton Command2 
      Caption         =   "轻松写卡"
      Height          =   540
      Left            =   2220
      TabIndex        =   1
      Top             =   150
      Width           =   1815
   End
   Begin VB.CommandButton Command1 
      Caption         =   "轻松读卡"
      Height          =   540
      Left            =   270
      TabIndex        =   0
      Top             =   150
      Width           =   1815
   End
   Begin VB.Label Label4 
      Caption         =   "读写器例子程序"
      BeginProperty Font 
         Name            =   "宋体"
         Size            =   12
         Charset         =   0
         Weight          =   400
         Underline       =   0   'False
         Italic          =   0   'False
         Strikethrough   =   0   'False
      EndProperty
      ForeColor       =   &H000000FF&
      Height          =   315
      Left            =   3000
      TabIndex        =   7
      Top             =   6660
      Width           =   1815
   End
   Begin VB.Label Label2 
      Caption         =   "建议将OUR_MIFARE.dll复制到应用程序同一目录下"
      ForeColor       =   &H00C0C000&
      Height          =   240
      Left            =   825
      TabIndex        =   6
      Top             =   5910
      Width           =   6090
   End
   Begin VB.Label Label1 
      Caption         =   "在VB的编辑状态下双击以上按钮可以查看代码"
      BeginProperty Font 
         Name            =   "宋体"
         Size            =   12
         Charset         =   0
         Weight          =   400
         Underline       =   0   'False
         Italic          =   0   'False
         Strikethrough   =   0   'False
      EndProperty
      ForeColor       =   &H000000FF&
      Height          =   315
      Left            =   1500
      TabIndex        =   5
      Top             =   5460
      Width           =   4890
   End
End
Attribute VB_Name = "Form1"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
'轻松读卡
Private Declare Function piccreadex Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByVal serial As Long, ByVal area As Byte, ByVal keyA1B0 As Byte, ByVal picckey As Long, ByVal piccdata0_2 As Long) As Byte

'S70卡请用以下函数******************************************************************************************************************************

'寻卡并返回该卡的序列号
Private Declare Function piccrequest Lib "OUR_MIFARE.dll" (ByVal serial As Long) As Byte

'密码认证
Private Declare Function piccauthkey1 Lib "OUR_MIFARE.dll" (ByVal serial As Long, ByVal area As Byte, ByVal keyA1B0 As Byte, ByVal picckey As Long) As Byte

'单块读卡
Private Declare Function piccread Lib "OUR_MIFARE.dll" (ByVal block As Byte, ByVal piccdata0_2 As Long) As Byte

'单块写卡
Private Declare Function piccwrite Lib "OUR_MIFARE.dll" (ByVal block As Byte, ByVal piccdata0_2 As Long) As Byte

'**********************************************************************************************************************************************


'轻松写卡
Private Declare Function piccwriteex Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByVal serial As Long, ByVal area As Byte, ByVal keyA1B0 As Byte, ByVal picckey As Long, ByVal piccdata0_2 As Long) As Byte


'修改单区函数声明
Private Declare Function piccchangesinglekey Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByVal serial As Long, ByVal area As Byte, ByVal keyA1B0 As Byte, ByVal piccoldkey As Long, ByVal piccnewkey As Long) As Byte

'让设备发出声响函数声明
Private Declare Function pcdbeep Lib "OUR_MIFARE.dll" (ByVal xms As Long) As Byte

'读取设备编号函数声明
Private Declare Function pcdgetdevicenumber Lib "OUR_MIFARE.dll" (ByVal devicenumber As Long) As Byte

'Mifare Ultralight卡 操作
Private Declare Function piccrequest_ul Lib "OUR_MIFARE.dll" (ByVal serial As Long) As Byte

'读块信息

Private Declare Function piccread_ul Lib "OUR_MIFARE.dll" (ByVal block As Byte, ByVal piccdata As Long) As Byte

'写块信息
Private Declare Function piccwrite_ul Lib "OUR_MIFARE.dll" (ByVal block As Byte, ByVal piccdata As Long) As Byte

'读多块信息
Private Declare Function piccreadex_ul Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByVal serial As Long, ByVal block As Byte, ByVal blocksize As Byte, ByVal piccdata As Long) As Byte

'写多块信息
Private Declare Function piccwriteex_ul Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByVal serial As Long, ByVal block As Byte, ByVal blocksize As Byte, ByVal piccdata As Long) As Byte
        
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

Dim m_myDouble As Double
Dim m_mystr As String

Dim i As Integer



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

'Debug.Print mypiccserial(0), mypiccserial(1), mypiccserial(2), mypiccserial(3)


'm_myDouble = mypiccserial(3)
'm_myDouble = m_myDouble * 256
'm_myDouble = m_myDouble + mypiccserial(2)
'm_myDouble = m_myDouble * 256
'm_myDouble = m_myDouble + mypiccserial(1)
'm_myDouble = m_myDouble * 256
'm_myDouble = m_myDouble + mypiccserial(0)

'm_mystr = "0000000000" + CStr(m_myDouble)

'm_mystr = Right(m_mystr, 10) '十位卡号

'Debug.Print m_mystr

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
    Dim status As Byte
    
    Dim serialul(0 To 6) As Byte '设备编号
    Dim piccdata(0 To 3) As Byte
    
    status = piccrequest_ul(VarPtr(serialul(0)))
    
    If stauts = 0 Then
        piccdata(0) = 111
        piccdata(1) = 111
        piccdata(2) = 222
        piccdata(3) = 222
        
        status = piccwrite_ul(7, VarPtr(piccdata(0))) '写卡只能写4个字节
    
    End If
    
    
   Select Case status

        Case 0:
            pcdbeep 50
            MsgBox "写卡成功"
            
        Case 8:
        
            MsgBox "请将卡放在感应区"
            
       
        Case Else
            MsgBox "异常,错误代码为" + CStr(status)

    End Select
    

End Sub

Private Sub Command11_Click()
'轻松写卡
'技术支持:
'网站:
Dim i As Integer

Dim status As Byte '存放返回值

Dim myblockno As Byte '区号
Dim myblocksize As Byte '块号

Dim myctrlword As Byte '控制字

Dim mypiccserial(0 To 6) As Byte 'Utralight卡序列号为7个字节

Dim mypiccdata(0 To 100) As Byte '卡数据缓冲


'控制字指定,控制字的含义请查看本公司网站提供的动态库说明
myctrlword = 0

'指定区号
myblockno = 4 '指定为第8区
'批定密码模式
myblocksize = 12


'指定卡数据
For i = 0 To 47
    mypiccdata(i) = 47 - i
Next i

status = piccwriteex_ul(myctrlword, VarPtr(mypiccserial(0)), myblockno, myblocksize, VarPtr(mypiccdata(0)))
'在下面设定断点，然后查看mypiccserial、mypiccdata，
'调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
'开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
'处理返回函数
Select Case status

    Case 0:
        pcdbeep 50
        MsgBox "写卡成功"
        
    Case 8:
    
        MsgBox "请将卡放在感应区"
    
    Case Else
        MsgBox "异常,错误代码为" + CStr(status)

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

Private Sub Command12_Click()

'轻松读卡
'技术支持:
'网站:
Dim status As Byte '存放返回值

Dim myblockno As Byte '区号
Dim myblocksize As Byte '块号

Dim myctrlword As Byte '控制字

Dim mypiccserial(0 To 6) As Byte 'Utralight卡序列号为7个字节

Dim mypiccdata(0 To 100) As Byte '卡数据缓冲


'控制字指定,控制字的含义请查看本公司网站提供的动态库说明
myctrlword = 0 '如果指定NEEDSERIAL表示只操作指定卡号的卡

'指定区号
myblockno = 4 '指定启始块为8块
'
myblocksize = 12 '操作的块数，每块为4个字节
         
status = piccreadex_ul(myctrlword, VarPtr(mypiccserial(0)), myblockno, myblocksize, VarPtr(mypiccdata(0)))
'在下面设定断点，然后查看mypiccserial、mypiccdata，
'调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
'开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
'处理返回函数

'Debug.Print mypiccserial(0), mypiccserial(1), mypiccserial(2), mypiccserial(3)


'm_myDouble = mypiccserial(3)
'm_myDouble = m_myDouble * 256
'm_myDouble = m_myDouble + mypiccserial(2)
'm_myDouble = m_myDouble * 256
'm_myDouble = m_myDouble + mypiccserial(1)
'm_myDouble = m_myDouble * 256
'm_myDouble = m_myDouble + mypiccserial(0)

'm_mystr = "0000000000" + CStr(m_myDouble)

'm_mystr = Right(m_mystr, 10) '十位卡号

'Debug.Print m_mystr

Select Case status

    Case 0:

        MsgBox "操作成功"

    Case 8:

        MsgBox "请将卡放在感应区"

    Case 21 '没有动态库
        MsgBox "找不到动态库ICUSB.DLL请将ICUSB.DLL拷贝到VB安装后的目录VB98下"

    Case Else
        
        MsgBox "异常，错误代码：" + CStr(status)

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
        MsgBox "异常,错误代码为" + CStr(status)

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
Dim status As Byte
status = pcdbeep(50)

If status > 0 Then
    'MsgBox CStr(status)
End If

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
'轻松读卡
'技术支持:
'网站:
Dim i As Byte

Dim status As Byte '存放返回值

Dim myareano As Byte '区号
Dim authmode As Byte '密码类型，用A密码或B密码

Dim mypicckey(0 To 5) As Byte '密码
Dim mypiccserial(0 To 3) As Byte '卡序列号
Dim mypiccdata(0 To 255) As Byte '卡数据缓冲





'指定区号
myareano = 32 '指定为第32区
'批定密码模式
authmode = 1 '大于0表示用A密码认证，推荐用A密码认证

'指定密码
mypicckey(0) = &HFF
mypicckey(1) = &HFF
mypicckey(2) = &HFF
mypicckey(3) = &HFF
mypicckey(4) = &HFF
mypicckey(5) = &HFF


'寻卡
status = piccrequest(VarPtr(mypiccserial(0)))

'卡密码认证
If status = 0 Then

    status = piccauthkey1(VarPtr(mypiccserial(0)), myareano, authmode, VarPtr(mypicckey(0)))

End If

'读32区0块~14块的数，15块为密码控制块，轻易不要动作
If status = 0 Then
    For i = 0 To 14
    
        status = piccread((myareano - 32) * 16 + 128 + i, VarPtr(mypiccdata(i * 16))) '第一个参数中的16和128为32~39区的固定数,其他0~31区可以status = piccread(myareano * 4 + i, VarPtr(mypiccdata(i * 16)))
    Next i
    

End If


'在下面设定断点，然后查看mypiccserial、mypiccdata，
'调用完 piccread函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
'开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
'处理返回函数
Select Case status

    Case 0:
    
        MsgBox "操作成功"
        
    Case 8:
        MsgBox "请将卡放在感应区"
    Case 12:
    
        MsgBox "密码错误"
        
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
    '轻松读卡
'技术支持:
'网站:
Dim i As Byte

Dim status As Byte '存放返回值

Dim myareano As Byte '区号
Dim authmode As Byte '密码类型，用A密码或B密码

Dim mypicckey(0 To 5) As Byte '密码
Dim mypiccserial(0 To 3) As Byte '卡序列号
Dim mypiccdata(0 To 255) As Byte '卡数据缓冲





'指定区号
myareano = 32 '指定为第32区
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
For i = 0 To 255
    mypiccdata(i) = i
Next i

'寻卡
status = piccrequest(VarPtr(mypiccserial(0)))

'卡密码认证
If status = 0 Then

    status = piccauthkey1(VarPtr(mypiccserial(0)), myareano, authmode, VarPtr(mypicckey(0)))

End If

'读32区0块~14块的数，15块为密码控制块，轻易不要动作
If status = 0 Then
    For i = 0 To 14
    
        status = piccwrite((myareano - 32) * 16 + 128 + i, VarPtr(mypiccdata(i * 16))) '第一个参数中的16和128为32~39区的固定数,其他0~31区可以status = piccread(myareano * 4 + i, VarPtr(mypiccdata(i * 16)))
    Next i
    

End If


'在下面设定断点，然后查看mypiccserial、mypiccdata，
'调用完 piccread函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
'开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
'处理返回函数
Select Case status

    Case 0:
    
        MsgBox "操作成功"
        
    Case 8:
    
        MsgBox "请将卡放在感应区"
    
    Case 12:
    
        MsgBox "密码错误"
        
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

Private Sub Command8_Click()
'读取设备编号，可做为软件加密狗用,也可以根据此编号在公司网站上查询保修期限

'技术支持:
'网站:
Dim status As Byte

Dim serialul(0 To 6) As Byte '设备编号

status = piccrequest_ul(VarPtr(serialul(0)))

If status = 0 Then
    pcdbeep 50
    MsgBox "读卡成功，卡号：" + CStr(serialul(0)) + "-" + CStr(serialul(1)) + "-" + CStr(serialul(2)) + "-" + CStr(serialul(3)) + "-" + CStr(serialul(4)) + "-" + CStr(serialul(5)) + "-" + CStr(serialul(6))
    
Else
    MsgBox "异常代码：" + CStr(status)
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
    Dim status As Byte
    
    Dim serialul(0 To 6) As Byte '设备编号
    Dim piccdata(0 To 15) As Byte
    
    status = piccrequest_ul(VarPtr(serialul(0)))
    
    If stauts = 0 Then
        status = piccread_ul(4, VarPtr(piccdata(0)))
    
    End If
    
    If status = 0 Then
        pcdbeep 50
        MsgBox "读卡成功，卡号：" + CStr(serialul(0)) + "-" + CStr(serialul(1)) + "-" + CStr(serialul(2)) + "-" + CStr(serialul(3)) + "-" + CStr(serialul(4)) + "-" + CStr(serialul(5)) + "-" + CStr(serialul(6)) _
        + Chr(13) + Chr(10) + "数据：" + CStr(piccdata(0)) + "-" + CStr(piccdata(1)) + "-" + CStr(piccdata(2)) + "-" + CStr(piccdata(3)) + "-" + CStr(piccdata(4)) + "-" + CStr(piccdata(5)) _
        + "-" + CStr(piccdata(6)) + "-" + CStr(piccdata(7)) + "-" + CStr(piccdata(8)) + "-" + CStr(piccdata(9)) + "-" + CStr(piccdata(10)) + "-" + CStr(piccdata(11)) + "-" + CStr(piccdata(12)) _
         + "-" + CStr(piccdata(13)) + "-" + CStr(piccdata(14)) + "-" + CStr(piccdata(15))
    
    Else
        MsgBox "异常代码：" + CStr(status)
    End If
End Sub
