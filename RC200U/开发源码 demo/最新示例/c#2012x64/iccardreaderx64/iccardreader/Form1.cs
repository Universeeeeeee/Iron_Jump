using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Data;
using System.Drawing;
using System.Linq;
//using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

using System.Runtime.InteropServices;  //调用动态库一定要加入这个引用
using System.Text;//一定要加入这个

namespace WindowsFormsApplication1
{
    public partial class Form1 : Form
    {
        //常量定义
        public const byte BLOCK0_EN = 0x01;//操作第0块
        public const byte BLOCK1_EN = 0x02;//操作第1块
        public const byte BLOCK2_EN = 0x04;//操作第2块
        public const byte NEEDSERIAL = 0x08;//仅对指定序列号的卡操作
        public const byte EXTERNKEY = 0x10;
        public const byte NEEDHALT = 0x20;//读卡或写卡后顺便休眠该卡，休眠后，卡必须拿离开感应区，再放回感应区，才能进行第二次操作。

        //------------------------------------------------------------------------------------------------------------------------------------------------------
        //外部函数声明：让设备发出声响
        [DllImport("OUR_MIFARE.dll", EntryPoint = "pcdbeep", CallingConvention = CallingConvention.StdCall)]
        static extern byte pcdbeep(UInt32 xms);//xms单位为毫秒 


        //------------------------------------------------------------------------------------------------------------------------------------------------------    
        //只读卡号
        [DllImport("OUR_MIFARE.dll", EntryPoint = "piccrequest", CallingConvention = CallingConvention.StdCall)]
        public static extern byte piccrequest(byte[] serial);//devicenumber用于返回编号 

        //------------------------------------------------------------------------------------------------------------------------------------------------------    
        //读取设备编号，可做为软件加密狗用,也可以根据此编号在公司网站上查询保修期限
        [DllImport("OUR_MIFARE.dll", EntryPoint = "pcdgetdevicenumber", CallingConvention = CallingConvention.StdCall)]
        static extern byte pcdgetdevicenumber(byte[] devicenumber);//devicenumber用于返回编号 


        //------------------------------------------------------------------------------------------------------------------------------------------------------
        //轻松读卡
        [DllImport("OUR_MIFARE.dll", EntryPoint = "piccreadex", CallingConvention = CallingConvention.StdCall)]
        static extern byte piccreadex(byte ctrlword, byte[] serial, byte area, byte keyA1B0, byte[] picckey, byte[] piccdata0_2);
        //参数：说明
        //ctrlword：控制字
        //serial：卡序列号数组，用于指定或返回卡序列号
        //area：指定读卡区号
        //keyA1B0：指定用A或B密码认证,一般是用A密码，只有特殊用途下才用B密码，在这不做详细解释。
        //picckey：指定卡密码，6个字节，卡出厂时的初始密码为6个0xff
        //piccdata0_2：用于返回卡该区第0块到第2块的数据，共48个字节.


        //------------------------------------------------------------------------------------------------------------------------------------------------------
        //轻松写卡
        [DllImport("OUR_MIFARE.dll", EntryPoint = "piccwriteex", CallingConvention = CallingConvention.StdCall)]
        static extern byte piccwriteex(byte ctrlword, byte[] serial, byte area, byte keyA1B0, byte[] picckey, byte[] piccdata0_2);
        //参数：说明
        //ctrlword：控制字
        //serial：卡序列号数组，用于指定或返回卡序列号
        //area：指定读卡区号
        //keyA1B0：指定用A或B密码认证,一般是用A密码，只有特殊用途下才用B密码，在这不做详细解释。
        //picckey：指定卡密码，6个字节，卡出厂时的初始密码为6个0xff
        //piccdata0_2：用于返回卡该区第0块到第2块的数据，共48个字节.


        //------------------------------------------------------------------------------------------------------------------------------------------------------
        //修改卡单区的密码
        [DllImport("OUR_MIFARE.dll", EntryPoint = "piccchangesinglekey", CallingConvention = CallingConvention.StdCall)]
        static extern byte piccchangesinglekey(byte ctrlword, byte[] serial, byte area, byte keyA1B0, byte[] piccoldkey, byte[] piccnewkey);
        //参数：说明
        //ctrlword：控制字
        //serial：卡序列号数组，用于指定或返回卡序列号
        //area：指定读卡区号
        //keyA1B0：指定用A或B密码认证,一般是用A密码，只有特殊用途下才用B密码，在这不做详细解释。
        //piccoldkey：//旧密码
        //piccnewkey：//新密码.

