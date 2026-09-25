using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Data;
using System.Drawing;
using System.Linq;
//using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

using System.Runtime.InteropServices;  //call dll must declare 
using System.Text;//Be sure to join this


namespace WindowsFormsApplication1
{
    public partial class Form1 : Form
    {
        //Constants defined
        public const byte BLOCK0_EN = 0x01;//Operating 0 blocks
        public const byte BLOCK1_EN = 0x02;//Operating 1 blocks
        public const byte BLOCK2_EN = 0x04;//Operating 2 blocks
        public const byte NEEDSERIAL = 0x08;//Only the specified serial number card operation
        public const byte EXTERNKEY = 0x10;
        public const byte NEEDHALT = 0x20;//Read or write CARDS after dormancy card, by the way, after dormancy, leave induction card must take, return to active area, to carry out the second operation。

        //------------------------------------------------------------------------------------------------------------------------------------------------------
        //External function declaration: make sound equipment
        [DllImport("OUR_MIFARE.dll", EntryPoint = "pcdbeep", CallingConvention = CallingConvention.StdCall)]
        static extern byte pcdbeep(UInt32 xms);//xms  milliseconds 


        //------------------------------------------------------------------------------------------------------------------------------------------------------    
        //Read-only card number
        [DllImport("OUR_MIFARE.dll", EntryPoint = "piccrequest", CallingConvention = CallingConvention.StdCall)]
        public static extern byte piccrequest(byte[] serial);//devicenumber 

        //------------------------------------------------------------------------------------------------------------------------------------------------------    
        //Read the device number, can be used as a software encryption dog, can also according to the number on the company website query warranty period
        [DllImport("OUR_MIFARE.dll", EntryPoint = "pcdgetdevicenumber", CallingConvention = CallingConvention.StdCall)]
        static extern byte pcdgetdevicenumber(byte[] devicenumber);//devicenumber


        //------------------------------------------------------------------------------------------------------------------------------------------------------
        //Easy to read
        [DllImport("OUR_MIFARE.dll", EntryPoint = "piccreadex", CallingConvention = CallingConvention.StdCall)]
        static extern byte piccreadex(byte ctrlword, byte[] serial, byte area, byte keyA1B0, byte[] picckey, byte[] piccdata0_2);
        //parameters:
        //ctrlword：
        //serial：Card serial number array, is used to specify or return card serial number
        //area：Specifies read card code
        //keyA1B0：Specified with A or B Key authentication, usually with A Key, only under the special purpose, with B Key in this to do A detailed explanation。
        //picckey：Specified card Key, 6 bytes, initial Key for the card when they leave is  6个0xff
        //piccdata0_2：Used to return to the card the 0 to 2 pieces of data, a total of 48 bytes.


        //------------------------------------------------------------------------------------------------------------------------------------------------------
        //Easy to write
        [DllImport("OUR_MIFARE.dll", EntryPoint = "piccwriteex", CallingConvention = CallingConvention.StdCall)]
        static extern byte piccwriteex(byte ctrlword, byte[] serial, byte area, byte keyA1B0, byte[] picckey, byte[] piccdata0_2);
        //parameters:
        //ctrlword：
        //serial：Card serial number array, is used to specify or return card serial number
        //area：Specifies read card code
        //keyA1B0：Specified with A or B Key authentication, usually with A Key, only under the special purpose, with B Key in this to do A detailed explanation。
        //picckey：Specified card Key, 6 bytes, initial Key for the card when they leave is  6个0xff
        //piccdata0_2：Used to return to the card the 0 to 2 pieces of data, a total of 48 bytes.


        //------------------------------------------------------------------------------------------------------------------------------------------------------
        //The Key change card list
        [DllImport("OUR_MIFARE.dll", EntryPoint = "piccchangesinglekey", CallingConvention = CallingConvention.StdCall)]
        static extern byte piccchangesinglekey(byte ctrlword, byte[] serial, byte area, byte keyA1B0, byte[] piccoldkey, byte[] piccnewkey);
        //parameters:
        //ctrlword：
        //serial：Card serial number array, is used to specify or return card serial number
        //area：Specifies read card code
        //keyA1B0：Specified with A or B Key authentication, usually with A Key, only under the special purpose, with B Key in this to do A detailed explanation。
        //piccoldkey：//Old Key
        //piccnewkey：//New Key.


        //------------------------------------------------------------------------------------------------------------------------------------------------------
        //Send Display Information to Drive
        [DllImport("OUR_MIFARE.dll", EntryPoint = "lcddispfull", CallingConvention = CallingConvention.StdCall)]
        static extern byte lcddispfull(string lcdstr);
        //parameters:
        //lcdstr：According to the content

        public Form1()
        {
            InitializeComponent();
        }

