//---------------------------------------------------------------------------

#include <vcl.h>
#pragma hdrstop

#include "Unit1.h"

//控制字定义
#define BLOCK0_EN  0x01
#define BLOCK1_EN  0x02
#define BLOCK2_EN  0x04
#define NEEDSERIAL 0x08
#define EXTERNKEY  0x10
#define NEEDHALT   0x20


//---------------------------------------------------------------------------
#pragma package(smart_init)
#pragma resource "*.dfm"
TForm1 *Form1;

bool istimer1continue;
__int64 readcardtimes;

//---------------------------------------------------------------------------
__fastcall TForm1::TForm1(TComponent* Owner)
        : TForm(Owner)
{
}
//---------------------------------------------------------------------------
HINSTANCE hDll;

void __fastcall TForm1::Button1Click(TObject *Sender)
//轻松读卡
{
/*
技术支持：
网站：
*/

        unsigned char status;//存放返回值
        unsigned char myareano;//区号
        unsigned char authmode;//密码类型，用A密码或B密码
        unsigned char myctrlword;//控制字
	unsigned char mypicckey[6];//密码
        unsigned char mypiccserial[4];//卡序列号
        unsigned char mypiccdata[48]; //卡数据缓冲

        unsigned char (__stdcall *piccreadex)(unsigned char ctrlword,unsigned char *serial,unsigned char area,unsigned char keyA1B0,unsigned char *picckey,unsigned char *piccdata0_2);
        //判断动态库是否存在
        AnsiString FileName=ExtractFilePath(Application->ExeName);
        if(FileName.SubString(FileName.Length(),1) != "\\")
        {
             FileName += "\\";
        }
        FileName += "OUR_MIFARE.dll";
        if(!FileExists(FileName))
        {
                ShowMessage("无法在应用程序的文件夹找到OUR_MIFARE.dll");
                return;
        }
        //提取函数
        
        hDll=LoadLibrary(FileName.c_str());
        piccreadex = (unsigned char (__stdcall *)(unsigned char,unsigned char *,unsigned char,unsigned char,unsigned char *,unsigned char *))GetProcAddress(hDll,"piccreadex");

        //控制字指定,控制字的含义请查看本公司网站提供的动态库说明
        myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY;

        //指定区号
        myareano = 8;//指定为第8区
        //批定密码模式
        authmode = 1;//大于0表示用A密码认证，推荐用A密码认证

        //指定密码
        mypicckey[0] = 0xff;
        mypicckey[1] = 0xff;
        mypicckey[2] = 0xff;
        mypicckey[3] = 0xff;
        mypicckey[4] = 0xff;
        mypicckey[5] = 0xff;

        status = piccreadex(myctrlword,mypiccserial,myareano,authmode,mypicckey,mypiccdata);

        //FreeLibrary(hDll);无需释放，因为加载DLL动态库时，在exe运行后加载只是第1次才产生动态库镜像，再次加载只是引用第一次加载的动态库镜像，不会增加内存


        
        //在下面设定断点，然后查看mypiccserial、mypiccdata，
        //调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
        //开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
        //处理返回函数
        switch(status)
        {
                case 0:
                        ShowMessage("操作成功");
                        break;
                //......
                case 8:
                        ShowMessage("请将卡放在感应区");
                        break;



        }


        //返回解释
        /*
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



        */




}
//---------------------------------------------------------------------------

void __fastcall TForm1::Button4Click(TObject *Sender)
//让设备发出声音
{
/*
技术支持：
网站：
*/
        unsigned char (__stdcall *pcdbeep)(unsigned long xms);
        //判断动态库是否存在
        AnsiString FileName=ExtractFilePath(Application->ExeName);
        if(FileName.SubString(FileName.Length(),1) != "\\")
        {
             FileName += "\\";
        }
        FileName += "OUR_MIFARE.dll";
        if(!FileExists(FileName))
        {
                ShowMessage("无法在应用程序的文件夹找到OUR_MIFARE.dll");
                return;
        }

        //提取函数
        
        hDll=LoadLibrary(FileName.c_str());
        pcdbeep = (unsigned char (__stdcall *)(unsigned long))GetProcAddress(hDll,"pcdbeep");
        pcdbeep(50);
        //FreeLibrary(hDll);无需释放，因为加载DLL动态库时，在exe运行后加载只是第1次才产生动态库镜像，再次加载只是引用第一次加载的动态库镜像，不会增加内存


}
//---------------------------------------------------------------------------