        //------------------------------------------------------------------------------------------------------------------------------------------------------
        //修改卡A/B密码及控制字
        [DllImport("OUR_MIFARE.dll", EntryPoint = "piccchangesinglekeyex", CallingConvention = CallingConvention.StdCall)]
        static extern byte piccchangesinglekeyex(byte ctrlword, byte[] serial, byte area, byte keyA1B0, byte[] piccoldkey, byte[] piccnewkey);
        //参数：说明
        //ctrlword：控制字
        //serial：卡序列号数组，用于指定或返回卡序列号
        //area：指定读卡区号
        //keyA1B0：指定用A或B密码认证,一般是用A密码，只有特殊用途下才用B密码，在这不做详细解释。
        //piccoldkey：//旧密码
        //piccnewkey：//新密码.

        //------------------------------------------------------------------------------------------------------------------------------------------------------
        //发送显示内容到读卡器
        [DllImport("OUR_MIFARE.dll", EntryPoint = "lcddispfull", CallingConvention = CallingConvention.StdCall)]
        static extern byte lcddispfull(string lcdstr);
        //参数：说明
        //lcdstr：显示内容


        //------------------------------------------------------------------------------------------------------------------------------------------------------    
        //写设备存储区1
        [DllImport("OUR_MIFARE.dll", EntryPoint = "pcdsetcustomizedata1", CallingConvention = CallingConvention.StdCall)]
        public static extern byte pcdsetcustomizedata1(byte[] readerdata);//devicenumber用于传递写数据 

        //------------------------------------------------------------------------------------------------------------------------------------------------------    
        //读设备存储区1
        [DllImport("OUR_MIFARE.dll", EntryPoint = "pcdgetcustomizedata1", CallingConvention = CallingConvention.StdCall)]
        public static extern byte pcdgetcustomizedata1(byte[] readerdata);//devicenumber用于传递写数据 

        //------------------------------------------------------------------------------------------------------------------------------------------------------    
        //写设备存储区2
        [DllImport("OUR_MIFARE.dll", EntryPoint = "pcdsetcustomizedata2", CallingConvention = CallingConvention.StdCall)]
        public static extern byte pcdsetcustomizedata2(byte[] readerdata);//devicenumber用于传递写数据 

        //------------------------------------------------------------------------------------------------------------------------------------------------------    
        //读设备存储区2
        [DllImport("OUR_MIFARE.dll", EntryPoint = "pcdgetcustomizedata2", CallingConvention = CallingConvention.StdCall)]
        public static extern byte pcdgetcustomizedata2(byte[] readerdata, byte[] devno);//devicenumber用于传递写数据 


        public Form1()
        {
            InitializeComponent();
        }