        private void button1_Click(object sender, EventArgs e)//easy to read ICcard
        {
            byte status;//Store the return value
            byte myareano;//sector
            byte authmode;//authentication Key type, with A Key or B Key
            byte myctrlword;//Control word
            byte[] mypicckey = new byte[6];//Key
            byte[] mypiccserial = new byte[4];//Card serial number
            byte[] mypiccdata = new byte[48]; //Card data buffer
            //control word please check our company web site provides dynamic libraries
            myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY;

            //sector
            myareano = 8;//sector is 8
            //authentication key Type
            authmode = 1;//>0 with A，default A

            //the Key
            mypicckey[0] = 0xff;
            mypicckey[1] = 0xff;
            mypicckey[2] = 0xff;
            mypicckey[3] = 0xff;
            mypicckey[4] = 0xff;
            mypicckey[5] = 0xff;

            status = piccreadex(myctrlword, mypiccserial, myareano, authmode, mypicckey, mypiccdata);
            //In the following set breakpoints, and then look at it  " mypiccserial、mypiccdata"
            //call piccreadex function can read ic serialNo to " mypiccserial"，card infomation into "mypiccdata"
            //Developers based on their own to deal with  " mypiccserial、mypiccdata" 
   
            switch (status)
            {
                case 0:
                    pcdbeep(38);
                    MessageBox.Show("Operation is successful, the data returned in mypiccdata array!", "Note:", MessageBoxButtons.OK, MessageBoxIcon.Asterisk);
                    break;
                //......
                case 8:
                    MessageBox.Show("Please put the card on the induction area", "Note:", MessageBoxButtons.OK, MessageBoxIcon.Stop );
                    break;
                default:
                    MessageBox.Show("Error Code:" + status, "warn",MessageBoxButtons.OK, MessageBoxIcon.Warning );
                    break;


            }


            //Return to explain
            /*
            REQUEST 8//Not Find card 
            READSERIAL 9//Read a sequence error
            SELECTCARD 10//Selected card error
            LOADKEY 11//load key errir
            AUTHKEY 12//authentication Key error
            READ 13//Read card Error
            WRITE 14//Write card Error

            NONEDLL 21//not dll
            DRIVERORDLL 22//dll files error
            DRIVERNULL 23//not install drivers or the drivers is  err
            TIMEOUT 24//Timeout 
            TXSIZE 25//Send word is not enough
            TXCRC 26//send CRC error
            RXSIZE 27// receive information is not enough
            RXCRC 28//receive CRC is error



            */
        }

        private void button2_Click(object sender, EventArgs e)//easy to write card
        {
            byte i;
            byte status;//Store the return value
            byte myareano;//sector
            byte authmode;//authentication Key type, with A Key or B Key
            byte myctrlword;//Control word
            byte[] mypicckey = new byte[6];//Key
            byte[] mypiccserial = new byte[4];//Card serial number
            byte[] mypiccdata = new byte[48]; //Card data buffer
            //control word please check our company web site provides dynamic libraries

            myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY;

            //sector
            myareano = 8;//sector is 8
            //authentication key Type
            authmode = 1;//>0 with A Key，advice A Key

            //Key
            mypicckey[0] = 0xff;
            mypicckey[1] = 0xff;
            mypicckey[2] = 0xff;
            mypicckey[3] = 0xff;
            mypicckey[4] = 0xff;
            mypicckey[5] = 0xff;

            //Write Card Buff
            for (i = 0; i < 48; i++)
            {
                mypiccdata[i] = i;
            }

            status = piccwriteex(myctrlword, mypiccserial, myareano, authmode, mypicckey, mypiccdata);
            //In the following set breakpoints, and then look at it  " mypiccserial、mypiccdata"
            //call piccreadex function can read ic serialNo to " mypiccserial"，card infomation into "mypiccdata"
            //Developers based on their own to deal with  " mypiccserial、mypiccdata" 
            switch (status)
            {
                case 0:
                    MessageBox.Show("Operation is successful, mypiccdata arrays of data has been written to the card", "Note:", MessageBoxButtons.OK, MessageBoxIcon.Information );
                    break;
                //......
                case 8:
                    MessageBox.Show("Please put the card on the induction area", "Note:",  MessageBoxButtons.OK, MessageBoxIcon.Stop);
                    break;

                default:
                    MessageBox.Show("Eooro Code:" + status,  "warn:", MessageBoxButtons.OK, MessageBoxIcon.Stop);
                    break;

            }


            //Return to explain
            /*
            REQUEST 8//Not Find card 
            READSERIAL 9//Read a sequence error
            SELECTCARD 10//Selected card error
            LOADKEY 11//load key errir
            AUTHKEY 12//authentication Key error
            READ 13//Read card Error
            WRITE 14//Write card Error

            NONEDLL 21//not dll
            DRIVERORDLL 22//dll files error
            DRIVERNULL 23//not install drivers or the drivers is  err
            TIMEOUT 24//Timeout 
            TXSIZE 25//Send word is not enough
            TXCRC 26//send CRC error
            RXSIZE 27// receive information is not enough
            RXCRC 28//receive CRC is error



            */
        }

