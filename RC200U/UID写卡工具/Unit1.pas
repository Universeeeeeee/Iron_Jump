unit Unit1;

interface

uses
  Windows, Messages, SysUtils, Variants, Classes, Graphics, Controls, Forms,
  Dialogs, StdCtrls, ExtCtrls,declaredll,strutils, ComCtrls,Math;

type
  TForm1 = class(TForm)
    Button4: TButton;
    Button10: TButton;
    Edit2: TEdit;
    Label1: TLabel;
    Edit3: TEdit;
    Label9: TLabel;
    Button11: TButton;
    Label10: TLabel;
    Button1: TButton;
    ListBox1: TListBox;
    CheckBox1: TCheckBox;
    CheckBox2: TCheckBox;
    CheckBox3: TCheckBox;
    RichEdit2: TRichEdit;
    Timer1: TTimer;
    Edit1: TEdit;
    Label2: TLabel;
    Button2: TButton;
    CheckBox4: TCheckBox;
    procedure Button1Click(Sender: TObject);
    procedure Button3Click(Sender: TObject);
    procedure Button5Click(Sender: TObject);
    procedure Button4Click(Sender: TObject);
    procedure Button7Click(Sender: TObject);
    procedure Button8Click(Sender: TObject);
    procedure Button9Click(Sender: TObject);
    procedure Button10Click(Sender: TObject);
    procedure Button11Click(Sender: TObject);
    procedure Timer1Timer(Sender: TObject);
    procedure Button2Click(Sender: TObject);
    procedure RichEdit2KeyPress(Sender: TObject; var Key: Char);

  private
    { Private declarations }
  public
    { Public declarations }
  end;

var
  Form1: TForm1;
  port,baud:integer;
  cardnumber:Longword;       //Longword为无符号32bit的整型
  writcardnum:Longword;      //Longword为无符号32bit的整型
  lastcardnum:Longword;

implementation

{$R *.dfm}

procedure TForm1.Button1Click(Sender: TObject);
begin
    if button1.caption='开始连续发卡' then
    begin
        button1.caption:='暂停发卡';
        button11.Enabled :=false;
        BUTTON4.Enabled :=FALSE;
        timer1.Enabled :=true;
        CheckBox1.Checked :=true;
        edit1.Text :='请在发卡器上刷新的UID卡';
    END
    ELSE
    BEGIN
        button1.caption:='开始连续发卡';
        button11.Enabled :=true;
        BUTTON4.Enabled :=true;
        timer1.Enabled :=false;
        edit1.Text :='';
    END;
end;

procedure TForm1.Button3Click(Sender: TObject);
//改单区密码
{
技术支持：
网站：
}
var
    status:byte;//存放返回值
    myareano:byte;//区号
    authmode:byte;//密码类型，用A密码或B密码
    myctrlword:byte;//控制字
	  mypiccnewkey:array[0..5] of byte;//新密码
    mypiccserial:array[0..5] of byte;//卡序列号
    mypiccoldkey:array[0..5] of byte;//旧密码

begin
 
end;

procedure TForm1.Button5Click(Sender: TObject);
//轻松读卡
{
技术支持：
网站：
}
var
        devno:array[0..3] of byte;//设备编号
begin

end;

procedure TForm1.Button4Click(Sender: TObject);
//让设备发出声音
{
技术支持：
网站：
}
begin
  pcdbeep(50);
end;


procedure TForm1.Button7Click(Sender: TObject);
var
    status:byte;//存放返回值
    myareano:byte;//区号
    authmode:byte;//密码类型，用A密码或B密码
    myctrlword:byte;//控制字
	  mypiccoldkey:array[0..5] of byte;//新密码
    mypiccserial:array[0..5] of byte;//卡序列号
    mypiccdata:array[0..16] of byte;//旧密码
begin


end;

