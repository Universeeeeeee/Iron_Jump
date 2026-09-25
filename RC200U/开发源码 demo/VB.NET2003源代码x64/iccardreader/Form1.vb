
Public Class Form1
    Inherits System.Windows.Forms.Form

#Region " Windows 窗体设计器生成的代码 "

    Public Sub New()
        MyBase.New()

        '该调用是 Windows 窗体设计器所必需的。
        InitializeComponent()

        '在 InitializeComponent() 调用之后添加任何初始化

    End Sub

    '窗体重写 dispose 以清理组件列表。
    Protected Overloads Overrides Sub Dispose(ByVal disposing As Boolean)
        If disposing Then
            If Not (components Is Nothing) Then
                components.Dispose()
            End If
        End If
        MyBase.Dispose(disposing)
    End Sub

    'Windows 窗体设计器所必需的
    Private components As System.ComponentModel.IContainer

    '注意: 以下过程是 Windows 窗体设计器所必需的
    '可以使用 Windows 窗体设计器修改此过程。
    '不要使用代码编辑器修改它。
    Friend WithEvents Button1 As System.Windows.Forms.Button
    Friend WithEvents Button2 As System.Windows.Forms.Button
    Friend WithEvents Button3 As System.Windows.Forms.Button
    Friend WithEvents Button4 As System.Windows.Forms.Button
    Friend WithEvents Button5 As System.Windows.Forms.Button
    Friend WithEvents Label1 As System.Windows.Forms.Label
    Friend WithEvents Label2 As System.Windows.Forms.Label
    Friend WithEvents Label3 As System.Windows.Forms.Label
    Friend WithEvents Label4 As System.Windows.Forms.Label
    <System.Diagnostics.DebuggerStepThrough()> Private Sub InitializeComponent()
        Me.Button1 = New System.Windows.Forms.Button
        Me.Button2 = New System.Windows.Forms.Button
        Me.Button3 = New System.Windows.Forms.Button
        Me.Button4 = New System.Windows.Forms.Button
        Me.Button5 = New System.Windows.Forms.Button
        Me.Label1 = New System.Windows.Forms.Label
        Me.Label2 = New System.Windows.Forms.Label
        Me.Label3 = New System.Windows.Forms.Label
        Me.Label4 = New System.Windows.Forms.Label
        Me.SuspendLayout()
        '
        'Button1
        '
        Me.Button1.Location = New System.Drawing.Point(8, 16)
        Me.Button1.Name = "Button1"
        Me.Button1.Size = New System.Drawing.Size(120, 40)
        Me.Button1.TabIndex = 0
        Me.Button1.Text = "轻松读卡"
        '
        'Button2
        '
        Me.Button2.Location = New System.Drawing.Point(136, 16)
        Me.Button2.Name = "Button2"
        Me.Button2.Size = New System.Drawing.Size(120, 40)
        Me.Button2.TabIndex = 1
        Me.Button2.Text = "轻松写卡"
        '
        'Button3
        '
        Me.Button3.Location = New System.Drawing.Point(264, 16)
        Me.Button3.Name = "Button3"
        Me.Button3.Size = New System.Drawing.Size(120, 40)
        Me.Button3.TabIndex = 2
        Me.Button3.Text = "改单区密码"
        '
        'Button4
        '
        Me.Button4.Location = New System.Drawing.Point(392, 16)
        Me.Button4.Name = "Button4"
        Me.Button4.Size = New System.Drawing.Size(120, 40)
        Me.Button4.TabIndex = 3
        Me.Button4.Text = "让设备发出声响"
        '
        'Button5
        '
        Me.Button5.Location = New System.Drawing.Point(8, 64)
        Me.Button5.Name = "Button5"
        Me.Button5.Size = New System.Drawing.Size(504, 40)
        Me.Button5.TabIndex = 4
        Me.Button5.Text = "读出设备全球唯一的设备编号，作为加密狗用"
        '
        'Label1
        '
        Me.Label1.Location = New System.Drawing.Point(48, 136)
        Me.Label1.Name = "Label1"
        Me.Label1.Size = New System.Drawing.Size(424, 16)
        Me.Label1.TabIndex = 5
        Me.Label1.Text = "建议将ICUSB.dll和OUR_MIFARE.dll复制到应用程序同一目录下"
        '
        'Label2
        '
        Me.Label2.Location = New System.Drawing.Point(48, 168)
        Me.Label2.Name = "Label2"
        Me.Label2.Size = New System.Drawing.Size(424, 16)
        Me.Label2.TabIndex = 6
        Me.Label2.Text = "每个按钮只调用到一个函数，以上4个函数可以轻松应付各类应用，可以节省大量的开发时间"
        '
        'Label3
        '
        Me.Label3.Font = New System.Drawing.Font("宋体", 15.75!, System.Drawing.FontStyle.Regular, System.Drawing.GraphicsUnit.Point, CType(134, Byte))
        Me.Label3.ForeColor = System.Drawing.Color.Red
        Me.Label3.Location = New System.Drawing.Point(168, 200)
        Me.Label3.Name = "Label3"
        Me.Label3.Size = New System.Drawing.Size(168, 40)
        Me.Label3.TabIndex = 7
        Me.Label3.Text = "读写器例子程序"
        '
        'Label4
        '
        Me.Label4.ForeColor = System.Drawing.Color.Red
        Me.Label4.Location = New System.Drawing.Point(48, 112)
        Me.Label4.Name = "Label4"
        Me.Label4.Size = New System.Drawing.Size(424, 16)
        Me.Label4.TabIndex = 8
        Me.Label4.Text = "在VB.net的编辑状态下双击以上按钮可以查看代码"
        '
        'Form1
        '
        Me.AutoScaleBaseSize = New System.Drawing.Size(6, 14)
        Me.ClientSize = New System.Drawing.Size(520, 262)
        Me.Controls.Add(Me.Label4)
        Me.Controls.Add(Me.Label3)
        Me.Controls.Add(Me.Label2)
        Me.Controls.Add(Me.Label1)
        Me.Controls.Add(Me.Button5)
        Me.Controls.Add(Me.Button4)
        Me.Controls.Add(Me.Button3)
        Me.Controls.Add(Me.Button2)
        Me.Controls.Add(Me.Button1)
        Me.Name = "Form1"
        Me.Text = "Form1"
        Me.ResumeLayout(False)

    End Sub