void __fastcall TForm1::Button2Click(TObject *Sender)
//轻松写卡
{
/*
技术支持：
网站：
*/
        int i;
        unsigned char status;//存放返回值
        unsigned char myareano;//区号
        unsigned char authmode;//密码类型，用A密码或B密码
        unsigned char myctrlword;//控制字
	unsigned char mypicckey[6];//密码
        unsigned char mypiccserial[4];//卡序列号
        unsigned char mypiccdata[48]; //卡数据缓冲

        unsigned char (__stdcall *piccwriteex)(unsigned char ctrlword,unsigned char *serial,unsigned char area,unsigned char keyA1B0,unsigned char *picckey,unsigned char *piccdata0_2);
        //判断动态库是否存在
        AnsiString FileName=ExtractFilePath(Application->ExeName);
        if(FileName.SubString(FileName.Length(),1) != "\\")
        {
             FileName += "\\";
        }
        FileName += "OUR_MIFARE.dll";
        if(!FileExists(FileName))
        {
                ShowMessage("无法在应用程序的文件夹找到OUR_MIFARE.dll");
                return;
        }
        //提取函数
        
        hDll=LoadLibrary(FileName.c_str());
        piccwriteex = (unsigned char (__stdcall *)(unsigned char,unsigned char *,unsigned char,unsigned char,unsigned char *,unsigned char *))GetProcAddress(hDll,"piccwriteex");
        //控制字指定,控制字的含义请查看本公司网站提供的动态库说明
        myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY;

        //指定区号
        myareano = 8;//指定为第8区
        //批定密码模式
        authmode = 1;//大于0表示用A密码认证，推荐用A密码认证

        //指定密码
        mypicckey[0] = 0xff;
        mypicckey[1] = 0xff;
        mypicckey[2] = 0xff;
        mypicckey[3] = 0xff;
        mypicckey[4] = 0xff;
        mypicckey[5] = 0xff;

        //指定卡数据
        for(i = 0;i<48;i++)
        {
                mypiccdata[i] = i;
        }
        //写卡
        status = piccwriteex(myctrlword,mypiccserial,myareano,authmode,mypicckey,mypiccdata);

        //FreeLibrary(hDll);无需释放，因为加载DLL动态库时，在exe运行后加载只是第1次才产生动态库镜像，再次加载只是引用第一次加载的动态库镜像，不会增加内存
        //在下面设定断点，然后查看mypiccserial、mypiccdata，
        //调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
        //开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
        //处理返回函数
        switch(status)
        {
                case 0:
                        ShowMessage("操作成功");
                        break;
                //......
                case 8:
                        ShowMessage("请将卡放在感应区");
                        break;


        }


        //返回解释
        /*
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
        */

}
//---------------------------------------------------------------------------