        private void button1_Click(object sender, EventArgs e)//轻松读卡
        {
            byte status;//存放返回值
            byte myareano;//区号
            byte authmode;//密码类型，用A密码或B密码
            byte myctrlword;//控制字
            byte[] mypicckey = new byte[6];//密码
            byte[] mypiccserial = new byte[4];//卡序列号
            byte[] mypiccdata = new byte[48]; //卡数据缓冲
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

            status = piccreadex(myctrlword, mypiccserial, myareano, authmode, mypicckey, mypiccdata);
            //在下面设定断点，然后查看mypiccserial、mypiccdata，
            //调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
            //开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
            //处理返回函数
            switch (status)
            {
                case 0:
                    pcdbeep(20);
                    string readinf = "";
                    for (int i = 0; i < 48;i++ )
                    {
                        readinf = readinf + mypiccdata[i].ToString("X2");
                    }
                    textBox7.Text = readinf;
                    MessageBox.Show("操作成功,数据已显示在右框栏中！","示例程序");
                    break;
                case 8:
                    MessageBox.Show("未寻到卡，请将卡放在感应区！", "示例提示");
                    break;
                case 9:
                    MessageBox.Show("读序列码错误！", "示例提示");
                    break;
                case 10:
                    MessageBox.Show("选卡错误！", "示例提示");
                    break;
                case 11:
                    MessageBox.Show("装载密码错误！", "示例提示");
                    break;
                case 12:
                    MessageBox.Show("卡密码认证错误！", "示例提示");
                    break;
                case 13:
                    MessageBox.Show("读卡错误！", "示例提示");
                    break;
                case 14:
                    MessageBox.Show("写卡错误！", "示例提示");
                    break;
                case 21:
                    MessageBox.Show("没有动态库！", "示例提示");
                    break;
                case 22:
                    MessageBox.Show("动态库或驱动程序异常！", "示例提示");
                    break;
                case 23:
                    MessageBox.Show("驱动程序错误或尚未安装！", "示例提示");
                    break;
                case 24:
                    MessageBox.Show("操作超时，一般是动态库没有反映！", "示例提示");
                    break;
                case 25:
                    MessageBox.Show("发送字数不够！", "示例提示");
                    break;
                case 26:
                    MessageBox.Show("发送的CRC错！", "示例提示");
                    break;
                case 27:
                    MessageBox.Show("接收的字数不够！", "示例提示");
                    break;
                case 28:
                    MessageBox.Show("接收的CRC错！", "示例提示");
                    break;
                default:
                    MessageBox.Show("返回码(对应的说明请看例子中的注释):" + status, "示例提示");
                    break;
            }


            //返回解释
            /*
            REQUEST 8//寻卡错误
            READSERIAL 9//读序列吗错误
            SELECTCARD 10//选卡错误
            LOADKEY 11//装载密码错误
            AUTHKEY 12//密码认证错误
            READ 13//读卡错误
            WRITE 14//写卡错误

            NONEDLL 21//没有动态库
            DRIVERORDLL 22//动态库或驱动程序异常
            DRIVERNULL 23//驱动程序错误或尚未安装
            TIMEOUT 24//操作超时，一般是动态库没有反映
            TXSIZE 25//发送字数不够
            TXCRC 26//发送的CRC错
            RXSIZE 27//接收的字数不够
            RXCRC 28//接收的CRC错



            */
        }

        private void button2_Click(object sender, EventArgs e)//轻松写卡
        {
            byte i;
            byte status;//存放返回值
            byte myareano;//区号
            byte authmode;//密码类型，用A密码或B密码
            byte myctrlword;//控制字
            byte[] mypicckey = new byte[6];//密码
            byte[] mypiccserial = new byte[4];//卡序列号
            byte[] mypiccdata = new byte[48]; //卡数据缓冲
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
            string writinf = textBox7.Text.Trim() + "0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000";
            for (i = 0; i < 48; i++)
            {
                mypiccdata[i] = Convert.ToByte(Convert.ToInt32(writinf.Substring(i * 2, 2), 16));
            }

            status = piccwriteex(myctrlword, mypiccserial, myareano, authmode, mypicckey, mypiccdata);
            //在下面设定断点，然后查看mypiccserial、mypiccdata，
            //调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
            //开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
            //处理返回函数
            switch (status)
            {
                case 0:
                    pcdbeep(50);
                    MessageBox.Show("操作成功,右栏数据已写入卡中！", "示例提示");
                    break;
                case 8:
                    MessageBox.Show("未寻到卡，请将卡放在感应区！", "示例提示");
                    break;
                case 9:
                    MessageBox.Show("读序列码错误！", "示例提示");
                    break;
                case 10:
                    MessageBox.Show("选卡错误！", "示例提示");
                    break;
                case 11:
                    MessageBox.Show("装载密码错误！", "示例提示");
                    break;
                case 12:
                    MessageBox.Show("卡密码认证错误！", "示例提示");
                    break;
                case 13:
                    MessageBox.Show("读卡错误！", "示例提示");
                    break;
                case 14:
                    MessageBox.Show("写卡错误！", "示例提示");
                    break;
                case 21:
                    MessageBox.Show("没有动态库！", "示例提示");
                    break;
                case 22:
                    MessageBox.Show("动态库或驱动程序异常！", "示例提示");
                    break;
                case 23:
                    MessageBox.Show("驱动程序错误或尚未安装！", "示例提示");
                    break;
                case 24:
                    MessageBox.Show("操作超时，一般是动态库没有反映！", "示例提示");
                    break;
                case 25:
                    MessageBox.Show("发送字数不够！", "示例提示");
                    break;
                case 26:
                    MessageBox.Show("发送的CRC错！", "示例提示");
                    break;
                case 27:
                    MessageBox.Show("接收的字数不够！", "示例提示");
                    break;
                case 28:
                    MessageBox.Show("接收的CRC错！", "示例提示");
                    break;
                default:
                    MessageBox.Show("返回码(对应的说明请看例子中的注释):" + status, "示例提示");
                    break;
            }


            //返回解释
            /*
            REQUEST 8//寻卡错误
            READSERIAL 9//读序列吗错误
            SELECTCARD 10//选卡错误
            LOADKEY 11//装载密码错误
            AUTHKEY 12//密码认证错误
            READ 13//读卡错误
            WRITE 14//写卡错误

            NONEDLL 21//没有动态库
            DRIVERORDLL 22//动态库或驱动程序异常
            DRIVERNULL 23//驱动程序错误或尚未安装
            TIMEOUT 24//操作超时，一般是动态库没有反映
            TXSIZE 25//发送字数不够
            TXCRC 26//发送的CRC错
            RXSIZE 27//接收的字数不够
            RXCRC 28//接收的CRC错



            */
        }

