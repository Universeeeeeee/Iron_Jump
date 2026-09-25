using System;
using System.Drawing;
using System.Collections;
using System.ComponentModel;
using System.Windows.Forms;
using System.Data;
using System.Runtime.InteropServices;  //调用动态库一定要加入这个引用
using System.Text;//一定要加入这个


namespace iccardreader
{
	/// <summary>
	/// Form1 的摘要说明。
	/// </summary>
	public class Form1 : System.Windows.Forms.Form
	{
		private System.Windows.Forms.Button button1;
		private System.Windows.Forms.Button button2;
		private System.Windows.Forms.Button button3;
		private System.Windows.Forms.Button button4;
		private System.Windows.Forms.Button button5;
		private System.Windows.Forms.Label label1;
		/// <summary>
		/// 必需的设计器变量。
		//常量定义
		public const byte BLOCK0_EN = 0x01;//操作第0块
		public const byte BLOCK1_EN = 0x02;//操作第1块
		public const byte BLOCK2_EN = 0x04;//操作第2块
		public const byte NEEDSERIAL = 0x08;//仅对指定序列号的卡操作
		public const byte EXTERNKEY = 0x10;
		private System.Windows.Forms.TextBox textBox1;
		private System.Windows.Forms.Button button6;
		private System.Windows.Forms.Button button7;
		private System.Windows.Forms.Button button8;
		private System.Windows.Forms.TextBox textBox2;
		private System.Windows.Forms.Button button9;
		private System.Windows.Forms.Button button10;
		private System.Windows.Forms.Button button11;
		private System.Windows.Forms.TextBox textBox3;//用函数参数中的密码组进行读写卡时的认证,而不是用藏于读写器的芯片内的密码来认证。
		public const byte NEEDHALT = 0x20;//读卡或写卡后顺便休眠该卡，休眠后，卡必须拿离开感应区，再放回感应区，才能进行第二次操作。


		//------------------------------------------------------------------------------------------------------------------------------------------------------
		//外部函数声明：让设备发出声响
		[DllImport("OUR_MIFARE.dll", EntryPoint = "pcdbeep")]
		static extern byte pcdbeep(ulong xms);//xms单位为毫秒 

		//------------------------------------------------------------------------------------------------------------------------------------------------------    
		//只读卡号
		[DllImport("OUR_MIFARE.dll", EntryPoint = "piccrequest")]
		static extern byte piccrequest(byte[] serial);//devicenumber用于返回编号 

		//------------------------------------------------------------------------------------------------------------------------------------------------------    
		//读取设备编号，可做为软件加密狗用,也可以根据此编号在公司网站上查询保修期限
		[DllImport("OUR_MIFARE.dll", EntryPoint = "pcdgetdevicenumber")]
		static extern byte pcdgetdevicenumber(byte[] devicenumber);//devicenumber用于返回编号 


		//------------------------------------------------------------------------------------------------------------------------------------------------------
		//轻松读卡
		[DllImport("OUR_MIFARE.dll", EntryPoint = "piccreadex")]
		static extern byte piccreadex(byte ctrlword,byte[] serial,byte area,byte keyA1B0,byte[] picckey,byte[] piccdata0_2);
		//参数：说明
		//ctrlword：控制字
		//serial：卡序列号数组，用于指定或返回卡序列号
		//area：指定读卡区号
		//keyA1B0：指定用A或B密码认证,一般是用A密码，只有特殊用途下才用B密码，在这不做详细解释。
		//picckey：指定卡密码，6个字节，卡出厂时的初始密码为6个0xff
		//piccdata0_2：用于返回卡该区第0块到第2块的数据，共48个字节.