        private void button4_Click(object sender, EventArgs e)
        {
            pcdbeep(50);
        }

        private void button3_Click(object sender, EventArgs e)
        {
            byte status;//Store the return value
            byte myareano;//sector
            byte authmode;//authentication Key type, with A Key or B Key
            byte myctrlword;//Control word
            byte[] piccoldkey = new byte[6];//Old Key
            byte[] piccnewkey = new byte[6];//New Key
            byte[] mypiccserial = new byte[4];//Card serial number
            byte[] mypiccdata = new byte[48]; //Card data buffer
            //control word please check our company web site provides dynamic libraries

            myctrlword = 0;

            //sector
            myareano = 8;//sector is 8
            //authentication key Type
            authmode = 1;//>0 with A Key，advice A Key

            //Old Key
            piccoldkey[0] = 0xff;
            piccoldkey[1] = 0xff;
            piccoldkey[2] = 0xff;
            piccoldkey[3] = 0xff;
            piccoldkey[4] = 0xff;
            piccoldkey[5] = 0xff;

            //New Key ,Note：Remember, specify the new password, otherwise it could get back the password, which they lead to scrap
            piccnewkey[0] = 0xff;
            piccnewkey[1] = 0xff;
            piccnewkey[2] = 0xff;
            piccnewkey[3] = 0xff;
            piccnewkey[4] = 0xff;
            piccnewkey[5] = 0xff;

            status = piccchangesinglekey(myctrlword, mypiccserial, myareano, authmode, piccoldkey, piccnewkey);
            //In the following set breakpoints, and then look at it  " mypiccserial、mypiccdata"
            //call piccreadex function can read ic serialNo to " mypiccserial"，card infomation into "mypiccdata"
            //Developers based on their own to deal with  " mypiccserial、mypiccdata" 
            switch (status)
            {
                case 0:
                    MessageBox.Show("Operation is successful, the Key has been modified!",  "Note:", MessageBoxButtons.OK, MessageBoxIcon.Information );
                    break;
                //......
                case 8:
                    MessageBox.Show("Please put the card on the induction area", "Note:", MessageBoxButtons.OK, MessageBoxIcon.Stop);
                    break;

                default:
                    MessageBox.Show("Error Code:" + status, "Note:", MessageBoxButtons.OK, MessageBoxIcon.Warning  );
                    break;

            }


            //Return to explain
            /*
            REQUEST 8//Not Find card 
            READSERIAL 9//Read a sequence error
            SELECTCARD 10//Selected card error
            LOADKEY 11//load key errir
            AUTHKEY 12//authentication Key error
            READ 13//Read card Error
            WRITE 14//Write card Error

            NONEDLL 21//not dll
            DRIVERORDLL 22//dll files error
            DRIVERNULL 23//not install drivers or the drivers is  err
            TIMEOUT 24//Timeout 
            TXSIZE 25//Send word is not enough
            TXCRC 26//send CRC error
            RXSIZE 27// receive information is not enough
            RXCRC 28//receive CRC is error



            */
        }

