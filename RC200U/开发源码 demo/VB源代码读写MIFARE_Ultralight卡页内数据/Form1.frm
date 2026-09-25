VERSION 5.00
Begin VB.Form Form1 
   Caption         =   "Form1"
   ClientHeight    =   7875
   ClientLeft      =   60
   ClientTop       =   450
   ClientWidth     =   14730
   ForeColor       =   &H8000000F&
   LinkTopic       =   "Form1"
   ScaleHeight     =   7875
   ScaleWidth      =   14730
   StartUpPosition =   2  'CenterScreen
   Begin VB.PictureBox Picture1 
      AutoSize        =   -1  'True
      Height          =   6105
      Left            =   7320
      Picture         =   "Form1.frx":0000
      ScaleHeight     =   6045
      ScaleWidth      =   7320
      TabIndex        =   28
      Top             =   600
      Width           =   7380
   End
   Begin VB.TextBox Text9 
      Height          =   285
      Left            =   2400
      TabIndex        =   26
      Top             =   5640
      Width           =   3735
   End
   Begin VB.CommandButton Command8 
      Caption         =   "轻松写卡，最多一次12块"
      Height          =   495
      Left            =   3000
      TabIndex        =   24
      Top             =   7080
      Width           =   2415
   End
   Begin VB.TextBox Text8 
      Height          =   285
      Left            =   1200
      TabIndex        =   22
      Text            =   "1"
      Top             =   6045
      Width           =   495
   End
   Begin VB.CommandButton Command6 
      Caption         =   "轻松读卡，最多一次12块"
      Height          =   495
      Left            =   240
      TabIndex        =   19
      Top             =   7080
      Width           =   2415
   End
   Begin VB.TextBox Text7 
      Height          =   285
      Left            =   1200
      TabIndex        =   18
      Text            =   "4"
      Top             =   5610
      Width           =   495
   End
   Begin VB.TextBox Text6 
      Height          =   855
      Left            =   2400
      MultiLine       =   -1  'True
      TabIndex        =   17
      Top             =   6120
      Width           =   3735
   End
   Begin VB.CommandButton Command3 
      Caption         =   "锁定指定页"
      Height          =   375
      Left            =   120
      TabIndex        =   16
      Top             =   4200
      Width           =   1695
   End
   Begin VB.TextBox Text5 
      Height          =   285
      Left            =   2280
      TabIndex        =   14
      Text            =   "0"
      Top             =   3525
      Width           =   495
   End
   Begin VB.CommandButton Command2 
      Caption         =   "写1个页"
      Height          =   375
      Left            =   120
      TabIndex        =   12
      Top             =   3480
      Width           =   1215
   End
   Begin VB.TextBox Text4 
      Height          =   375
      Left            =   3840
      MaxLength       =   8
      TabIndex        =   11
      Text            =   "00000000"
      Top             =   3480
      Width           =   975
   End
   Begin VB.TextBox Text3 
      Height          =   375
      Left            =   3840
      TabIndex        =   9
      Top             =   2880
      Width           =   3255
   End
   Begin VB.TextBox Text2 
      Height          =   285
      Left            =   2280
      TabIndex        =   8
      Text            =   "0"
      Top             =   2925
      Width           =   495
   End
   Begin VB.CommandButton Command1 
      Caption         =   "读4个页"
      Height          =   375
      Left            =   120
      TabIndex        =   6
      Top             =   2880
      Width           =   1215
   End
   Begin VB.CommandButton Command7 
      Caption         =   "读卡序列号"
      Height          =   375
      Left            =   120
      TabIndex        =   5
      Top             =   2100
      Width           =   3615
   End
   Begin VB.TextBox Text1 
      Height          =   495
      Left            =   3840
      TabIndex        =   4
      Top             =   2040
      Width           =   3255
   End
   Begin VB.CommandButton Command5 
      Caption         =   "读出设备全球唯一的设备编号，作为加密狗用"
      Height          =   540
      Left            =   120
      TabIndex        =   1
      Top             =   1080
      Width           =   4905
   End
   Begin VB.CommandButton Command4 
      Caption         =   "让设备发出声响"
      Height          =   540
      Left            =   5280
      TabIndex        =   0
      Top             =   1080
      Width           =   1815
   End
   Begin VB.Label Label1 
      AutoSize        =   -1  'True
      Caption         =   "Ultralight卡的卡结构表："
      Height          =   195
      Left            =   7440
      TabIndex        =   29
      Top             =   240
      Width           =   1875
   End
   Begin VB.Label Label12 
      Caption         =   "卡号"
      Height          =   195
      Left            =   1920
      TabIndex        =   27
      Top             =   5640
      Width           =   360
   End
   Begin VB.Label Label11 
      Caption         =   "用以下两条函数，就可以轻松操作Ultralight卡"
      Height          =   195
      Left            =   240
      TabIndex        =   25
      Top             =   5040
      Width           =   3495
   End
   Begin VB.Label Label10 
      Caption         =   "块数"
      Height          =   195
      Left            =   720
      TabIndex        =   23
      Top             =   6090
      Width           =   360
   End
   Begin VB.Label Label9 
      Caption         =   "起始块号"
      Height          =   195
      Left            =   360
      TabIndex        =   21
      Top             =   5610
      Width           =   720
   End
   Begin VB.Label Label7 
      Caption         =   "数据"
      Height          =   195
      Left            =   1920
      TabIndex        =   20
      Top             =   6090
      Width           =   360
   End
   Begin VB.Line Line1 
      BorderColor     =   &H0000C000&
      BorderWidth     =   5
      X1              =   -120
      X2              =   7320
      Y1              =   4800
      Y2              =   4800
   End
   Begin VB.Label Label8 
      Caption         =   "起始页号"
      Height          =   255
      Left            =   1440
      TabIndex        =   15
      Top             =   3540
      Width           =   735
   End
   Begin VB.Label Label6 
      Caption         =   "写入数据"
      Height          =   255
      Left            =   3000
      TabIndex        =   13
      Top             =   3540
      Width           =   735
   End
   Begin VB.Label Label5 
      Caption         =   "读出数据"
      Height          =   255
      Left            =   3000
      TabIndex        =   10
      Top             =   2940
      Width           =   735
   End
   Begin VB.Label Label3 
      Caption         =   "起始页号"
      Height          =   255
      Left            =   1440
      TabIndex        =   7
      Top             =   2940
      Width           =   735
   End
   Begin VB.Label Label4 
      Caption         =   "Mifare Ultralight卡读写器例子程序"
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
      Left            =   1320
      TabIndex        =   3
      Top             =   120
      Width           =   4695
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
      Left            =   240
      TabIndex        =   2
      Top             =   600
      Width           =   6090
   End
