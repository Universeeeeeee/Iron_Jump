package com.icmcu;
import com.ruk.icreader;

public class test
{
	public static final byte BLOCK0_EN = 0x01;//操作第0块
	public static final byte BLOCK1_EN = 0x02;//操作第1块
	public static final byte BLOCK2_EN = 0x04;//操作第2块
	public static final byte NEEDSERIAL = 0x08;//仅对指定序列号的卡操作
	public static final byte EXTERNKEY = 0x10;//使用函数时需指定密码，否则使用预存在读写器中的密码（该密码只能写入，无法读出，很安全）
	public static final byte NEEDHALT = 0x20;//读卡或写卡后顺便休眠该卡，休眠后，卡必须拿离开感应区，再放回感应区，才能进行第二次操作。

	public static void main(String[] args)
	{

		// TODO Auto-generated method stub
		if(args.length == 0)
		{
			System.out.println("请先输入参数!");
			return;
		}
		//Java中只能使用string1.equals(string2)的方式来比较字符串 
		if(args[0].equals("1"))
		{//读取设备编号，可做为软件加密狗用,也可以根据此编号在公司网站上查询保修期限
			int status;//存放返回值
			byte[] devicenumber = new byte[4];
			status = (int)(icreader.pcdgetdevicenumber(devicenumber) & 0xff);//& 0xff用于转为无符号行数据
			System.out.print("\n\n1-读取设备编号\n");
			System.out.print("结果:");
			if(status == 0)
			{
				System.out.print("读取成功!设备编号为" + (devicenumber[0] & 0xff) + "-" + (devicenumber[1] & 0xff) + "-" + (devicenumber[2] & 0xff) + "-" + (devicenumber[3] & 0xff));
				System.out.print("\n\n");
			}
			else
			{
				String strls = ""; 
				if(status == 23)
				{
					strls = "，错误提示：读卡器未插入或驱动程序未安装";
				}
				
				System.out.print("错误代码:" + Integer.toString(status) + strls + "\n\n");
				
				
			}
		}
		else if(args[0].equals("2"))
		{//让设备发出声音
			System.out.print("\n\n2-驱动读卡器嘀一声\n");
			System.out.print("结果:如果能听到读卡器嘀一声表示成功，否则请检查读卡器是否已连上线！\n\n");
			icreader.pcdbeep(50);


		}
		else if(args[0].equals("3"))
		{//轻松读卡
			int status;//存放返回值
            		byte myareano;//区号
            		byte authmode;//密码类型，用A密码或B密码
            		byte myctrlword;//控制字
            		byte[] mypicckey = new byte[6];//密码
            		byte[] mypiccserial = new byte[4];//卡序列号
            		byte[] mypiccdata = new byte[48]; //卡数据缓冲

			//控制字指定,控制字的含义请查看本公司网站提供的动态库说明
            		myctrlword = (byte)(BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY);

            		//指定区号
            		myareano = 8;//指定为第8区
            		//批定密码模式
            		authmode = 1;//大于0表示用A密码认证，推荐用A密码认证

            		//指定密码
            		mypicckey[0] = (byte)0xff;
            		mypicckey[1] = (byte)0xff;
            		mypicckey[2] = (byte)0xff;
            		mypicckey[3] = (byte)0xff;
            		mypicckey[4] = (byte)0xff;
            		mypicckey[5] = (byte)0xff;

            		status = (int)(icreader.piccreadex(myctrlword, mypiccserial, myareano, authmode, mypicckey, mypiccdata) & 0xff);

			System.out.print("\n\n3-轻松读卡\n");
	
			switch (status)
            		{
                		case 0:
                    			System.out.print("结果:成功!卡序列号为" + Integer.toHexString(mypiccserial[0] & 0xff) + "-" + Integer.toHexString(mypiccserial[1] & 0xff) + "-" + Integer.toHexString(mypiccserial[2] & 0xff) + "-" + Integer.toHexString(mypiccserial[3] & 0xff));
					System.out.print("\n卡扇区数据存放在mypiccdata数组中");
					System.out.print("\n\n");
					icreader.pcdbeep(50);
                    			break;
                			//......
                		case 8:
					System.out.print("请将卡放在感应区...\n\n");

                    			break;
                		default:
								String strls = ""; 
								if(status == 23)
								{
									strls = "，错误提示：读卡器未插入或驱动程序未安装";
								}
                    			System.out.print("错误代码:" + Integer.toString(status) + strls + "\n\n");
                    			break;


            		}
		}
		else if(args[0].equals("4"))
		{//轻松写卡

            		int i;
                        int status;//存放返回值
                        byte myareano;//区号
                        byte authmode;//密码类型，用A密码或B密码
                        byte myctrlword;//控制字
                        byte[] mypicckey = new byte[6];//密码
                        byte[] mypiccserial = new byte[4];//卡序列号
                        byte[] mypiccdata = new byte[48]; //卡数据缓冲
                        //控制字指定,控制字的含义请查看本公司网站提供的动态库说明

                        myctrlword = (byte)(BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY);

                        //指定区号
                        myareano = 8;//指定为第8区
                        //批定密码模式
                        authmode = 1;//大于0表示用A密码认证，推荐用A密码认证

                        //指定密码
                        mypicckey[0] = (byte)0xff;
            		mypicckey[1] = (byte)0xff;
            		mypicckey[2] = (byte)0xff;
            		mypicckey[3] = (byte)0xff;
            		mypicckey[4] = (byte)0xff;
            		mypicckey[5] = (byte)0xff;

                        //指定卡数据
                        for (i = 0; i < 48; i++)
                        {
                            mypiccdata[i] = (byte)i;
                        }

                        status = (int)(icreader.piccwriteex(myctrlword, mypiccserial, myareano, authmode, mypicckey, mypiccdata) & 0xff);
                        //在下面设定断点，然后查看mypiccserial、mypiccdata，
                        //调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
                        //开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
                        //处理返回函数

			System.out.print("\n\n4-轻松写卡\n");
                        switch (status)
                        {
                        	case 0:
					System.out.print("结果:成功!卡序列号为" + Integer.toHexString(mypiccserial[0] & 0xff) + "-" + Integer.toHexString(mypiccserial[1] & 0xff) + "-" + Integer.toHexString(mypiccserial[2] & 0xff) + "-" + Integer.toHexString(mypiccserial[3] & 0xff));
					System.out.print("\nmypiccdata数组中的数据已写入卡扇区中");
					System.out.print("\n\n");
					icreader.pcdbeep(50);

					break;
                            	//......
                            	case 8:
                                	System.out.print("请将卡放在感应区...\n\n");
                                	break;

                            	default:
								
									String strls = ""; 
									if(status == 23)
									{
										strls = "，错误提示：读卡器未插入或驱动程序未安装";
									}
                                	System.out.print("错误代码:" + Integer.toString(status) + strls + "\n\n");
                                	break;

                        }



		}
		else if(args[0].equals("5"))
		{//改单区密码

			int status;//存放返回值
                        byte myareano;//区号
                        byte authmode;//密码类型，用A密码或B密码
                        byte myctrlword;//控制字
                        byte[] mypiccserial = new byte[4];//卡序列号

			byte[] piccoldkey = new byte[6];//旧密码
                        byte[] piccnewkey = new byte[6]; //新密码.


                        //控制字指定,控制字的含义请查看本公司网站提供的动态库说明
                        myctrlword = EXTERNKEY;

                        //指定区号
                        myareano = 8;//指定为第8区
                        //批定密码模式
                        authmode = 1;//大于0表示用A密码认证，推荐用A密码认证

                        //指定旧密码
                        piccoldkey[0] = (byte)0xff;
                        piccoldkey[1] = (byte)0xff;
                        piccoldkey[2] = (byte)0xff;
                        piccoldkey[3] = (byte)0xff;
                        piccoldkey[4] = (byte)0xff;
                        piccoldkey[5] = (byte)0xff;

                        //指定新密码,注意：指定新密码时一定要记住，否则有可能找不回密码，导致该卡报废。
                        piccnewkey[0] = (byte)0xff;
                        piccnewkey[1] = (byte)0xff;
                        piccnewkey[2] = (byte)0xff;
                        piccnewkey[3] = (byte)0xff;
                        piccnewkey[4] = (byte)0xff;
                        piccnewkey[5] = (byte)0xff;

                        status = (int)(icreader.piccchangesinglekey(myctrlword, mypiccserial, myareano, authmode, piccoldkey, piccnewkey) & 0xff);
                        //在下面设定断点，然后查看mypiccserial、mypiccdata，
                        //调用完 piccreadex函数可读出卡序列号到 mypiccserial，读出卡数据到mypiccdata，
                        //开发人员根据自己的需要处理mypiccserial、mypiccdata 中的数据了。
                        //处理返回函数
			System.out.print("\n\n5-改单区密码\n");
                        switch (status)
                        {
				case 0:
					System.out.print("结果:成功!卡序列号为" + Integer.toHexString(mypiccserial[0] & 0xff) + "-" + Integer.toHexString(mypiccserial[1] & 0xff) + "-" + Integer.toHexString(mypiccserial[2] & 0xff) + "-" + Integer.toHexString(mypiccserial[3] & 0xff));
					System.out.print("\n密码已被修改!");
					System.out.print("\n\n");
					icreader.pcdbeep(50);

                                	break;
                            	//......
				case 8:
                            		System.out.print("请将卡放在感应区...\n\n");
                                	break;

                            	default:
								
									String strls = ""; 
									if(status == 23)
									{
										strls = "，错误提示：读卡器未插入或驱动程序未安装";
									}
                                	System.out.print("错误代码:" + Integer.toString(status) + strls + "\n\n");
                                	break;

                        }


		}
		else  if(args[0].equals("6")) 
		{//改单区密码-扩展指令

			int status;//存放返回值
                        byte myareano;//区号
                        byte authmode;//密码类型，用A密码或B密码
                        byte myctrlword;//控制字
                        byte[] mypiccserial = new byte[4];//卡序列号

			byte[] piccoldkey = new byte[6];//旧密码
                        byte[] piccdata = new byte[17]; //新密码

			//控制字指定,控制字的含义请查看本公司网站提供的动态库说明
                        myctrlword = EXTERNKEY;

                        //指定区号
                        myareano = 8;//指定为第8区
                        //批定密码模式
                        authmode = 1;//大于0表示用A密码认证，推荐用A密码认证

			//指定旧密码
                        piccoldkey[0] = (byte)0xff;
                        piccoldkey[1] = (byte)0xff;
                        piccoldkey[2] = (byte)0xff;
                        piccoldkey[3] = (byte)0xff;
                        piccoldkey[4] = (byte)0xff;
                        piccoldkey[5] = (byte)0xff;

                        //指定新密码,注意：指定新密码时一定要记住，否则有可能找不回密码，导致该卡报废。
                        piccdata[0] = (byte)0xff;
                        piccdata[1] = (byte)0xff;
                        piccdata[2] = (byte)0xff;
                        piccdata[3] = (byte)0xff;
                        piccdata[4] = (byte)0xff;
                        piccdata[5] = (byte)0xff;

			//访问位FF078069
			piccdata[6] = (byte)0xff;
                        piccdata[7] = (byte)0x07;
                        piccdata[8] = (byte)0x80;
                        piccdata[9] = (byte)0x69;

			piccdata[10] = (byte)0xff;
                        piccdata[11] = (byte)0xff;
                        piccdata[12] = (byte)0xff;
                        piccdata[13] = (byte)0xff;
                        piccdata[14] = (byte)0xff;
                        piccdata[15] = (byte)0xff;

			piccdata[16] = (byte)0x03;//同时改密码和访问位

			status=(int)icreader.piccchangesinglekeyex(myctrlword,mypiccserial,myareano,authmode,piccoldkey,piccdata);

			System.out.print("\n\n6-改单区密码(扩展指令)\n");
                        switch (status)
                        {
				case 0:
					System.out.print("结果:成功!卡序列号为" + Integer.toHexString(mypiccserial[0] & 0xff) + "-" + Integer.toHexString(mypiccserial[1] & 0xff) + "-" + Integer.toHexString(mypiccserial[2] & 0xff) + "-" + Integer.toHexString(mypiccserial[3] & 0xff));
					System.out.print("\n密码已被修改!");
					System.out.print("\n\n");
					icreader.pcdbeep(50);

                                	break;
                            	//......
				case 8:
                            		System.out.print("请将卡放在感应区...\n\n");
                                	break;

                            	default:
									String strls = ""; 
									if(status == 23)
									{
										strls = "，错误提示：读卡器未插入或驱动程序未安装";
									}
                                	System.out.print("错误代码:" + Integer.toString(status) + strls + "\n\n");
                                	break;

                        }


		}



/*

返回错误代码解释

#define ERR_REQUEST 8'寻卡错误
#define ERR_READSERIAL 9'读序列吗错误
#define ERR_SELECTCARD 10'选卡错误
#define ERR_LOADKEY 11'装载密码错误
#define ERR_AUTHKEY 12'密码认证错误
#define ERR_READ 13'读卡错误
#define ERR_WRITE 14'写卡错误
#define ERR_NONEDLL 21'没有动态库
#define ERR_DRIVERORDLL 22'动态库或驱动程序异常
#define ERR_DRIVERNULL 23'读卡器未插入或驱动程序未安装
#define ERR_TIMEOUT 24'操作超时，一般是动态库没有反映
#define ERR_TXSIZE 25'发送字数不够
#define ERR_TXCRC 26'发送的CRC错
#define ERR_RXSIZE 27'接收的字数不够
#define ERR_RXCRC 28'接收的CRC错

*/






	
	}

	




}