void __fastcall TForm1::Button3Click(TObject *Sender)
//修改单区密码,只改A或B密码，不能改密码权限访问字，且一次只能改A或B密码中的一个。
{

/*
技术支持：
网站：
*/

        unsigned char status;//存放返回值
        unsigned char myareano;//区号
        unsigned char authmode;//密码类型，用A密码或B密码
        unsigned char myctrlword;//控制字

	unsigned char mypiccnewkey[6];//新密码
        unsigned char mypiccserial[4];//卡序列号
        unsigned char mypiccoldkey[6];//旧密码

        unsigned char (__stdcall *piccchangesinglekey)(unsigned char ctrlword,unsigned char *serial,unsigned char area,unsigned char keyA1B0,unsigned char *piccoldkey,unsigned char *piccnewkey);
        //判断动态库是否存在
        AnsiString FileName=ExtractFilePath(Application->ExeName);
        if(FileName.SubString(FileName.Length(),1) != "\\")
        {
             FileName += "\\";
        }
        FileName += "OUR_MIFARE.dll";
        if(!FileExists(FileName))
        {
                ShowMessage("无法在应用程序的文件夹找到OUR_MIFARE.dll");
                return;
        }

        //提取函数
        
        hDll=LoadLibrary(FileName.c_str());
        piccchangesinglekey = (unsigned char (__stdcall *)(unsigned char ,unsigned char *,unsigned char ,unsigned char ,unsigned char *,unsigned char *))GetProcAddress(hDll,"piccchangesinglekey");

        //控制字指定,控制字的含义请查看本公司网站提供的动态库说明
        myctrlword = 0;

        //指定区号
        myareano = 8;//指定为第8区
        //批定密码模式
        authmode = 1;//大于0表示用A密码认证，推荐用A密码认证

        //指定旧密码
        mypiccoldkey[0] = 0xff;
        mypiccoldkey[1] = 0xff;
        mypiccoldkey[2] = 0xff;
        mypiccoldkey[3] = 0xff;
        mypiccoldkey[4] = 0xff;
        mypiccoldkey[5] = 0xff;

        //指定新密码,注意：指定新密码时一定要记住，否则有可能找不回密码，导致该卡报废。
        mypiccnewkey[0] = 0xff;
        mypiccnewkey[1] = 0xff;
        mypiccnewkey[2] = 0xff;
        mypiccnewkey[3] = 0xff;
        mypiccnewkey[4] = 0xff;
        mypiccnewkey[5] = 0xff;

        status = piccchangesinglekey(myctrlword,mypiccserial,myareano,authmode,mypiccoldkey,mypiccnewkey);

        //FreeLibrary(hDll);无需释放，因为加载DLL动态库时，在exe运行后加载只是第1次才产生动态库镜像，再次加载只是引用第一次加载的动态库镜像，不会增加内存
        //返回值处理
        switch(status)
        {
                case 0:
                        ShowMessage("操作成功");
                        break;
                //......
                case 8:
                        ShowMessage("请将卡放在感应区");
                        break;

        }
}
//---------------------------------------------------------------------------

void __fastcall TForm1::Button5Click(TObject *Sender)
//读取设备编号，可做为软件加密狗用,也可以根据此编号在公司网站上查询保修期限
{
/*
技术支持：
网站：
*/

        unsigned char devno[4];//设备编号
        unsigned char (__stdcall *pcdgetdevicenumber)(unsigned char *devicenumber);
        //判断动态库是否存在
        AnsiString FileName=ExtractFilePath(Application->ExeName);
        if(FileName.SubString(FileName.Length(),1) != "\\")
        {
             FileName += "\\";
        }
        FileName += "OUR_MIFARE.dll";
        if(!FileExists(FileName))
        {
                ShowMessage("无法在应用程序的文件夹找到OUR_MIFARE.dll");
                return;
        }

        //提取函数
        
        hDll=LoadLibrary(FileName.c_str());
        pcdgetdevicenumber = (unsigned char (__stdcall *)(unsigned char *))GetProcAddress(hDll,"pcdgetdevicenumber");


        if(!pcdgetdevicenumber(devno))
        {
                //FreeLibrary(hDll);无需释放，因为加载DLL动态库时，在exe运行后加载只是第1次才产生动态库镜像，再次加载只是引用第一次加载的动态库镜像，不会增加内存
                ShowMessage(IntToStr(devno[0]) + "-" + IntToStr(devno[1]) + "-" + IntToStr(devno[2]) + "-" + IntToStr(devno[3]));
        }
        else
        {
                //FreeLibrary(hDll);无需释放，因为加载DLL动态库时，在exe运行后加载只是第1次才产生动态库镜像，再次加载只是引用第一次加载的动态库镜像，不会增加内存
        }

}
//---------------------------------------------------------------------------


