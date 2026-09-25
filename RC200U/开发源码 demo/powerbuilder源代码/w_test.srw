$PBExportHeader$w_test.srw
$PBExportComments$OC-01读写器
forward
global type w_test from window
end type
type cb_5 from commandbutton within w_test
end type
type cb_4 from commandbutton within w_test
end type
type cb_3 from commandbutton within w_test
end type
type cb_2 from commandbutton within w_test
end type
type cb_1 from commandbutton within w_test
end type
end forward

global type w_test from window
integer width = 2464
integer height = 1128
boolean titlebar = true
string title = "Untitled"
boolean controlmenu = true
boolean minbox = true
boolean maxbox = true
boolean resizable = true
long backcolor = 67108864
string icon = "AppIcon!"
boolean center = true
cb_5 cb_5
cb_4 cb_4
cb_3 cb_3
cb_2 cb_2
cb_1 cb_1
end type
global w_test w_test

type prototypes
//IC-01读写器
//020-82301718 138-26029618 王生 80760223@qq.com
FUNCTION Integer piccreadex ( Char ctrlword , REF Char serial[4] , Integer area , Integer keyA1B0 , Char picckey[6] , REF Char piccdata0_2[48] ) LIBRARY "OUR_MIFARE.dll" //读卡
FUNCTION Integer piccwriteex ( Char ctrlword , Char serial[4] , Integer area , Integer keyA1B0 , Char picckey[6] , Char piccdata0_2[48] ) LIBRARY "OUR_MIFARE.dll" //写卡
FUNCTION Integer pcdbeep ( Integer xms ) LIBRARY "OUR_MIFARE.dll" //设备发声
FUNCTION Integer piccchangesinglekey ( Char ctrlword , Char serial[4] , Integer area , Integer keyA1B0 , Char piccoldkey[6] , Char piccnewkey[6] ) LIBRARY "OUR_MIFARE.dll" //修改密码
FUNCTION Integer pcdgetdevicenumber ( REF Char devicenumber[4] ) LIBRARY "OUR_MIFARE.dll" //读设备编号
FUNCTION Integer piccrequest ( REF Char serial[4] ) LIBRARY "OUR_MIFARE.dll" //寻卡并返回该卡的序列号
FUNCTION Integer piccrequestex ( REF Char serial[4] ) LIBRARY "OUR_MIFARE.dll" //寻卡并选中指定序列号的IC卡
FUNCTION Integer piccauthkey1 ( Char serial[4] , Integer area , Integer keyA1B0 , Char picckey[6] ) LIBRARY "OUR_MIFARE.dll" //密码认证方式1
FUNCTION Integer piccauthkey2 ( Char serial[4] , Integer area , Integer keyA1B0 ) LIBRARY "OUR_MIFARE.dll" //密码认证方式2
FUNCTION Integer pcdwritekeytoe2 ( Integer area , Integer keyA1B0 , Char picckey[6] ) LIBRARY "OUR_MIFARE.dll" //将密码写入芯片内部保密性极高的只写区域
FUNCTION Integer piccread ( Integer block , REF Char piccdata[48] ) LIBRARY "OUR_MIFARE.dll" //读块
FUNCTION Integer piccwrite ( Integer block , Char piccdata[48] ) LIBRARY "OUR_MIFARE.dll" //写块
FUNCTION Integer picchalt ( ) LIBRARY "OUR_MIFARE.dll" //休眠选中卡

end prototypes
type variables
PRIVATE:
CONSTANT PRIVATE Integer BLOCK0_EN = 1
CONSTANT PRIVATE Integer BLOCK1_EN = 2
CONSTANT PRIVATE Integer BLOCK2_EN = 4
CONSTANT PRIVATE Integer NEEDSERIAL = 8
CONSTANT PRIVATE Integer EXTERNKEY = 16
CONSTANT PRIVATE Integer NEEDHALT = 32

end variables

forward prototypes
public subroutine msgbox (string as_msg)
end prototypes

public subroutine msgbox (string as_msg);MessageBox ( "标题" , as_msg )

end subroutine

on w_test.create
this.cb_5=create cb_5
this.cb_4=create cb_4
this.cb_3=create cb_3
this.cb_2=create cb_2
this.cb_1=create cb_1
this.Control[]={this.cb_5,&
this.cb_4,&
this.cb_3,&
this.cb_2,&
this.cb_1}
end on

on w_test.destroy
destroy(this.cb_5)
destroy(this.cb_4)
destroy(this.cb_3)
destroy(this.cb_2)
destroy(this.cb_1)
end on

type cb_5 from commandbutton within w_test
integer x = 91
integer y = 676
integer width = 457
integer height = 128
integer taborder = 50
integer textsize = -9
integer weight = 400
fontcharset fontcharset = ansi!
fontpitch fontpitch = variable!
fontfamily fontfamily = swiss!
string facename = "Arial"
string text = "设备编号"
end type

