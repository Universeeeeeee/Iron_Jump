SET CLASSPATH=.

cd /d "%~dp0"
"%JAVA_HOME%\bin\java.exe" com.icmcu.test 1

::输入1表示读卡的序列号4个字节，2嘀一声，3轻松读卡指令piccreadex，4轻松写卡指令piccwriteex，5改单区密码piccchangesinglekey，6改单区密码-扩展指令piccchangesinglekeyex
pause