        private void button4_Click(object sender, EventArgs e)
        {
            pcdbeep(50);
        }

        private void button3_Click(object sender, EventArgs e)
        {
            byte status;//存放返回值
            byte myareano;//区号
            byte authmode;//密码类型，用A密码或B密码
            byte myctrlword;//控制字
            byte[] piccoldkey = new byte[6];//旧密码
            byte[] mypiccserial = new byte[4];//卡序列号
            byte[] piccnewkey = new byte[6]; //新密码.


            //控制字指定,控制字的含义请查看本公司网站提供的动态库说明
            myctrlword = 0;

            //指定区号
            myareano = 8;//指定为第8区
            //批定密码模式
            authmode = 1;//大于0表示用A密码认证，推荐用A密码认证

            //指定旧密码
            piccoldkey[0] = 0xff;
            piccoldkey[1] = 0xff;
            piccoldkey[2] = 0xff;
            piccoldkey[3] = 0xff;
            piccoldkey[4] = 0xff;
            piccoldkey[5] = 0xff;

            //指定新密码,注意：指定新密码时一定要记住，否则有可能找不回密码，导致该卡报废。
            piccnewkey[0] = 0xff;
            piccnewkey[1] = 0xff;
            piccnewkey[2] = 0xff;
            piccnewkey[3] = 0xff;
            piccnewkey[4] = 0xff;
            piccnewkey[5] = 0xff;

            status = piccchangesinglekey(myctrlword, mypiccserial, myareano, authmode, piccoldkey, piccnewkey);
            //在下面设定断点，然后查看mypiccserial、mypiccdata，
            //调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
            //开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
            //处理返回函数
            switch (status)
            {
                case 0:
                    MessageBox.Show("操作成功,密码已被修改!");
                    break;
                case 8:
                    MessageBox.Show("未寻到卡，请将卡放在感应区！", "示例提示");
                    break;
                case 9:
                    MessageBox.Show("读序列码错误！", "示例提示");
                    break;
                case 10:
                    MessageBox.Show("选卡错误！", "示例提示");
                    break;
                case 11:
                    MessageBox.Show("装载密码错误！", "示例提示");
                    break;
                case 12:
                    MessageBox.Show("卡密码认证错误！", "示例提示");
                    break;
                case 13:
                    MessageBox.Show("读卡错误！", "示例提示");
                    break;
                case 14:
                    MessageBox.Show("写卡错误！", "示例提示");
                    break;
                case 21:
                    MessageBox.Show("没有动态库！", "示例提示");
                    break;
                case 22:
                    MessageBox.Show("动态库或驱动程序异常！", "示例提示");
                    break;
                case 23:
                    MessageBox.Show("驱动程序错误或尚未安装！", "示例提示");
                    break;
                case 24:
                    MessageBox.Show("操作超时，一般是动态库没有反映！", "示例提示");
                    break;
                case 25:
                    MessageBox.Show("发送字数不够！", "示例提示");
                    break;
                case 26:
                    MessageBox.Show("发送的CRC错！", "示例提示");
                    break;
                case 27:
                    MessageBox.Show("接收的字数不够！", "示例提示");
                    break;
                case 28:
                    MessageBox.Show("接收的CRC错！", "示例提示");
                    break;
                default:
                    MessageBox.Show("返回码(对应的说明请看例子中的注释):" + status, "示例提示");
                    break;
            }


            //返回解释
            /*
            REQUEST 8//寻卡错误
            READSERIAL 9//读序列吗错误
            SELECTCARD 10//选卡错误
            LOADKEY 11//装载密码错误
            AUTHKEY 12//密码认证错误
            READ 13//读卡错误
            WRITE 14//写卡错误

            NONEDLL 21//没有动态库
            DRIVERORDLL 22//动态库或驱动程序异常
            DRIVERNULL 23//驱动程序错误或尚未安装
            TIMEOUT 24//操作超时，一般是动态库没有反映
            TXSIZE 25//发送字数不够
            TXCRC 26//发送的CRC错
            RXSIZE 27//接收的字数不够
            RXCRC 28//接收的CRC错

            */
        }