event clicked;//设备编号
String ls_tmp
Integer li_rtn
Char devicenumber[4]
li_rtn = pcdgetdevicenumber ( devicenumber )
ls_tmp = String ( Asc (devicenumber[1]) ) +"-"+ String ( Asc (devicenumber[2]) ) +"-"+ String ( Asc (devicenumber[3]) ) +"-"+ String ( Asc (devicenumber[4]) )
debugbreak ()
MsgBox ( ls_tmp )

end event

type cb_4 from commandbutton within w_test
integer x = 91
integer y = 528
integer width = 457
integer height = 128
integer taborder = 40
integer textsize = -9
integer weight = 400
fontcharset fontcharset = ansi!
fontpitch fontpitch = variable!
fontfamily fontfamily = swiss!
string facename = "Arial"
string text = "设备发声"
end type

event clicked;//设备发声
Integer li_rtn
li_rtn = pcdbeep (1000)

end event

type cb_3 from commandbutton within w_test
integer x = 91
integer y = 380
integer width = 457
integer height = 128
integer taborder = 30
integer textsize = -9
integer weight = 400
fontcharset fontcharset = ansi!
fontpitch fontpitch = variable!
fontfamily fontfamily = swiss!
string facename = "Arial"
string text = "修改密码"
end type

event clicked;//修改密码
Integer li_rtn, area, keya1b0
Char ctrlword, serial[4], piccoldkey[6], piccnewkey[6]

area = 1
keya1b0 = 1
ctrlword = Char ( BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY )
piccoldkey = { "~hFF" , "~hFF" , "~hFF" , "~hFF" , "~hFF" , "~hFF" }
piccnewkey = { "~h31" , "~h31" , "~h31" , "~h31" , "~h31" , "~h31" }
li_rtn = piccchangesinglekey ( ctrlword , serial , area , keya1b0 , piccoldkey , piccnewkey )
DebugBreak ()
CHOOSE CASE li_rtn
	CASE 0
		MsgBox("操作成功")
	CASE 8
		MsgBox("请将卡放在感应区")
	CASE 21 //没有动态库
		MsgBox("找不到接口文件ICUSB.DLL和OUR_MIFARE.dll")
	CASE ELSE
		MsgBox("异常")
END CHOOSE

end event

type cb_2 from commandbutton within w_test
integer x = 91
integer y = 232
integer width = 457
integer height = 128
integer taborder = 20
integer textsize = -9
integer weight = 400
fontcharset fontcharset = ansi!
fontpitch fontpitch = variable!
fontfamily fontfamily = swiss!
string facename = "Arial"
string text = "写卡操作"
end type

event clicked;//写卡
Integer li_rtn, i, area, keya1b0
Char ctrlword, serial[4], picckey[6], piccdata0_2[48]

area = 1
keya1b0 = 1
ctrlword = Char ( BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY )
picckey = { "~hFF" , "~hFF" , "~hFF" , "~hFF" , "~hFF" , "~hFF" }
for i = 1 to 48
	piccdata0_2[i] = "~h33"
next
li_rtn = piccwriteex ( ctrlword , serial , area , keya1b0 , picckey , piccdata0_2 )
DebugBreak ()
CHOOSE CASE li_rtn
	CASE 0
		MsgBox("操作成功")
	CASE 8
		MsgBox("请将卡放在感应区")
	CASE 21 //没有动态库
		MsgBox("找不到接口文件ICUSB.DLL和OUR_MIFARE.dll")
	CASE ELSE
		MsgBox("异常")
END CHOOSE

end event

type cb_1 from commandbutton within w_test
integer x = 91
integer y = 84
integer width = 457
integer height = 128
integer taborder = 10
integer textsize = -9
integer weight = 400
fontcharset fontcharset = ansi!
fontpitch fontpitch = variable!
fontfamily fontfamily = swiss!
string facename = "Arial"
string text = "读卡操作"
end type

event clicked;//读卡
Integer i, li_rtn, area, keya1b0
Char ctrlword, serial[4], picckey[6], piccdata0_2[48]

area = 1
keya1b0 = 1
ctrlword = Char ( BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY ) // + NEEDSERIAL
picckey = { "~hFF" , "~hFF" , "~hFF" , "~hFF" , "~hFF" , "~hFF" }
li_rtn = piccreadex ( ctrlword , serial , area , keya1b0 , picckey , piccdata0_2 )
DebugBreak ()
CHOOSE CASE li_rtn
	CASE 0
		MsgBox("操作成功")
	CASE 8
		MsgBox("请将卡放在感应区")
	CASE 21 //没有动态库
		MsgBox("找不到接口文件ICUSB.DLL和OUR_MIFARE.dll")
	CASE ELSE
		MsgBox("异常")
END CHOOSE

end event