procedure TForm1.Button8Click(Sender: TObject);
//轻松写卡
{
技术支持：
网站：
}
var
    i:integer;
    status:byte;//存放返回值
    myareano:byte;//区号
    authmode:byte;//密码类型，用A密码或B密码
    myctrlword:byte;//控制字
	  mypicckey:array[0..5] of byte;//密码
    mypiccserial:array[0..3] of byte;//卡序列号
    mypiccdata:array[0..47] of byte;//卡数据缓冲
    strls:string;
begin


end;

procedure TForm1.Button9Click(Sender: TObject);
//轻松读卡
{
技术支持：
网站：
}
var
    i:integer;
    status:byte;//存放返回值
    myareano:byte;//区号
    authmode:byte;//密码类型，用A密码或B密码
    myctrlword:byte;//控制字
	  mypicckey:array[0..5] of byte;//密码
    mypiccserial:array[0..3] of byte;//卡序列号
    mypiccdata:array[0..47] of byte;//卡数据缓冲
    str:string;
begin

 
end;

procedure TForm1.Button10Click(Sender: TObject);
var
  status:byte;//存放返回值
  mypiccserial:array[0..3] of byte;//卡序列号
  cardnumber:Longword;//Longword为无符号32bit的整型

begin
    status := piccrequest(@mypiccserial);
    case status of
          0:
          begin
             if (checkbox4.State = cbchecked) then
                 cardnumber:= mypiccserial[0]*256*256*256+mypiccserial[1]*256*256+mypiccserial[2]*256+mypiccserial[3]
             else
                 cardnumber:= mypiccserial[3]*256*256*256+mypiccserial[2]*256*256+mypiccserial[1]*256+mypiccserial[0];
             Edit2.Text := RightStr('0000000000'+IntToStr(cardnumber),10);
             Edit3.Text :=inttohex(mypiccserial[0],2)+inttohex(mypiccserial[1],2)+inttohex(mypiccserial[2],2)+inttohex(mypiccserial[3],2);
             Application.MessageBox('读卡操作成功!', '提示', MB_OK+MB_ICONINFORMATION);
          end;
          8: Application.MessageBox('请将卡放在感应区', '提示', MB_OK+MB_ICONSTOP);
        else
          begin
              Application.MessageBox(PAnsiChar(AnsiString(IntToStr(status))), '提示', MB_OK+MB_ICONSTOP);
          end;
        end;

        //返回解释
        {
        #define ERR_REQUEST 8//寻卡错误
        #define ERR_READSERIAL 9//读序列吗错误
        #define ERR_SELECTCARD 10//选卡错误
        #define ERR_LOADKEY 11//装载密码错误
        #define ERR_AUTHKEY 12//密码认证错误
        #define ERR_READ 13//读卡错误
        #define ERR_WRITE 14//写卡错误

        #define ERR_NONEDLL 21//没有动态库
        #define ERR_DRIVERORDLL 22//动态库或驱动程序异常
        #define ERR_DRIVERNULL 23//驱动程序错误或尚未安装
        #define ERR_TIMEOUT 24//操作超时，一般是动态库没有反映
        #define ERR_TXSIZE 25//发送字数不够
        #define ERR_TXCRC 26//发送的CRC错
        #define ERR_RXSIZE 27//接收的字数不够
        #define ERR_RXCRC 28//接收的CRC错
        }

end;

procedure TForm1.Button11Click(Sender: TObject);
//轻松读卡
{
技术支持：
网站：
}
var
    i:integer;
    x:LongWord ;
    status:byte;//存放返回值
    edc:byte;//校验码
    authmode:byte;//密码类型，用A密码或B密码
    myctrlword:byte;//控制字
	  mypicckey:array[0..5] of byte;//密码
    mypiccserial:array[0..3] of byte;//卡序列号
    mypiccdata:array[0..15] of byte;//卡数据缓冲
    strs:string;