        private void button8_Click(object sender, EventArgs e)//读取设备编号，可做为软件加密狗用,也可以根据此编号在公司网站上查询保修期限
        {
            byte[] devno = new byte[4];
            if (pcdgetdevicenumber(devno) == 0)
            {
                pcdbeep(50);
                MessageBox.Show("设备的序列号为："+System.Convert.ToString(devno[0]) + "-" + System.Convert.ToString(devno[1]) + "-" + System.Convert.ToString(devno[2]) + "-" + System.Convert.ToString(devno[3]),"示例程序");
                //ShowMessage(IntToStr(devno[0]) + "-" + IntToStr(devno[1]) + "-" + IntToStr(devno[2]) + "-" + IntToStr(devno[3]));
            }
        }

        private void button9_Click(object sender, EventArgs e)
        {
            string strls;
            strls = textBox1.Text;
            lcddispfull(strls);
        }

        private void button7_Click(object sender, EventArgs e)
        {
            if (button7.Text == "每十秒读一次")
            {
                pcdbeep(5);
                byte[] devno = new byte[4];
                if (pcdgetdevicenumber(devno) == 0)
                {
                    textBox4.Text = System.Convert.ToString(devno[0]) + "-" + System.Convert.ToString(devno[1]) + "-" + System.Convert.ToString(devno[2]) + "-" + System.Convert.ToString(devno[3]);
                }
                else
                { textBox4.Text = ""; }

                button12.Text = "轮询读IC卡号";
                timer1.Enabled = false;
                timer2.Enabled = true;
                button7.Text = "暂停";
            }
            else
            {
                timer2.Enabled = false;
                button7.Text = "每十秒读一次";
            }
        }

        private void button11_Click(object sender, EventArgs e)
        {
            byte status;//Store the return value
            byte[] mypiccserial = new byte[4];//card serial
            Int64 cardnumdec;
            status = piccrequest(mypiccserial);
            if (status == 0)
            {
                cardnumdec = mypiccserial[3];
                cardnumdec = cardnumdec * 256;
                cardnumdec = cardnumdec + mypiccserial[2];
                cardnumdec = cardnumdec * 256;
                cardnumdec = cardnumdec + mypiccserial[1];
                cardnumdec = cardnumdec * 256;
                cardnumdec = cardnumdec + mypiccserial[0];
                textBox3.Text = Convert.ToString(cardnumdec);
                pcdbeep(38);
            }
        }

