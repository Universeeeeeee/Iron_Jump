unit Unit1;

interface

uses
  Windows, Messages, SysUtils, Variants, Classes, Graphics, Controls, Forms,  Dialogs, RzTray, Menus, ExtCtrls, ImgList,
  StdCtrls,declaredll;


type
  TForm1 = class(TForm)
    tmr1: TTimer;
    pm1: TPopupMenu;
    N1: TMenuItem;
    N2: TMenuItem;
    S1: TMenuItem;
    N3: TMenuItem;
    O1: TMenuItem;
    N4: TMenuItem;
    X1: TMenuItem;
    il1: TImageList;
    rztrycn1: TRzTrayIcon;
    btn1: TButton;
    CheckBox1: TCheckBox;
    procedure N1Click(Sender: TObject);
    procedure FormCloseQuery(Sender: TObject; var CanClose: Boolean);
    procedure X1Click(Sender: TObject);
    procedure btn1Click(Sender: TObject);
    procedure tmr1Timer(Sender: TObject);
    procedure FormCreate(Sender: TObject);
    procedure S1Click(Sender: TObject);
    procedure O1Click(Sender: TObject);

  private
    { Private declarations }
    isenclose:Boolean ;
  public
    { Public declarations }
  end;

var
  Form1: TForm1;
  Reading:Boolean ;

implementation

{$R *.dfm}
procedure SendKeys(sSend:string);
var
    i:integer;
    focushld,windowhld:hwnd;
    threadld:dword;
    ch: byte;
begin
  windowhld:=GetForegroundWindow;           //获得前台应用程序的活动窗口的句柄

  threadld:=GetWindowThreadProcessId(Windowhld,nil);        //获取与指定窗口关联在一起的一个进程和线程标识符

  AttachThreadInput(GetCurrentThreadId,threadld,true);
    //通常，系统内的每个线程都有自己的输入队列。          //
    //AttachThreadInput允许线程和进程共享输入队列。        //
    //连接了线程后，输入焦点、窗口激活、鼠标捕获、键盘状态 //
    //以及输入队列状态都会进入共享状态          //
  Focushld:=getfocus;
    //获得拥有输入焦点的窗口的句柄
  AttachThreadInput(GetCurrentThreadId,threadld,false );
  if focushld = 0 then Exit;
    //如果没有输入焦点则退出发送过程
  i := 1;
  while i <= Length(sSend) do
    //该过程发送指定字符串（中英文皆可以）
  begin  
    ch := byte(sSend[ i ]);
    if Windows.IsDBCSLeadByte(ch) then
    begin
      Inc(i);
      SendMessage(focushld, WM_IME_CHAR, MakeWord(byte(sSend[ i ]), ch), 0);
      Sleep(25);
    end
    else
      SendMessage(focushld, WM_IME_CHAR, word(ch), 0);
      Inc(i);
      Sleep(25);
  end;
  postmessage(focushld,WM_keydown,13,0);  
    //发送一个虚拟Enter按键
end;


procedure TForm1.N1Click(Sender: TObject);
begin
      ShowWindow(Application.Handle, SW_RESTORE);
      Form1.Show();
      Form1.WindowState :=  wsNormal;
      //SetWindowLong(Application.Handle, GWL_EXSTYLE, WS_EX_TOOLWINDOW);
end;

procedure TForm1.FormCloseQuery(Sender: TObject; var CanClose: Boolean);
begin
  if(not isenclose) then
  begin
    Form1.Hide();
    ShowWindow(Application.Handle,SW_HIDE);
    CanClose := False;
    //隐身
  end;
end;

procedure TForm1.X1Click(Sender: TObject);
begin
  if(Application.MessageBox('是否真的要退出读卡器程序?', '警告', MB_YESNO +MB_ICONINFORMATION) = IDYES) then
  begin
    isenclose := True;
    Close();
  end;
end;

procedure TForm1.btn1Click(Sender: TObject);
begin
       pcdbeep(50);
end;

procedure TForm1.tmr1Timer(Sender: TObject);
var
    status:byte;//存放返回值
    myareano:byte;//区号
    authmode:byte;//密码类型，用A密码或B密码
    myctrlword:byte;//控制字
	  mypicckey:array[0..5] of byte;//密码
    mypiccserial:array[0..3] of byte;//卡序列号
    mypiccdata:array[0..47] of byte;//卡数据缓冲
    strls:string;
    i:Integer ;
begin
    try

        if Reading= True then
        begin
            //控制字指定,控制字的含义请查看本公司网站提供的动态库说明
            myctrlword := BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY;

            //指定区号
            myareano := 1;//指定为第8区
            //批定密码模式
            authmode := 1;//大于0表示用A密码认证，推荐用A密码认证

            //指定密码
            mypicckey[0] := $ff;
            mypicckey[1] := $ff;
            mypicckey[2] := $ff;
            mypicckey[3] := $ff;
            mypicckey[4] := $ff;
            mypicckey[5] := $ff;

            status := piccreadex(myctrlword,@mypiccserial,myareano,authmode,@mypicckey,@mypiccdata);
            if status= 0 then
            begin
                picchalt;

                if CheckBox1.Checked =True then
                begin
                   pcdbeep(12);
                end;

                strls:='';
                for i := 0 to 15 do
                begin
                     strls := strls+inttohex(mypiccdata[i],2);
                end;
                SendKeys(strls);
            end;
        end;
      finally

      end;
end;

procedure TForm1.FormCreate(Sender: TObject);
begin
     Reading:=True ;
end;

procedure TForm1.S1Click(Sender: TObject);
begin
    O1.Enabled :=True ;
    S1.Enabled :=False  ;
    Reading:= True;
end;

procedure TForm1.O1Click(Sender: TObject);
begin
    O1.Enabled :=False ;
    S1.Enabled :=True ;
    Reading:=False;
end;

end.
