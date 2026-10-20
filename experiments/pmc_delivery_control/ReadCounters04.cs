// Offline only: retain CSwitch counter attachments and source configuration bytes.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
public unsafe class ReadCounters04 {
    [StructLayout(LayoutKind.Explicit,Size=112)] struct Record {
        [FieldOffset(4)] public ushort Flags;
        [FieldOffset(8)] public uint Tid;
        [FieldOffset(12)] public uint Pid;
        [FieldOffset(16)] public long Time;
        [FieldOffset(24)] public Guid Provider;
        [FieldOffset(42)] public byte Version;
        [FieldOffset(45)] public byte Opcode;
        [FieldOffset(80)] public ushort Cpu;
        [FieldOffset(84)] public ushort ExtCount;
        [FieldOffset(86)] public ushort Length;
        [FieldOffset(88)] public IntPtr Extended;
        [FieldOffset(96)] public IntPtr Data;
    }
    [StructLayout(LayoutKind.Explicit,Size=16)] struct ExtendedItem {
        [FieldOffset(2)] public ushort Type;
        [FieldOffset(6)] public ushort Size;
        [FieldOffset(8)] public ulong Data;
    }
    [StructLayout(LayoutKind.Explicit,Size=448)] struct Logfile {
        [FieldOffset(0)] public IntPtr Filename;
        [FieldOffset(28)] public uint Mode;
        [FieldOffset(168)] public uint HeaderEventsLost;
        [FieldOffset(376)] public long Frequency;
        [FieldOffset(384)] public long StartTime;
        [FieldOffset(392)] public uint ClockType;
        [FieldOffset(396)] public uint BuffersLost;
        [FieldOffset(416)] public uint ConsumerEventsLost;
        [FieldOffset(424)] public IntPtr Callback;
    }
    [UnmanagedFunctionPointer(CallingConvention.Winapi)] delegate void Callback(IntPtr p);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern ulong OpenTraceW(ref Logfile l);
    [DllImport("advapi32.dll")] static extern uint ProcessTrace(ulong[] h,uint n,IntPtr a,IntPtr b);
    [DllImport("advapi32.dll")] static extern uint CloseTrace(ulong h);
    static JavaScriptSerializer json=new JavaScriptSerializer{MaxJsonLength=int.MaxValue};
    static Dictionary<string,long> shapes=new Dictionary<string,long>();
    static Dictionary<string,string> examples=new Dictionary<string,string>();
    static Dictionary<string,long> extendedTypes=new Dictionary<string,long>();
    static Guid thread=new Guid("3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c");
    static Guid perf=new Guid("ce1dbfb4-137e-4da6-87b0-3f59aa102cbc");
    static StreamWriter writer;
    static Exception failure;
    static long count;
    static void Receive(IntPtr pointer) {
        if(failure!=null)return;
        try {
            Record* e=(Record*)pointer;
            string shape=e->Provider+"/"+e->Opcode+"/v"+e->Version+"/len"+e->Length;
            shapes[shape]=shapes.ContainsKey(shape)?shapes[shape]+1:1;
            if(!examples.ContainsKey(shape)) {
                byte[] example=new byte[Math.Min(512,(int)e->Length)];if(example.Length>0)Marshal.Copy(e->Data,example,0,example.Length);
                examples[shape]=Convert.ToBase64String(example);
            }
            List<object> items=new List<object>();
            for(int i=0;i<e->ExtCount;i++) {
                ExtendedItem* item=(ExtendedItem*)e->Extended+i;
                extendedTypes[item->Type.ToString()]=extendedTypes.ContainsKey(item->Type.ToString())?extendedTypes[item->Type.ToString()]+1:1;
                byte[] bytes=new byte[item->Size];if(bytes.Length>0)Marshal.Copy((IntPtr)item->Data,bytes,0,bytes.Length);
                // EVENT_HEADER_EXT_TYPE_PMC_COUNTERS = 0x0008, raw64 values.
                if(item->Type==8) {
                    if(item->Size%8!=0)throw new Exception("Invalid PMC attachment size");
                    ulong[] values=new ulong[item->Size/8];for(int j=0;j<values.Length;j++)values[j]=BitConverter.ToUInt64(bytes,8*j);
                    items.Add(new{type=item->Type,size=item->Size,values=values,raw=Convert.ToBase64String(bytes)});
                }
            }
            bool keep=(e->Provider==thread)||(e->Provider==perf)||items.Count>0;
            if(!keep)return;
            byte[] payload=new byte[e->Length];if(payload.Length>0)Marshal.Copy(e->Data,payload,0,payload.Length);
            writer.WriteLine(json.Serialize(new{qpc=e->Time,cpu=e->Cpu,pid=e->Pid,tid=e->Tid,flags=e->Flags,provider=e->Provider.ToString(),opcode=e->Opcode,version=e->Version,pmc=items,payload=Convert.ToBase64String(payload)}));
            count++;
        }catch(Exception error){failure=error;}
    }
    public static int Main(string[] args) {
        try{return Run(args);}catch(Exception e){
            File.WriteAllText(Path.Combine(args[1],"failure_type.txt"),e.GetType().FullName);
            File.WriteAllText(Path.Combine(args[1],"failure_message.txt"),e.Message);
            File.WriteAllText(Path.Combine(args[1],"failure_stack.txt"),e.StackTrace);
            return 2;
        }
    }
    public static int Run(string[] args) {
        if(args.Length!=2||IntPtr.Size!=8)throw new Exception("existing.etl new-output-dir (x64)");
        if(Directory.Exists(args[1]))throw new Exception("Preserve decoder output");Directory.CreateDirectory(args[1]);
        Callback callback=Receive;
        var log=new Logfile{Filename=Marshal.StringToHGlobalUni(args[0]),Mode=0x10001000U,Callback=Marshal.GetFunctionPointerForDelegate(callback)};
        ulong handle=OpenTraceW(ref log);if(handle==ulong.MaxValue)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        try {
            using(writer=new StreamWriter(Path.Combine(args[1],"events.jsonl"))) {
                uint code=ProcessTrace(new ulong[]{handle},1,IntPtr.Zero,IntPtr.Zero);
                if(code!=0)throw new Exception("ProcessTrace "+code);if(failure!=null)throw failure;
            }
        }finally{CloseTrace(handle);Marshal.FreeHGlobal(log.Filename);GC.KeepAlive(callback);}
        File.WriteAllText(Path.Combine(args[1],"reached_metadata.txt"),"events complete");
        File.WriteAllText(Path.Combine(args[1],"metadata.json"),json.Serialize(new{selected=count,shapes=shapes,examples=examples,extended_types=extendedTypes,qpc_frequency=log.Frequency,clock_type=log.ClockType,trace_start_filetime_100ns=log.StartTime,header_events_lost=log.HeaderEventsLost,buffers_lost=log.BuffersLost,consumer_events_lost=log.ConsumerEventsLost}));
        Console.WriteLine("Decoded "+count);return 0;
    }
}