		//------------------------------------------------------------------------------------------------------------------------------------------------------
		//轻松写卡
		[DllImport("OUR_MIFARE.dll", EntryPoint = "piccwriteex")]
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
		[DllImport("OUR_MIFARE.dll", EntryPoint = "piccchangesinglekey")]
		static extern byte piccchangesinglekey(byte ctrlword, byte[] serial, byte area, byte keyA1B0, byte[] piccoldkey, byte[] piccnewkey);
		//参数：说明
		//ctrlword：控制字
		//serial：卡序列号数组，用于指定或返回卡序列号
		//area：指定读卡区号
		//keyA1B0：指定用A或B密码认证,一般是用A密码，只有特殊用途下才用B密码，在这不做详细解释。
		//piccoldkey：//旧密码
		//piccnewkey：//新密码.


		//------------------------------------------------------------------------------------------------------------------------------------------------------
		//发送显示内容到读卡器
		[DllImport("OUR_MIFARE.dll", EntryPoint = "lcddispfull")]
		static extern byte lcddispfull(string lcdstr);
		//参数：说明
		//lcdstr：显示内容
		
		/// </summary>
		private System.ComponentModel.Container components = null;

		public Form1()
		{
			//
			// Windows 窗体设计器支持所必需的
			//
			InitializeComponent();

			//
			// TODO: 在 InitializeComponent 调用后添加任何构造函数代码
			//
		}

		/// <summary>
		/// 清理所有正在使用的资源。
		/// </summary>
		protected override void Dispose( bool disposing )
		{
			if( disposing )
			{
				if (components != null) 
				{
					components.Dispose();
				}
			}
			base.Dispose( disposing );
		}