        private void button5_Click(object sender, EventArgs e)
        {
            string strls;
            byte i;
            byte status;//存放返回值
            byte myareano;//区号
            byte authmode;//密码类型，用A密码或B密码
            byte myctrlword;//控制字
            byte[] mypicckey = new byte[6];//密码
            byte[] mypiccserial = new byte[4];//卡序列号
            byte[] mypiccdata = new byte[48]; //卡数据缓冲
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


            strls = textBox1.Text + "                                                 ";
            byte[] strlsansi = System.Text.Encoding.GetEncoding(936).GetBytes(strls);//转换为Ansi
            for (i = 0; i < 48; i++)
            {
                mypiccdata[i] = strlsansi[i];
            }

            status = piccwriteex(myctrlword, mypiccserial, myareano, authmode, mypicckey, mypiccdata);
            //在下面设定断点，然后查看mypiccserial、mypiccdata，
            //调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
            //开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
            //处理返回函数
            switch (status)
            {
                case 0:
                    pcdbeep(50);
                    MessageBox.Show("操作成功,下栏文字信息已写入卡中！","示例提示");
                    break;
                case 8:
                    MessageBox.Show("未寻到卡，请将卡放在感应区！", "示例提示");
                    break;
                case 9:
                    MessageBox.Show("读序列码错误！", "示例提示");
                    break;
                case 10:
                    MessageBox.Show("选卡错误！", "示例提示");
                    break;
                case 11:
                    MessageBox.Show("装载密码错误！", "示例提示");
                    break;
                case 12:
                    MessageBox.Show("卡密码认证错误！", "示例提示");
                    break;
                case 13:
                    MessageBox.Show("读卡错误！", "示例提示");
                    break;
                case 14:
                    MessageBox.Show("写卡错误！", "示例提示");
                    break;
                case 21:
                    MessageBox.Show("没有动态库！", "示例提示");
                    break;
                case 22:
                    MessageBox.Show("动态库或驱动程序异常！", "示例提示");
                    break;
                case 23:
                    MessageBox.Show("驱动程序错误或尚未安装！", "示例提示");
                    break;
                case 24:
                    MessageBox.Show("操作超时，一般是动态库没有反映！", "示例提示");
                    break;
                case 25:
                    MessageBox.Show("发送字数不够！", "示例提示");
                    break;
                case 26:
                    MessageBox.Show("发送的CRC错！", "示例提示");
                    break;
                case 27:
                    MessageBox.Show("接收的字数不够！", "示例提示");
                    break;
                case 28:
                    MessageBox.Show("接收的CRC错！", "示例提示");
                    break;
                default:
                    MessageBox.Show("返回码(对应的说明请看例子中的注释):" + status, "示例提示");
                    break;

            }
        }

        private void button6_Click(object sender, EventArgs e)
        {
            byte status;//存放返回值
            byte myareano;//区号
            byte authmode;//密码类型，用A密码或B密码
            byte myctrlword;//控制字
            byte[] mypicckey = new byte[6];//密码
            byte[] mypiccserial = new byte[4];//卡序列号
            byte[] mypiccdata = new byte[48]; //卡数据缓冲
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

            status = piccreadex(myctrlword, mypiccserial, myareano, authmode, mypicckey, mypiccdata);
            //在下面设定断点，然后查看mypiccserial、mypiccdata，
            //调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
            //开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
            //处理返回函数
            switch (status)
            {
                case 0:
                    string getdata = Encoding.Default.GetString(mypiccdata);
                    MessageBox.Show("读卡操作成功,卡内信息："+getdata, "示例程序");
                    break;
                case 8:
                    MessageBox.Show("未寻到卡，请将卡放在感应区！", "示例提示");
                    break;
                case 9:
                    MessageBox.Show("读序列码错误！", "示例提示");
                    break;
                case 10:
                    MessageBox.Show("选卡错误！", "示例提示");
                    break;
                case 11:
                    MessageBox.Show("装载密码错误！", "示例提示");
                    break;
                case 12:
                    MessageBox.Show("卡密码认证错误！", "示例提示");
                    break;
                case 13:
                    MessageBox.Show("读卡错误！", "示例提示");
                    break;
                case 14:
                    MessageBox.Show("写卡错误！", "示例提示");
                    break;
                case 21:
                    MessageBox.Show("没有动态库！", "示例提示");
                    break;
                case 22:
                    MessageBox.Show("动态库或驱动程序异常！", "示例提示");
                    break;
                case 23:
                    MessageBox.Show("驱动程序错误或尚未安装！", "示例提示");
                    break;
                case 24:
                    MessageBox.Show("操作超时，一般是动态库没有反映！", "示例提示");
                    break;
                case 25:
                    MessageBox.Show("发送字数不够！", "示例提示");
                    break;
                case 26:
                    MessageBox.Show("发送的CRC错！", "示例提示");
                    break;
                case 27:
                    MessageBox.Show("接收的字数不够！", "示例提示");
                    break;
                case 28:
                    MessageBox.Show("接收的CRC错！", "示例提示");
                    break;
                default:
                    MessageBox.Show("返回码(对应的说明请看例子中的注释):" + status, "示例提示");
                    break;
            }
        }