begin
    for i:=0 to 16 do
    begin
        if i<4 then  mypiccserial[i]:=0;
        if i<6 then  mypicckey[i]:=0;
        mypiccdata[i]:=0;
    end;

    if RichEdit2.Lines[0]>'4294967295' then
    begin
       Application.MessageBox('卡号最大取值：4294967295', '提示', MB_OK+MB_ICONSTOP) ;
       exit;
    end;

    x:= StrToInt64(RichEdit2.Lines[0]) ;
    if x>4294967295 then
    begin
       Showmessage('卡号最大取值：4294967295') ;
       exit;
    end;

    edc:=0;
    if (checkbox4.State = cbchecked) then
    begin
        for i:=3 downto 0 do
        begin
           mypiccdata[i]:= x and 255;
           edc:=edc xor mypiccdata[i];
           x:=x shr 8;
        end;
    end
    else
    begin
        for i:=0 to 3 do
        begin
           mypiccdata[i]:= x and 255;
           edc:=edc xor mypiccdata[i];
           x:=x shr 8;
        end;
    end;
    mypiccdata[4]:= edc;

    myctrlword:=BLOCK0_EN;
    authmode:=0;
    status:=piccwriteserial(myctrlword,@mypiccserial,authmode,@mypicckey,@mypiccdata);
    case status of
          0:
          begin
              pcdbeep(38);
              strs:= 'UID卡号：'+RightStr('0000000000'+RichEdit2.Lines[0],10)+' 写卡成功！' ;
              ListBox1.Items.Add(strs);
              listbox1.ItemIndex:=listbox1.Count-1;
              Application.MessageBox(PAnsiChar(AnsiString(strs)) , '提示', MB_OK+MB_ICONINFORMATION);       ////MB_ICONQUESTION  MB_ICONEXCLAMATION  MB_ICONWARNING  MB_ICONINFORMATION  MB_ICONASTERISK  MB_ICONHAND  MB_ICONERROR  MB_ICONSTOP
              if checkbox1.State = cbchecked then
              begin
                  x:=StrToInt64(RichEdit2.Lines[0])+1;
                  if (checkbox2.State = cbchecked)  and (RightStr(inttostr(x),1)='4') then x:=x+1;
                  if (checkbox3.State = cbchecked)  and (RightStr(inttostr(x),1)='7') then x:=x+1;
                  RichEdit2.Text :=rightstr('0000000000'+inttostr(x),10);
              end;
          end;
          8: Application.MessageBox('请将卡放在感应区', '提示', MB_OK+MB_ICONSTOP);
          12:Application.MessageBox('卡密码认证失败！', '提示', MB_OK+MB_ICONSTOP);
        else
          begin
              Application.MessageBox(PAnsiChar(AnsiString('操作失败，错误代码：'+IntToStr(status))), '提示', MB_OK+MB_ICONSTOP);
          end;
   end;
end;

procedure TForm1.Timer1Timer(Sender: TObject);
var
    i:integer;
    x:LongWord ;
    status:byte;//存放返回值
    edc:byte;//校验码
    authmode:byte;//密码类型，用A密码或B密码
    myctrlword:byte;//控制字
	  mypicckey:array[0..5] of byte;//密码
    mypiccserial:array[0..3] of byte;//卡序列号
    mypiccdata:array[0..15] of byte;//卡数据缓冲
    strs:string;