		#region Windows 窗体设计器生成的代码
		/// <summary>
		/// 设计器支持所需的方法 - 不要使用代码编辑器修改
		/// 此方法的内容。
		/// </summary>
		private void InitializeComponent()
		{
			this.button1 = new System.Windows.Forms.Button();
			this.button2 = new System.Windows.Forms.Button();
			this.button3 = new System.Windows.Forms.Button();
			this.button4 = new System.Windows.Forms.Button();
			this.button5 = new System.Windows.Forms.Button();
			this.label1 = new System.Windows.Forms.Label();
			this.textBox1 = new System.Windows.Forms.TextBox();
			this.button6 = new System.Windows.Forms.Button();
			this.button7 = new System.Windows.Forms.Button();
			this.button8 = new System.Windows.Forms.Button();
			this.textBox2 = new System.Windows.Forms.TextBox();
			this.button9 = new System.Windows.Forms.Button();
			this.button10 = new System.Windows.Forms.Button();
			this.button11 = new System.Windows.Forms.Button();
			this.textBox3 = new System.Windows.Forms.TextBox();
			this.SuspendLayout();
			// 
			// button1
			// 
			this.button1.Location = new System.Drawing.Point(8, 16);
			this.button1.Name = "button1";
			this.button1.Size = new System.Drawing.Size(104, 32);
			this.button1.TabIndex = 0;
			this.button1.Text = "轻松读卡";
			this.button1.Click += new System.EventHandler(this.button1_Click);
			// 
			// button2
			// 
			this.button2.Location = new System.Drawing.Point(120, 16);
			this.button2.Name = "button2";
			this.button2.Size = new System.Drawing.Size(104, 32);
			this.button2.TabIndex = 1;
			this.button2.Text = "轻松写卡";
			this.button2.Click += new System.EventHandler(this.button2_Click);
			// 
			// button3
			// 
			this.button3.Location = new System.Drawing.Point(344, 16);
			this.button3.Name = "button3";
			this.button3.Size = new System.Drawing.Size(104, 32);
			this.button3.TabIndex = 3;
			this.button3.Text = "让设备发出声响";
			this.button3.Click += new System.EventHandler(this.button3_Click);
			// 
			// button4
			// 
			this.button4.Location = new System.Drawing.Point(232, 16);
			this.button4.Name = "button4";
			this.button4.Size = new System.Drawing.Size(104, 32);
			this.button4.TabIndex = 2;
			this.button4.Text = "改单区密码";
			this.button4.Click += new System.EventHandler(this.button4_Click);
			// 
			// button5
			// 
			this.button5.Location = new System.Drawing.Point(8, 168);
			this.button5.Name = "button5";
			this.button5.Size = new System.Drawing.Size(440, 32);
			this.button5.TabIndex = 4;
			this.button5.Text = "读出设备全球唯一的设备编号，作为加密狗用";
			this.button5.Click += new System.EventHandler(this.button5_Click);
			// 
			// label1
			// 
			this.label1.Location = new System.Drawing.Point(16, 216);
			this.label1.Name = "label1";
			this.label1.Size = new System.Drawing.Size(432, 24);
			this.label1.TabIndex = 5;
			this.label1.Text = "建议将OUR_MIFARE.dll和ICUSB.DLL复制到应用程序同一目录下";
			// 
			// textBox1
			// 
			this.textBox1.Location = new System.Drawing.Point(8, 256);
			this.textBox1.Name = "textBox1";
			this.textBox1.Size = new System.Drawing.Size(264, 21);
			this.textBox1.TabIndex = 6;
			this.textBox1.Text = "天下风云出我辈 一入江湖岁月催";
			// 
			// button6
			// 
			this.button6.Location = new System.Drawing.Point(288, 248);
			this.button6.Name = "button6";
			this.button6.Size = new System.Drawing.Size(160, 32);
			this.button6.TabIndex = 7;
			this.button6.Text = "发送字符至读卡器显示";
			this.button6.Click += new System.EventHandler(this.button6_Click);
			// 
			// button7
			// 
			this.button7.Location = new System.Drawing.Point(232, 64);
			this.button7.Name = "button7";
			this.button7.Size = new System.Drawing.Size(104, 32);
			this.button7.TabIndex = 8;
			this.button7.Text = "写汉字至卡中";
			this.button7.Click += new System.EventHandler(this.button7_Click);
			// 
			// button8
			// 
			this.button8.Location = new System.Drawing.Point(344, 64);
			this.button8.Name = "button8";
			this.button8.Size = new System.Drawing.Size(104, 32);
			this.button8.TabIndex = 9;
			this.button8.Text = "从卡中读出汉字";
			// 
			// textBox2
			// 
			this.textBox2.Location = new System.Drawing.Point(112, 72);
			this.textBox2.Name = "textBox2";
			this.textBox2.Size = new System.Drawing.Size(112, 21);
			this.textBox2.TabIndex = 10;
			this.textBox2.Text = "王小明";
			// 
			// button9
			// 
			this.button9.Location = new System.Drawing.Point(8, 112);
			this.button9.Name = "button9";
			this.button9.Size = new System.Drawing.Size(104, 32);
			this.button9.TabIndex = 11;
			this.button9.Text = "只读卡号";
			this.button9.Click += new System.EventHandler(this.button9_Click);
			// 
			// button10
			// 
			this.button10.Location = new System.Drawing.Point(240, 296);
			this.button10.Name = "button10";
			this.button10.Size = new System.Drawing.Size(208, 32);
			this.button10.TabIndex = 13;
			this.button10.Text = "写指定卡15区数据为1~48";
			this.button10.Click += new System.EventHandler(this.button10_Click);
			// 
			// button11
			// 
			this.button11.Location = new System.Drawing.Point(8, 296);
			this.button11.Name = "button11";
			this.button11.Size = new System.Drawing.Size(104, 32);
			this.button11.TabIndex = 12;
			this.button11.Text = "先读卡";
			this.button11.Click += new System.EventHandler(this.button11_Click);
			// 
			// textBox3
			// 
			this.textBox3.Location = new System.Drawing.Point(120, 304);
			this.textBox3.Name = "textBox3";
			this.textBox3.Size = new System.Drawing.Size(56, 21);
			this.textBox3.TabIndex = 14;
			this.textBox3.Text = "AABBCCDD";
			// 
			// Form1
			// 
			this.AutoScaleBaseSize = new System.Drawing.Size(6, 14);
			this.ClientSize = new System.Drawing.Size(456, 358);
			this.Controls.Add(this.textBox3);
			this.Controls.Add(this.button10);
			this.Controls.Add(this.button11);
			this.Controls.Add(this.button9);
			this.Controls.Add(this.textBox2);
			this.Controls.Add(this.button8);
			this.Controls.Add(this.button7);
			this.Controls.Add(this.button6);
			this.Controls.Add(this.textBox1);
			this.Controls.Add(this.label1);
			this.Controls.Add(this.button5);
			this.Controls.Add(this.button3);
			this.Controls.Add(this.button4);
			this.Controls.Add(this.button2);
			this.Controls.Add(this.button1);
			this.Name = "Form1";
			this.Text = "Form1";
			this.ResumeLayout(false);

		}
		#endregion