void __fastcall TForm1::Button6Click(TObject *Sender)
{//修改单区密码,可同时改A、B密码、密码权限访问字


        unsigned char status;//存放返回值
        unsigned char myareano;//区号
        unsigned char authmode;//密码类型，用A密码或B密码
        unsigned char myctrlword;//控制字
	unsigned char mypiccoldkey[6];//旧密码
        unsigned char mypiccserial[4];//卡序列号
        unsigned char mypiccdata[17]; //其中新A密码6个字节；密码权限访问字4个字节；新B密码6个字节；指定更改项目的标志为1个字节，
                                      //这个字节为3是表示同时更改A、B、 密码权限访问字，为2表示密码权限访问字不更改，只改A、B密码，为0表示只改A密码

        unsigned char (__stdcall *piccchangesinglekeyex)(unsigned char ctrlword,unsigned char *serial,unsigned char area,unsigned char keyA1B0,unsigned char *piccoldkey,unsigned char *piccnewkey);

        AnsiString FileName=ExtractFilePath(Application->ExeName);
        if(FileName.SubString(FileName.Length(),1) != "\\")
        {
             FileName += "\\";
        }
        FileName += "OUR_MIFARE.dll";
        if(!FileExists(FileName))
        {
                ShowMessage("无法在应用程序的文件夹找到OUR_MIFARE.dll");
                return;
        }

        
        hDll=LoadLibrary(FileName.c_str());
        piccchangesinglekeyex = (unsigned char (__stdcall *)(unsigned char ,unsigned char *,unsigned char ,unsigned char ,unsigned char *,unsigned char *))GetProcAddress(hDll,"piccchangesinglekeyex");

        myctrlword =EXTERNKEY;//用函数中输入的密码认证
        myareano = 8;//改第8区的密码
        authmode = 0xaa;//用A密码认证

        //旧密码
        mypiccoldkey[0] = 0xff;
        mypiccoldkey[1] = 0xff;
        mypiccoldkey[2] = 0xff;
        mypiccoldkey[3] = 0xff;
        mypiccoldkey[4] = 0xff;
        mypiccoldkey[5] = 0xff;

        //新A密码
        mypiccdata[0] = 0xff;
        mypiccdata[1] = 0xff;
        mypiccdata[2] = 0xff;
        mypiccdata[3] = 0xff;
        mypiccdata[4] = 0xff;
        mypiccdata[5] = 0xff;

        //密码权限访问字,出厂卡为 FF 07 80 69
        mypiccdata[6] = 0xff;
        mypiccdata[7] = 0x07;
        mypiccdata[8] = 0x80;
        mypiccdata[9] = 0x69;

        //新B密码
        mypiccdata[10] = 0xff;
        mypiccdata[11] = 0xff;
        mypiccdata[12] = 0xff;
        mypiccdata[13] = 0xff;
        mypiccdata[14] = 0xff;
        mypiccdata[15] = 0xff;

        //指定更改项目的标志
        mypiccdata[16] = 0x2;//只改A密码和B密码，暂时不改密码权限访问字

        status = piccchangesinglekeyex(myctrlword,mypiccserial,myareano,authmode,mypiccoldkey,mypiccdata);
        //FreeLibrary(hDll);无需释放，因为加载DLL动态库时，在exe运行后加载只是第1次才产生动态库镜像，再次加载只是引用第一次加载的动态库镜像，不会增加内存
        switch(status)
        {
                case 0:
                        ShowMessage("操作成功");
                        break;
                //......
                case 8:
                        ShowMessage("请将卡放在感应区");
                        break;

                case 30:
                        ShowMessage("密码权限访问字错误");
                        break;
        }

}
//---------------------------------------------------------------------------

void __fastcall TForm1::Button7Click(TObject *Sender)
{
        /*
        unsigned char (__stdcall *lcddispfull)(LPSTR lcdstr);


        //判断动态库是否存在
        AnsiString FileName=ExtractFilePath(Application->ExeName);
        if(FileName.SubString(FileName.Length(),1) != "\\")
        {
             FileName += "\\";
        }
        FileName += "OUR_MIFARE.dll";
        if(!FileExists(FileName))
        {
                ShowMessage("无法在应用程序的文件夹找到OUR_MIFARE.dll");
                return;
        }

        //提取函数

        hDll=LoadLibrary(FileName.c_str());

        lcddispfull = (unsigned char (__stdcall *)(LPSTR ))GetProcAddress(hDll,"lcddispfull");


        //lcddispfull(Edit1->Text.c_str());
        //FreeLibrary(hDll);无需释放，因为加载DLL动态库时，在exe运行后加载只是第1次才产生动态库镜像，再次加载只是引用第一次加载的动态库镜像，不会增加内存
        */
}
//---------------------------------------------------------------------------


