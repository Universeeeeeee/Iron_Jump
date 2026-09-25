VERSION 5.00
Begin VB.Form Form1 
   Caption         =   "Form1"
   ClientHeight    =   3840
   ClientLeft      =   60
   ClientTop       =   450
   ClientWidth     =   7710
   ForeColor       =   &H8000000F&
   LinkTopic       =   "Form1"
   ScaleHeight     =   3840
   ScaleWidth      =   7710
   StartUpPosition =   2  'CenterScreen
   Begin VB.CommandButton Command7 
      Caption         =   "读卡序列号"
      Height          =   375
      Left            =   240
      TabIndex        =   5
      Top             =   3000
      Width           =   3615
   End
   Begin VB.TextBox Text1 
      Height          =   495
      Left            =   4680
      TabIndex        =   4
      Top             =   2880
      Width           =   2535
   End
   Begin VB.CommandButton Command5 
      Caption         =   "读出设备全球唯一的设备编号，作为加密狗用"
      Height          =   540
      Left            =   240
      TabIndex        =   1
      Top             =   1920
      Width           =   4905
   End
   Begin VB.CommandButton Command4 
      Caption         =   "让设备发出声响"
      Height          =   540
      Left            =   5400
      TabIndex        =   0
      Top             =   1920
      Width           =   1815
   End
   Begin VB.Label Label1 
      Caption         =   "能读取所有支持7个字节UID的MIFARE Ultralight/MIFARE DESFire/MIFARE Classic等不同类型卡的卡号。"
      BeginProperty Font 
         Name            =   "MS Sans Serif"
         Size            =   12
         Charset         =   0
         Weight          =   400
         Underline       =   0   'False
         Italic          =   0   'False
         Strikethrough   =   0   'False
      EndProperty
      Height          =   615
      Left            =   360
      TabIndex        =   6
      Top             =   1080
      Width           =   7215
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
      TabIndex        =   3
      Top             =   120
      Width           =   1815
   End
   Begin VB.Label Label2 
      Caption         =   "建议将OUR_MIFARE.dll复制到应用程序同一目录下"
      BeginProperty Font 
         Name            =   "MS Sans Serif"
         Size            =   12
         Charset         =   0
         Weight          =   400
         Underline       =   0   'False
         Italic          =   0   'False
         Strikethrough   =   0   'False
      EndProperty
      ForeColor       =   &H00C0C000&
      Height          =   360
      Left            =   360
      TabIndex        =   2
      Top             =   480
      Width           =   6090
   End
End
Attribute VB_Name = "Form1"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Private Declare Function piccrequest_ul Lib "OUR_MIFARE.dll" (ByVal serial As Long) As Byte

'让设备发出声响函数声明
Private Declare Function pcdbeep Lib "OUR_MIFARE.dll" (ByVal xms As Long) As Byte

'读取设备编号函数声明
Private Declare Function pcdgetdevicenumber Lib "OUR_MIFARE.dll" (ByVal devicenumber As Long) As Byte
        
'控制字定义,控制字指定,控制字的含义请查看本公司网站提供的动态库说明
Private Const BLOCK0_EN = &H1
Private Const BLOCK1_EN = &H2
Private Const BLOCK2_EN = &H4
Private Const NEEDSERIAL = &H8
Private Const EXTERNKEY = &H10
Private Const NEEDHALT = &H20


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

Private Sub Command7_Click()
'轻松读卡
'技术支持:
'网站:
Dim status As Byte '存放返回值

Dim mypiccserial(0 To 6) As Byte '卡序列号

Dim i As Integer

Dim str As String


status = piccrequest_ul(VarPtr(mypiccserial(0)))
'在下面设定断点，然后查看mypiccserial、mypiccdata，
'调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
'开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
'处理返回函数

str = ""
Select Case status

    Case 0:
        For i = 0 To 6
        
            
            
            str = str + Right("0" + Hex(mypiccserial(i)), 2)
        Next i
        
        
        Text1.Text = str
        
        
    Case 8:
    
        Text1.Text = "请将卡放在感应区"
        
    Case 21: '没有动态库
        Text1.Text = "找不到动态库ICUSB.DLL请将ICUSB.DLL拷贝到VB安装后的目录VB98下"
    

    Case 23: '没有动态库
        Text1.Text = "请连上USB 读写器"
        
        
    Case Else
        
        Text1.Text = "异常" + CStr(status)

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


