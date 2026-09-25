program ReadCard;

uses
  Forms,
  Windows,
  SysUtils,
  Messages,
  Dialogs,
  Unit1 in 'Unit1.pas' {Form1},
  declaredll in 'declaredll.pas';

{$R *.res}
var
myMutex:HWND;

begin
  myMutex:=CreateMutex(nil,false,'RSRead');
  if WaitForSingleObject(myMutex,0)<>wait_TimeOut then
  begin
      Application.Initialize;
      Application.Title := '读卡器程序正在运行...';
      Application.CreateForm(TForm1, Form1);
  Application.Run;
  end
  else
  begin
      // ShowMessage('读卡器服务程序已经运行！');
       Application.MessageBox('读卡器服务程序已经运行!', '警告',MB_OK +MB_ICONINFORMATION)
  end;
end.