        private void button8_Click(object sender, EventArgs e)//Read the device number, can be used as a software encryption dog, can also according to the number on the company website query warranty period
        {
            byte[] devno = new byte[4];
            if (pcdgetdevicenumber(devno) == 0)
            {
                MessageBox.Show(System.Convert.ToString(devno[0]) + "-" + System.Convert.ToString(devno[1]) + "-" + System.Convert.ToString(devno[2]) + "-" + System.Convert.ToString(devno[3]));
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

        }

        private void button11_Click(object sender, EventArgs e)
        {
            byte status;//Store the return value
            byte[] mypiccserial = new byte[4];//card serial
            Int64  cardnumdec;
            status = piccrequest(mypiccserial);
            switch (status)
            {
                case 0:                    
                    cardnumdec=mypiccserial[3];
                    cardnumdec = cardnumdec * 256;
                    cardnumdec = cardnumdec+mypiccserial[2];
                    cardnumdec = cardnumdec * 256;
                    cardnumdec = cardnumdec+mypiccserial[1];
                    cardnumdec = cardnumdec * 256;
                    cardnumdec = cardnumdec+mypiccserial[0];
                    textBox3.Text = Convert.ToString (cardnumdec);
                    pcdbeep(38);
                    MessageBox.Show("Operation is successful!", "note:", MessageBoxButtons.OK, MessageBoxIcon.Asterisk );
                    break;
                //......
                case 8:
                    textBox3.Text ="";
                    MessageBox.Show("Please put the card on the induction area!", "Note:", MessageBoxButtons.OK, MessageBoxIcon.Stop);
                    break;

                default:
                    textBox3.Text = ""; 
                    MessageBox.Show("Error Code:" + status,"warn", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    break;

            }
        }

        private void button10_Click(object sender, EventArgs e)
        {

        }

        private void button5_Click(object sender, EventArgs e)
        {
            byte i;
            string writestr;
            byte status;//Store the return value
            byte myareano;//sector
            byte authmode;//authentication Key type, with A Key or B Key
            byte myctrlword;//Control word
            byte[] mypicckey = new byte[6];//Key
            byte[] mypiccserial = new byte[4];//Card serial number
            byte[] mypiccdata = new byte[48]; //Card data buffer
            //control word please check our company web site provides dynamic libraries

            myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY;

            //sector
            myareano = 8;//sector is 8
            //authentication key Type
            authmode = 1;//>0 with A Key，advice A Key

            //Key
            mypicckey[0] = 0xff;
            mypicckey[1] = 0xff;
            mypicckey[2] = 0xff;
            mypicckey[3] = 0xff;
            mypicckey[4] = 0xff;
            mypicckey[5] = 0xff;

            //Write Card Buff
            for (i = 0; i < 48; i++)
            {
                mypiccdata[i] =0;
            }
            writestr = textBox1.Text.Trim() + "                                                  ";
            mypiccdata = System.Text.Encoding.ASCII.GetBytes(writestr);

            status = piccwriteex(myctrlword, mypiccserial, myareano, authmode, mypicckey, mypiccdata);
            //In the following set breakpoints, and then look at it  " mypiccserial、mypiccdata"
            //call piccreadex function can read ic serialNo to " mypiccserial"，card infomation into "mypiccdata"
            //Developers based on their own to deal with  " mypiccserial、mypiccdata" 
            switch (status)
            {
                case 0:
                    pcdbeep(38);
                    MessageBox.Show("Operation is successful, mypiccdata arrays of data has been written to the card", "Note:", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    break;
                //......
                case 8:
                    MessageBox.Show("Please put the card on the induction area", "Note:", MessageBoxButtons.OK, MessageBoxIcon.Stop);
                    break;

                default:
                    MessageBox.Show("Eooro Code:" + status, "warn:", MessageBoxButtons.OK, MessageBoxIcon.Stop);
                    break;

            }
        }

        private void button6_Click(object sender, EventArgs e)
        {
            byte status;//Store the return value
            byte myareano;//sector
            byte authmode;//authentication Key type, with A Key or B Key
            byte myctrlword;//Control word
            byte[] mypicckey = new byte[6];//Key
            byte[] mypiccserial = new byte[4];//Card serial number
            byte[] mypiccdata = new byte[48]; //Card data buffer
            //control word please check our company web site provides dynamic libraries
            myctrlword = BLOCK0_EN + BLOCK1_EN + BLOCK2_EN + EXTERNKEY;

            //sector
            myareano = 8;//sector is 8
            //authentication key Type
            authmode = 1;//>0 with A，default A

            //the Key
            mypicckey[0] = 0xff;
            mypicckey[1] = 0xff;
            mypicckey[2] = 0xff;
            mypicckey[3] = 0xff;
            mypicckey[4] = 0xff;
            mypicckey[5] = 0xff;

            textBox1.Text = "";
            status = piccreadex(myctrlword, mypiccserial, myareano, authmode, mypicckey, mypiccdata);
            //In the following set breakpoints, and then look at it  " mypiccserial、mypiccdata"
            //call piccreadex function can read ic serialNo to " mypiccserial"，card infomation into "mypiccdata"
            //Developers based on their own to deal with  " mypiccserial、mypiccdata" 
   
            switch (status)
            {
                case 0:
                    pcdbeep(38);
                    string ASCIIstr2 = null;
                    for (int i = 0; i < mypiccdata.Length; i++)
                        {
                            int asciicode = (int)(mypiccdata[i]);
                            ASCIIstr2 += Convert.ToChar(asciicode);//字符串ASCIIstr2 为对应的ASCII字符串
                        }
                    textBox1.Text = ASCIIstr2.Trim() ;
                    MessageBox.Show("Operation is successful, the data returned in mypiccdata array!", "Note:", MessageBoxButtons.OK, MessageBoxIcon.Asterisk);
                    break;
                //......
                case 8:
                    MessageBox.Show("Please put the card on the induction area", "Note:", MessageBoxButtons.OK, MessageBoxIcon.Stop );
                    break;
                default:
                    MessageBox.Show("Error Code:" + status, "warn",MessageBoxButtons.OK, MessageBoxIcon.Warning );
                    break;


            }
        }
    }
}