End
Attribute VB_Name = "Form1"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Option Explicit

'寻卡选卡激活卡
Private Declare Function piccrequest_ul Lib "OUR_MIFARE.dll" (ByVal serial As Long) As Byte

'读块
Private Declare Function piccread_ul Lib "OUR_MIFARE.dll" (ByVal blockaddr As Byte, ByVal piccdata As Long) As Byte

'写块
Private Declare Function piccwrite_ul Lib "OUR_MIFARE.dll" (ByVal blockaddr As Byte, ByVal piccdata As Long) As Byte

'让设备发出声响函数声明
Private Declare Function pcdbeep Lib "OUR_MIFARE.dll" (ByVal xms As Long) As Byte

'读取设备编号函数声明
Private Declare Function pcdgetdevicenumber Lib "OUR_MIFARE.dll" (ByVal devicenumber As Long) As Byte
        
'控制字定义,控制字指定,控制字的含义请查看本公司网站提供的动态库说明
Private Const NEEDSERIAL = &H8
Private Const NEEDHALT = &H20

'用以下两条函数就可以轻松操作Ultralight卡

'轻松读卡
Private Declare Function piccreadex_ul Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByVal serial As Long, ByVal blockaddr As Byte, ByVal blocksize As Byte, ByVal piccdata As Long) As Byte

'轻松写卡
Private Declare Function piccwriteex_ul Lib "OUR_MIFARE.dll" (ByVal ctrlword As Byte, ByVal serial As Long, ByVal blockaddr As Byte, ByVal blocksize As Byte, ByVal piccdata As Long) As Byte