#End Region

    Private Sub Button1_Click(ByVal sender As System.Object, ByVal e As System.EventArgs) Handles Button1.Click

        '轻松读卡
        '技术支持:
        '网站:

        Dim data() As Byte
        Dim status As Byte '存放返回值

        Dim addrlong As IntPtr


        Dim myareano As Byte '区号
        Dim authmode As Byte '密码类型，用A密码或B密码
        Dim myctrlword As Byte '控制字

        Dim mypiccserial(3) As Byte '卡序列号,从0~3四个字节
        Dim mypicckey(5) As Byte '密码,从0~5六个字节
        Dim mypiccdata(47) As Byte '卡数据缓冲,从0~47四十八个字节




        'Dim mypiccserial As stru_serial '卡序列号
        'Dim mypicckey As stru_picckey '密码
        'Dim mypiccdata As stru_piccdata0_2 '卡数据缓冲

        'Public Structure stru_serial

        'Public Structure stru_picckey

        'Public Structure stru_piccdata0_2

        '控制字指定,控制字的含义请查看本公司网站提供的动态库说明
        myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY

        '指定区号
        myareano = 8 '指定为第8区
        '批定密码模式
        authmode = 1 '大于0表示用A密码认证，推荐用A密码认证

        '指定密码

        'mypicckey.picckey0 = (&HFF)
        'mypicckey.picckey1 = (&HFF)
        'mypicckey.picckey2 = (&HFF)
        'mypicckey.picckey3 = (&HFF)
        'mypicckey.picckey4 = (&HFF)
        'mypicckey.picckey5 = (&HFF)

        mypicckey(0) = (&HFF)
        mypicckey(1) = (&HFF)
        mypicckey(2) = (&HFF)
        mypicckey(3) = (&HFF)
        mypicckey(4) = (&HFF)
        mypicckey(5) = (&HFF)

        authmode = &HAA

        status = piccreadex(myctrlword, mypiccserial(0), myareano, authmode, mypicckey(0), mypiccdata(0))
        '在下面设定断点，然后查看mypiccserial、mypiccdata，
        '调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
        '开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
        '处理返回函数
        Select Case status

            Case 0


                MsgBox("操作成功")

            Case 8

                MsgBox("请将卡放在感应区")
            Case 12
                MsgBox("卡密码认证失败")

            Case 21 '没有动态库
                MsgBox("找不到动态库ICUSB.DLL，请将ICUSB.DLL拷贝到当前项目的bin目录下")

            Case Else
                MsgBox("异常")

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

    Private Sub Button5_Click(ByVal sender As System.Object, ByVal e As System.EventArgs) Handles Button5.Click
        '读取设备编号，可做为软件加密狗用,也可以根据此编号在公司网站上查询保修期限

        '技术支持:
        '网站:
        Dim status As Byte '存放返回值
        Dim devno(3) As Byte '设备编号

        status = pcdgetdevicenumber(devno(0))

        If status = 0 Then
            MsgBox(CStr(devno(0)) + "-" + CStr(devno(1)) + "-" + CStr(devno(2)) + "-" + CStr(devno(3)))
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

    Private Sub Button4_Click(ByVal sender As System.Object, ByVal e As System.EventArgs) Handles Button4.Click
        pcdbeep(50)
    End Sub

    Private Sub Button2_Click(ByVal sender As System.Object, ByVal e As System.EventArgs) Handles Button2.Click
        '轻松写卡
        '技术支持:
        '网站:
        Dim i As Integer
        Dim status As Byte '存放返回值
        Dim myareano As Byte '区号
        Dim authmode As Byte '密码类型，用A密码或B密码
        Dim myctrlword As Byte '控制字
        Dim mypicckey(5) As Byte '密码
        Dim mypiccserial(3) As Byte '卡序列号
        Dim mypiccdata(47) As Byte '卡数据缓冲


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

        status = piccwriteex(myctrlword, mypiccserial(0), myareano, authmode, mypicckey(0), mypiccdata(0))
        '在下面设定断点，然后查看mypiccserial、mypiccdata，
        '调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
        '开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
        '处理返回函数
        Select Case status

            Case 0

                MsgBox("操作成功")

            Case 8

                MsgBox("请将卡放在感应区")
            Case 12

                MsgBox("卡密码认证失败")

            Case 21 '没有动态库
                MsgBox("找不到动态库ICUSB.DLL，请将ICUSB.DLL拷贝到当前项目的bin目录下")

            Case Else
                MsgBox("异常")

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

    Private Sub Button3_Click(ByVal sender As System.Object, ByVal e As System.EventArgs) Handles Button3.Click
        '修改单区密码
        '技术支持:
        '网站:
        Dim i As Integer

        Dim status As Byte '存放返回值
        Dim myareano As Byte '区号
        Dim authmode As Byte '密码类型，用A密码或B密码
        Dim myctrlword As Byte '控制字
        Dim mypiccserial(3) As Byte '卡序列号
        Dim mypiccoldkey(5) As Byte '旧密码
        Dim mypiccnewkey(5) As Byte '新密码







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

        status = piccchangesinglekey(myctrlword, mypiccserial(0), myareano, authmode, mypiccoldkey(0), mypiccnewkey(0))

        '处理返回函数
        Select Case status

            Case 0

                MsgBox("操作成功")

            Case 8

                MsgBox("请将卡放在感应区")
            Case 12

                MsgBox("卡密码认证失败")

            Case 21 '没有动态库
                MsgBox("找不到动态库WY-ICUSB.DLL请将WY-ICUSB.DLL拷贝到VB安装后的目录VB98下")

            Case Else
                MsgBox("异常")

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
End Class