        private void timer2_Tick(object sender, EventArgs e)
        {
            byte[] devno = new byte[4];
            pcdbeep(5);
            if (pcdgetdevicenumber(devno) == 0)
            {
                textBox4.Text = System.Convert.ToString(devno[0]) + "-" + System.Convert.ToString(devno[1]) + "-" + System.Convert.ToString(devno[2]) + "-" + System.Convert.ToString(devno[3]);
            }
            else
            { textBox4.Text = ""; }
        }

        private void button10_Click(object sender, EventArgs e)
        {

        }

        private void button12_Click(object sender, EventArgs e)
        {
            if (button12.Text == "轮询读IC卡号")
            {
                button7.Text = "每十秒读一次";
                timer2.Enabled = false;
                timer1.Enabled = true;
                button12.Text = "暂停";
            }
            else
            {
                timer1.Enabled = false;
                button12.Text = "轮询读IC卡号";
            }
        }

        private void timer1_Tick(object sender, EventArgs e)
        {
            byte status;//Store the return value
            byte[] mypiccserial = new byte[4];//card serial
            Int64 cardnumdec;
            status = piccrequest(mypiccserial);
            if (status == 0)
            {
                cardnumdec = mypiccserial[3];
                cardnumdec = cardnumdec * 256;
                cardnumdec = cardnumdec + mypiccserial[2];
                cardnumdec = cardnumdec * 256;
                cardnumdec = cardnumdec + mypiccserial[1];
                cardnumdec = cardnumdec * 256;
                cardnumdec = cardnumdec + mypiccserial[0];
                textBox3.Text = Convert.ToString(cardnumdec);
                pcdbeep(38);
            }
        }

        private void Form1_Load(object sender, EventArgs e)
        {

        }

        private void button10_Click_1(object sender, EventArgs e)
        {
            byte status;//存放返回值
            byte myareano;//区号
            byte authmode;//密码类型，用A密码或B密码
            byte myctrlword;//控制字
            byte[] piccoldkey = new byte[6];//旧密码
            byte[] mypiccserial = new byte[4];//卡序列号
            byte[] piccnewkey = new byte[17]; //新密码.


            //控制字指定,控制字的含义请查看本公司网站提供的动态库说明
            myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY;

            //指定区号
            myareano = 8;//指定为第8区
            //批定密码模式
            authmode = 1;//大于0表示用A密码认证，推荐用A密码认证

            //指定旧密码
            piccoldkey[0] = 0xff;
            piccoldkey[1] = 0xff;
            piccoldkey[2] = 0xff;
            piccoldkey[3] = 0xff;
            piccoldkey[4] = 0xff;
            piccoldkey[5] = 0xff;

            //指定新密码,注意：指定新密码时一定要记住，否则有可能找不回密码，导致该卡报废。
            piccnewkey[0] = 0xff;  //A密码
            piccnewkey[1] = 0xff;
            piccnewkey[2] = 0xff;
            piccnewkey[3] = 0xff;
            piccnewkey[4] = 0xff;
            piccnewkey[5] = 0xff;

            piccnewkey[6] = 0xff;  //控制字，除非您确定了解控制字的含意，否则不要更改，错改卡将报废
            piccnewkey[7] = 0x07;
            piccnewkey[8] = 0x80;
            piccnewkey[9] = 0x69;

            piccnewkey[10] = 0xff;  //B密码
            piccnewkey[11] = 0xff;
            piccnewkey[12] = 0xff;
            piccnewkey[13] = 0xff;
            piccnewkey[14] = 0xff;
            piccnewkey[15] = 0xff;

            piccnewkey[16] = 0x03;  //'3是表示同时更改A、B、 密码权限访问字，为2表示密码权限访问字不更改，只改A、B密码，为0表示只改A密码

            status = piccchangesinglekeyex(myctrlword, mypiccserial, myareano, authmode, piccoldkey, piccnewkey);
            //在下面设定断点，然后查看mypiccserial、mypiccdata，
            //调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
            //开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
            //处理返回函数
            switch (status)
            {
                case 0:
                    pcdbeep(50);
                    MessageBox.Show("操作成功,密码已被修改!", "示例提示");
                    break;
                case 8:
                    MessageBox.Show("未寻到卡，请将卡放在感应区！", "示例提示");
                    break;
                case 9:
                    MessageBox.Show("读序列码错误！", "示例提示");
                    break;
                case 10:
                    MessageBox.Show("选卡错误！", "示例提示");
                    break;
                case 11:
                    MessageBox.Show("装载密码错误！", "示例提示");
                    break;
                case 12:
                    MessageBox.Show("卡密码认证错误！", "示例提示");
                    break;
                case 13:
                    MessageBox.Show("读卡错误！", "示例提示");
                    break;
                case 14:
                    MessageBox.Show("写卡错误！", "示例提示");
                    break;
                case 21:
                    MessageBox.Show("没有动态库！", "示例提示");
                    break;
                case 22:
                    MessageBox.Show("动态库或驱动程序异常！", "示例提示");
                    break;
                case 23:
                    MessageBox.Show("驱动程序错误或尚未安装！", "示例提示");
                    break;
                case 24:
                    MessageBox.Show("操作超时，一般是动态库没有反映！", "示例提示");
                    break;
                case 25:
                    MessageBox.Show("发送字数不够！", "示例提示");
                    break;
                case 26:
                    MessageBox.Show("发送的CRC错！", "示例提示");
                    break;
                case 27:
                    MessageBox.Show("接收的字数不够！", "示例提示");
                    break;
                case 28:
                    MessageBox.Show("接收的CRC错！", "示例提示");
                    break;
                default:
                    MessageBox.Show("返回码(对应的说明请看例子中的注释):" + status, "示例提示");
                    break;
            }
        }