Private Sub Command1_Click()
'读页
'技术支持:
'网站:
Dim status As Byte '存放返回值

Dim mypiccserial(0 To 6) As Byte '卡序列号

Dim mypiccdata(0 To 15) As Byte '读卡的数据缓冲，Ultralight卡及NTAG21x卡的数组长度必须为16个字节，写卡的为4个字节

Dim i As Integer

Dim str As String

status = piccrequest_ul(VarPtr(mypiccserial(0)))

str = ""
Text3.Text = ""
Select Case status

    Case 0:
        For i = 0 To 6
            
            str = str + Right("0" + Hex(mypiccserial(i)), 2)
        Next i
        
        
        Text1.Text = str
        
        
        status = piccread_ul(CByte(Text2), VarPtr(mypiccdata(0)))

        
        str = ""
        Select Case status
        
            Case 0:
                For i = 0 To 15
                
                    
                    
                    str = str + Right("0" + Hex(mypiccdata(i)), 2)
                Next i
                
                
                Text3.Text = str
                
                
            Case 8:
            
                Text3.Text = "请将卡放在感应区"
                

            Case 23: '没有动态库
                Text3.Text = "请连上USB 读写器"
                
                
            Case Else
                
                Text3.Text = "异常" + CStr(status)
        
        End Select

        
    Case 8:
    
        Text1.Text = "请将卡放在感应区"
        

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

Private Sub Command2_Click()
'写页
'技术支持:
'网站:
Dim status As Byte '存放返回值

Dim mypiccserial(0 To 6) As Byte '卡序列号

Dim mypiccdata(0 To 3) As Byte '读卡的数据缓冲，Ultralight卡及NTAG21x卡的数组长度必须为16个字节，写卡的为4个字节

Dim i As Integer

Dim str As String
Dim strls1 As String
Dim strls2 As String

Dim strlen As Byte '数据字符串的长度


'取数据
strls1 = Text4.Text
strlen = Len(strls1)
str = ""

For i = 1 To strlen
    strls2 = Mid(strls1, i, 1)
    If (strls2 <> " ") And (strls2 <> vbCr) And (strls2 <> vbCrLf) And (strls2 <> vbLf) Then 'vbcr,vbcrlf,vblf
        str = str + strls2
    End If

Next i

strlen = Len(str)

If strlen < 8 Then

    MsgBox "写入数据长度不足"
    Text4.SetFocus
    Exit Sub
End If

strlen = 0
For i = 1 To 8 Step 2
    strls2 = Mid(str, i, 2)
    
    mypiccdata(strlen) = CByte("&h" & strls2)
    strlen = strlen + 1
    
Next i


status = piccrequest_ul(VarPtr(mypiccserial(0)))


str = ""

Select Case status

    Case 0:
        For i = 0 To 6
        
            
            
            str = str + Right("0" + Hex(mypiccserial(i)), 2)
        Next i
        
        
        Text1.Text = str

        status = piccwrite_ul(CByte(Text5), VarPtr(mypiccdata(0)))
        
        str = ""
        Select Case status
        
            Case 0:
                
                
                MsgBox "卡的第" + Text2 + "页数据写入成功！！！"
                
                
            Case 8:
            
                MsgBox "请将卡放在感应区"
                
        
            Case 23: '没有动态库
                MsgBox "请连上USB 读写器"
                
                
            Case Else
                
                MsgBox "异常" + CStr(status)
        
        End Select

        
        

        
    Case 8:
    
        Text1.Text = "请将卡放在感应区"
        

    Case 23: '没有动态库
        Text1.Text = "请连上USB 读写器"
        
        
    Case Else
        
        Text1.Text = "异常" + CStr(status)

End Select
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
'轻松读卡
'技术支持:
'网站:
Dim status As Byte '存放返回值

Dim myctrlword As Byte '控制字

Dim mypiccserial(0 To 6) As Byte '卡序列号

Dim myblockaddr As Byte '起始块地址

Dim myblocksize As Byte '总块数

Dim mypiccdata(0 To 47) As Byte '读卡的数据缓冲，最大可以读出12个块共48个字节

Dim i As Integer

Dim str As String

myctrlword = 0