		/// <summary>
		/// 应用程序的主入口点。
		/// </summary>
		[STAThread]
		static void Main() 
		{
			Application.Run(new Form1());
		}

		private void button1_Click(object sender, System.EventArgs e)//轻松读卡
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
					MessageBox.Show("操作成功,数据已返回在mypiccdata数组中");
					break;
					//......
				case 8:
					MessageBox.Show("请将卡放在感应区");
					break;
				default:
					MessageBox.Show("返回码(对应的说明请看例子中的注释):"+status);
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

		private void button3_Click(object sender, System.EventArgs e)//让设备发出声音
		{
			pcdbeep(50);
		}

		private void button2_Click(object sender, System.EventArgs e)//轻松写卡
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
			for (i = 0; i < 48; i++)
			{
				mypiccdata[i] = i;
			}

			status = piccwriteex(myctrlword, mypiccserial, myareano, authmode, mypicckey, mypiccdata);
			//在下面设定断点，然后查看mypiccserial、mypiccdata，
			//调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
			//开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
			//处理返回函数
			switch (status)
			{
				case 0:
					MessageBox.Show("操作成功,mypiccdata数组中的数据已写入卡中");
					break;
					//......
				case 8:
					MessageBox.Show("请将卡放在感应区");
					break;

				default:
					MessageBox.Show("返回码(对应的说明请看例子中的注释):"+status);
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

		private void button4_Click(object sender, System.EventArgs e)//修改单区密码
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
					//......
				case 8:
					MessageBox.Show("请将卡放在感应区");
					break;

				default:
					MessageBox.Show("返回码(对应的说明请看例子中的注释):"+status);
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

		private void button5_Click(object sender, System.EventArgs e)//读取设备编号，可做为软件加密狗用,也可以根据此编号在公司网站上查询保修期限
		{
			byte[] devno = new byte[4];
			if (pcdgetdevicenumber(devno) == 0)
			{
				MessageBox.Show(System.Convert.ToString(devno[0]) + "-" + System.Convert.ToString(devno[1]) + "-" +  System.Convert.ToString(devno[2]) + "-" +  System.Convert.ToString(devno[3]));
				//ShowMessage(IntToStr(devno[0]) + "-" + IntToStr(devno[1]) + "-" + IntToStr(devno[2]) + "-" + IntToStr(devno[3]));
			}
		}

		private void button6_Click(object sender, System.EventArgs e)
		{
			string strls;
			strls = textBox1.Text;
			lcddispfull(strls);
		}

		private void button7_Click(object sender, System.EventArgs e)
		{
			byte i;
			byte status;//存放返回值
			byte myareano;//区号
			byte authmode;//密码类型，用A密码或B密码
			byte myctrlword;//控制字
			byte[] mypicckey = new byte[6];//密码
			byte[] mypiccserial = new byte[4];//卡序列号
			byte[] mypiccdata = new byte[48]; //卡数据缓冲

			string strls ;
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


			strls=textBox2.Text;



					
				

				//MessageBox.Show(System.Convert.ToString((int)c));
 				
				
				


           


			//汉字编码解析
			

			//指定卡数据
			for (i = 0; i < 48; i++)
			{
				mypiccdata[i] = i;
			}

			status = piccwriteex(myctrlword, mypiccserial, myareano, authmode, mypicckey, mypiccdata);
			//在下面设定断点，然后查看mypiccserial、mypiccdata，
			//调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
			//开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
			//处理返回函数
			switch (status)
			{
				case 0:
					MessageBox.Show("操作成功,mypiccdata数组中的数据已写入卡中");
					break;
					//......
				case 8:
					MessageBox.Show("请将卡放在感应区");
					break;

				default:
					MessageBox.Show("返回码(对应的说明请看例子中的注释):"+status);
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

		private void button9_Click(object sender, System.EventArgs e)
		{
			byte status;//存放返回值
			uint cardhao; 
			string str;

			byte[] mypiccserial = new byte[4];//卡序列号

			status = piccrequest(mypiccserial);
			//在下面设定断点，然后查看mypiccserial、mypiccdata，
			//调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
			//开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
			//处理返回函数
			switch (status)
			{
				case 0:
					cardhao = mypiccserial[3];
					cardhao = cardhao * 256;
					cardhao = cardhao + mypiccserial[2];
					cardhao = cardhao * 256;
					cardhao = cardhao + mypiccserial[1];
					cardhao = cardhao * 256;
					cardhao = cardhao + mypiccserial[0];

					str = "000000000" + Convert.ToString(cardhao);//前面至少加9个0

					str = str.Substring(str.Length-10,10);


					MessageBox.Show("操作成功,数据已返回在mypiccserial数组中,转换成十位十进制数为" + str);
					break;
					//......
				case 8:
					MessageBox.Show("请将卡放在感应区");
					break;

				default:
					MessageBox.Show("返回码(对应的说明请看例子中的注释):"+status);
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

		private void button11_Click(object sender, System.EventArgs e)
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
			myareano = 15;//指定为第8区
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

			//status为0或大于9时mypiccserial数组值有效，mypiccserial返回IC卡序列号
			if((status == 0) || (status > 9))
			{
				textBox3.Text = Convert.ToString(mypiccserial[0],16) + Convert.ToString(mypiccserial[1],16) + Convert.ToString(mypiccserial[2],16) + Convert.ToString(mypiccserial[3],16);
			}
			switch (status)
			{
				case 0:

					MessageBox.Show("操作成功,数据已返回在mypiccdata数组中");
					break;
					//......
				case 8:
					MessageBox.Show("请将卡放在感应区");
					break;
				default:
					
					MessageBox.Show("返回码(对应的说明请看例子中的注释):"+status);
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

		private void button10_Click(object sender, System.EventArgs e)
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

			myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY + NEEDSERIAL;//NEEDSERIAL为需要

			//一定要先指定卡号,在textBox3中提取
			mypiccserial[0] = Convert.ToByte(textBox3.Text.Substring(0,2),16);
			mypiccserial[1] = Convert.ToByte(textBox3.Text.Substring(2,2),16);
			mypiccserial[2] = Convert.ToByte(textBox3.Text.Substring(4,2),16);
			mypiccserial[3] = Convert.ToByte(textBox3.Text.Substring(6,2),16);

			//指定区号
			myareano = 15;//指定为第8区
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
			for (i = 0; i < 48; i++)
			{
				mypiccdata[i] = Convert.ToByte(i+1);
			}

			status = piccwriteex(myctrlword, mypiccserial, myareano, authmode, mypicckey, mypiccdata);
			//在下面设定断点，然后查看mypiccserial、mypiccdata，
			//调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
			//开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
			//处理返回函数
			switch (status)
			{
				case 0:
					MessageBox.Show("操作成功,mypiccdata数组中的数据已写入卡中");
					break;
					//......
				case 8:
					MessageBox.Show("请将卡放在感应区");
					break;

				default:
					MessageBox.Show("返回码(对应的说明请看例子中的注释):"+status);
					break;

			}
		}
	}
}