void __fastcall TForm1::Button8Click(TObject *Sender)
{
        Timer1->Enabled = True;
        istimer1continue = true;
        readcardtimes = 0;

        Button8->Enabled = false;
        Button1->Enabled = false;
        Button2->Enabled = false;
        Button3->Enabled = false;
        Button4->Enabled = false;
        Button5->Enabled = false;
        Button6->Enabled = false;
        Button7->Enabled = false;

        Button9->Enabled = true;
}
//---------------------------------------------------------------------------

void __fastcall TForm1::Timer1Timer(TObject *Sender)
{//开始循环轻松读卡
        Timer1->Enabled = false;

        //轻松读卡

        unsigned char status;//存放返回值
        unsigned char myareano;//区号
        unsigned char authmode;//密码类型，用A密码或B密码
        unsigned char myctrlword;//控制字
	unsigned char mypicckey[6];//密码
        unsigned char mypiccserial[4];//卡序列号
        unsigned char mypiccdata[48]; //卡数据缓冲

        unsigned char (__stdcall *piccreadex)(unsigned char ctrlword,unsigned char *serial,unsigned char area,unsigned char keyA1B0,unsigned char *picckey,unsigned char *piccdata0_2);
        //判断动态库是否存在
        AnsiString FileName=ExtractFilePath(Application->ExeName);
        if(FileName.SubString(FileName.Length(),1) != "\\")
        {
             FileName += "\\";
        }
        FileName += "OUR_MIFARE.dll";
        if(!FileExists(FileName))
        {
                Edit2->Text = "无法在应用程序的文件夹找到OUR_MIFARE.dll";

                Button9->Click();
                return;
        }
        //提取函数

        hDll=LoadLibrary(FileName.c_str());
        piccreadex = (unsigned char (__stdcall *)(unsigned char,unsigned char *,unsigned char,unsigned char,unsigned char *,unsigned char *))GetProcAddress(hDll,"piccreadex");

        //控制字指定,控制字的含义请查看本公司网站提供的动态库说明
        myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY;

        //指定区号
        myareano = 8;//指定为第8区
        //批定密码模式
        authmode = 1;//大于0表示用A密码认证，推荐用A密码认证

        //指定密码
        mypicckey[0] = 0xff;
        mypicckey[1] = 0xff;
        mypicckey[2] = 0xff;
        mypicckey[3] = 0xff;
        mypicckey[4] = 0xff;
        mypicckey[5] = 0xff;

        status = piccreadex(myctrlword,mypiccserial,myareano,authmode,mypicckey,mypiccdata);

        //FreeLibrary(hDll);无需释放，因为加载DLL动态库时，在exe运行后加载只是第1次才产生动态库镜像，再次加载只是引用第一次加载的动态库镜像，不会增加内存

        //在下面设定断点，然后查看mypiccserial、mypiccdata，
        //调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
        //开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
        //处理返回函数
        switch(status)
        {
            case 0:
                Edit2->Text = "操作成功";
                break;
            //......
            case 8:
                Edit2->Text = "请将卡放在感应区";
                break;

            case 23:
                Edit2->Text = "请先插入有驱的IC读写器";
                break;

        }

        if(status == 23)
        {
               Button9->Click();

               return;
        }

        readcardtimes++;

        Label2->Caption = "次数：" + IntToStr(readcardtimes);

        if(istimer1continue)
        {
                Timer1->Enabled = True;
        }
}
//---------------------------------------------------------------------------

void __fastcall TForm1::Button9Click(TObject *Sender)
{//关闭环轻松读卡
        Button9->Enabled = false;

        Button1->Enabled = true;
        Button2->Enabled = true;
        Button3->Enabled = true;
        Button4->Enabled = true;
        Button5->Enabled = true;
        Button6->Enabled = true;
        Button7->Enabled = true;

        Button8->Enabled = true;

        istimer1continue = false;
}
//---------------------------------------------------------------------------

void __fastcall TForm1::FormCloseQuery(TObject *Sender, bool &CanClose)
{
        FreeLibrary(hDll);
}
//---------------------------------------------------------------------------