begin
    if edit1.Font.Color=clCream  then
    begin
       edit1.Font.Color:=clRed ;
    end
    else
       edit1.Font.Color:=clCream;

    if RichEdit2.Lines[0]>'4294967295' then
    begin
        button1.caption:='开始连续发卡';
        button11.Enabled :=true;
        BUTTON4.Enabled :=true;
        timer1.Enabled :=false;
        Application.MessageBox('卡号最大取值：4294967295', '提示', MB_OK+MB_ICONSTOP) ;
        exit;
    end;

    status := piccrequest(@mypiccserial);
    case status of
         0:
         begin
              if (checkbox4.State = cbchecked) then
                  cardnumber:= mypiccserial[0]*256*256*256+mypiccserial[1]*256*256+mypiccserial[2]*256+mypiccserial[3]
              else
                  cardnumber:= mypiccserial[3]*256*256*256+mypiccserial[2]*256*256+mypiccserial[1]*256+mypiccserial[0];

              if (cardnumber<> writcardnum) and (cardnumber<>lastcardnum) then
              begin
                   lastcardnum:=cardnumber;
                   x:= StrToInt64(RichEdit2.Lines[0]) ;
                   edc:=0;
                   if (checkbox4.State = cbchecked) then
                   begin
                       for i:=3 downto 0 do
                       begin
                            mypiccdata[i]:= x and 255;
                            edc:=edc xor mypiccdata[i];
                            x:=x shr 8;
                       end;
                   end
                   else
                   begin
                       for i:=0 to 3 do
                       begin
                            mypiccdata[i]:= x and 255;
                            edc:=edc xor mypiccdata[i];
                            x:=x shr 8;
                       end;
                   end;
                   mypiccdata[4]:= edc;

                   myctrlword:=BLOCK0_EN;
                   authmode:=0;
                   status:=piccwriteserial(myctrlword,@mypiccserial,authmode,@mypicckey,@mypiccdata);
                   case status of
                        0:
                        begin
                             writcardnum:= StrToInt64(RichEdit2.Lines[0]);  //保留已写入的UID
                             strs:= 'UID卡号：'+RightStr('0000000000'+RichEdit2.Lines[0],10)+' 写卡成功！' ;
                             ListBox1.Items.Add(strs);
                             listbox1.ItemIndex:=listbox1.Count-1;
                             edit1.Text :=RichEdit2.Lines[0]+' 号卡写卡成功，请继续在发卡器上刷新的UID卡';
                             pcdbeep(38);
                             x:=StrToInt64(RichEdit2.Lines[0])+1;
                             if (checkbox2.State = cbchecked)  and (RightStr(inttostr(x),1)='4') then x:=x+1;
                             if (checkbox3.State = cbchecked)  and (RightStr(inttostr(x),1)='7') then x:=x+1;
                             RichEdit2.Text :=rightstr('0000000000'+inttostr(x),10);
                        end;

                        18:
                        begin
                            edit1.Text :='错误代码:18,这可能不是UID卡，请在发卡器上刷新的UID卡';
                        end;

                        else
                        begin
                            edit1.Text :='错误代码:'+inttostr(status)+',请在发卡器上刷新的UID卡';
                        end;
                   end;
              end;
              {else
              begin
                  edit1.Text :=inttostr(cardnumber)+'号为刚操作的卡,请在发卡器上刷新的UID卡';
              end;}
         end;

         8:
         begin
              edit1.Text :='请在发卡器上刷新的UID卡';
         end;

         9:
         begin
             edit1.Text :='错误代码9:多张卡在感应区,请在发卡器上刷新的UID卡';
         end;

         10:
         begin
             cardnumber:= mypiccserial[0]*256*256*256+mypiccserial[1]*256*256+mypiccserial[2]*256+mypiccserial[3];
             edit1.Text :='错误代码10:'+'请在发卡器上刷新的UID卡';
         end;

         22:
         begin
             edit1.Text :='错误代码22:动态库或驱动程序异常!';
         end;

         23:
         begin
             edit1.Text :='错误代码23:动态库或驱动程序异常!';
         end;

         24:
         begin
            edit1.Text :='错误代码24:动态库或驱动程序异常!';
         end;
         28:
         begin
             edit1.Text :='错误代码28:CRC校验错!';
         end;

         else
         begin
            edit1.Text :='错误代码:'+inttostr(status)+',请继续在发卡器上刷新的UID卡';
         end;
    end;

end;

procedure TForm1.Button2Click(Sender: TObject);
begin
listbox1.Clear;
end;

procedure TForm1.RichEdit2KeyPress(Sender: TObject; var Key: Char);
begin
if Not (key in ['0'..'9']) then
key := #0;

end;

end.