myblockaddr = CByte(Trim(Text7.Text)) 'ULtralight卡数据块从3块开始

myblocksize = CByte(Trim(Text8.Text))

status = piccreadex_ul(myctrlword, VarPtr(mypiccserial(0)), myblockaddr, myblocksize, VarPtr(mypiccdata(0)))


Text9.Text = ""
Text6.Text = ""
Select Case status

    Case 0:
    
        str = ""
        For i = 0 To 6
            
            str = str + Right("0" + Hex(mypiccserial(i)), 2)
        Next i

        Text9.Text = str
        
        
        str = ""
        For i = 0 To (myblocksize * 4 - 1)
            
            str = str + Right("0" + Hex(mypiccdata(i)), 2)
        Next i

        Text6.Text = str
  
    Case 8:
    
        Text9.Text = "请将卡放在感应区"
        

    Case 23: '没有动态库
        Text9.Text = "请连上USB 读写器"
        
        
    Case Else
        
        Text9.Text = "异常" + CStr(status)

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
'读卡的序列号
'技术支持:
'网站:
Dim status As Byte '存放返回值

Dim mypiccserial(0 To 6) As Byte '卡序列号

Dim i As Integer

Dim str As String


status = piccrequest_ul(VarPtr(mypiccserial(0)))

str = ""
Select Case status

    Case 0:
        For i = 0 To 6
        
            
            
            str = str + Right("0" + Hex(mypiccserial(i)), 2)
        Next i
        
        
        Text1.Text = str
        
        
    Case 8:
    
        Text1.Text = "请将卡放在感应区"
        

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


Private Sub Command8_Click()
'轻松写卡
'技术支持:
'网站:
Dim status As Byte '存放返回值

Dim myctrlword As Byte '控制字

Dim mypiccserial(0 To 6) As Byte '卡序列号

Dim myblockaddr As Byte '起始块地址

Dim myblocksize As Byte '总块数

Dim mypiccdata(0 To 47) As Byte '读卡的数据缓冲，最大可以读出12个块共48个字节

Dim i As Integer

Dim mylen As Integer

Dim strls1 As String
Dim strls2 As String

Dim datastrls As String

Dim datastrlen As Integer '输入的字符长度
Dim datalen As Integer '需要的数据长度

myctrlword = 0

myblockaddr = CByte(Trim(Text7.Text)) 'ULtralight卡数据块从3块开始

myblocksize = CByte(Trim(Text8.Text))

datalen = CLng(Text8.Text) * 4
    
If (datalen < 1) Then
    MsgBox "本次写入的长度不能小于1，请重新输入！"
    Text8.SetFocus
    Exit Sub
End If

 '取数据
strls1 = Text6.Text
mylen = Len(strls1)
datastrls = ""


For i = 1 To mylen
    strls2 = Mid(strls1, i, 1)
    If (strls2 <> " ") And (strls2 <> vbCr) And (strls2 <> vbCrLf) And (strls2 <> vbLf) Then 'vbcr,vbcrlf,vblf
        datastrls = datastrls + strls2
    End If

Next i




    
datastrlen = Len(datastrls)

If (datastrlen < (datalen * 2)) Then
    MsgBox "请先补齐数据！"
    Text6.SetFocus
    Exit Sub
End If


For i = 1 To datalen
    strls2 = Mid(datastrls, (i - 1) * 2 + 1, 2)
    
    mypiccdata(i - 1) = CByte("&h" & strls2)
    
Next i
    


status = piccwriteex_ul(myctrlword, VarPtr(mypiccserial(0)), myblockaddr, myblocksize, VarPtr(mypiccdata(0)))


Select Case status

    Case 0:
    
        strls1 = ""
        For i = 0 To 6
            
            strls1 = strls1 + Right("0" + Hex(mypiccserial(i)), 2)
        Next i

        Text9.Text = strls1
        
        MsgBox "写入成功！"
        
  
    Case 8:
    
        Text9.Text = "请将卡放在感应区"
        

    Case 23: '没有动态库
        Text9.Text = "请连上USB 读写器"
        
        
    Case Else
        
        Text9.Text = "异常" + CStr(status)

End Select


End Sub