        private void button14_Click(object sender, EventArgs e)
        {
            byte status;//Store the return value
            byte[] memo1 = new byte[4];//machinmemo1
            string readinf;
            status = pcdgetcustomizedata1(memo1);
            if (status == 0)
            {
                readinf = "";
                for (int i = 0; i < 4;i++ )
                {
                    readinf = readinf + memo1[i].ToString("X2");
                }
                textBox2.Text = readinf;
                pcdbeep(38);
            }
        }

        private void button13_Click(object sender, EventArgs e)
        {
            byte[] memo1 = new byte[4];
            string writinf;
            writinf = textBox2.Text.Trim()+"00000000";
            for (int i=0;i<4;i++)
            {
                memo1[i] =  Convert.ToByte(Convert.ToInt32(writinf.Substring(i * 2, 2),16)); 
            }
            byte status = pcdsetcustomizedata1(memo1);
            switch ( status)
            {
                case 0:
                    pcdbeep(50);
                    MessageBox.Show("操作成功,信息已写入设备!", "示例提示");
                    break;
                case 21:
                    MessageBox.Show("没有动态库！", "示例提示");
                    break;
                default:
                    MessageBox.Show("返回码(对应的说明请看例子中的注释):" + status, "示例提示");
                    break;
            }
        }

        private void button15_Click(object sender, EventArgs e)
        {
            byte[] memo1 = new byte[8];
            string writinf;
            writinf = textBox5.Text.Trim() + "0000000000000000";
            for (int i = 0; i < 8; i++)
            {
                memo1[i] = Convert.ToByte(Convert.ToInt32(writinf.Substring(i * 2, 2), 16));
            }
            byte status = pcdsetcustomizedata2(memo1);
            switch (status)
            {
                case 0:
                    pcdbeep(50);
                    MessageBox.Show("操作成功,信息已写入设备!", "示例提示");
                    break;
                case 21:
                    MessageBox.Show("没有动态库！", "示例提示");
                    break;
                default:
                    MessageBox.Show("返回码(对应的说明请看例子中的注释):" + status, "示例提示");
                    break;
            }
        }

        private void button16_Click(object sender, EventArgs e)
        {
            byte status;//Store the return value
            byte[] memo1 = new byte[8];//machinmemo1
            byte[] devno = new byte[4];
            string readinf;
            status = pcdgetcustomizedata2(memo1,devno);
            if (status == 0)
            {
                readinf = "";
                for (int i = 0; i < 8; i++)
                {
                    readinf = readinf + memo1[i].ToString("X2");
                }
                textBox5.Text = readinf;
                pcdbeep(38);
                MessageBox.Show("设备的序列号为：" + System.Convert.ToString(devno[0]) + "-" + System.Convert.ToString(devno[1]) + "-" + System.Convert.ToString(devno[2]) + "-" + System.Convert.ToString(devno[3]), "示例程序");
            }
        }
    }
}
