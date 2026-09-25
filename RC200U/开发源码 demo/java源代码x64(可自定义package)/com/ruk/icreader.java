package com.ruk;

public class icreader
{
	public native static byte pcdgetdevicenumber(byte[] devicenumber);static{System.loadLibrary("OUR_MIFARE_x64");}//读取设备编号

	public native static byte pcdbeep(int xms);static{System.loadLibrary("OUR_MIFARE_x64");}//让设备发出声音

	public native static byte piccreadex(byte ctrlword,byte[] serial,byte area,byte keyA1B0,byte[] picckey,byte[] piccdata0_2);static{System.loadLibrary("OUR_MIFARE_x64");}//轻松读卡

	public native static byte piccwriteex(byte ctrlword,byte[] serial,byte area,byte keyA1B0,byte[] picckey,byte[] piccdata0_2);static{System.loadLibrary("OUR_MIFARE_x64");}//轻松写卡

	public native static byte piccchangesinglekey(byte ctrlword,byte[] serial,byte area,byte keyA1B0,byte[] piccoldkey,byte[] piccnewkey);static{System.loadLibrary("OUR_MIFARE_x64");}//改单区密码

	public native static byte piccchangesinglekeyex(byte ctrlword,byte[] serial,byte area,byte keyA1B0,byte[] piccoldkey,byte[] piccdata);static{System.loadLibrary("OUR_MIFARE_x64");}//改单区密码，可同时修改A密码，或密码权限访问字(密码权限编码)或B密码
	

}
