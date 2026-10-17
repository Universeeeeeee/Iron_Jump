// Offline ETL reader only. No providers, sessions, devices or target processes are started.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Web.Script.Serialization;

public unsafe class ReadStacks
{
    [StructLayout(LayoutKind.Explicit, Size = 112)]
    struct Record
    {
        [FieldOffset(4)] public ushort Flags;
        [FieldOffset(8)] public uint Tid;
        [FieldOffset(12)] public uint Pid;
        [FieldOffset(16)] public long Time;
        [FieldOffset(24)] public Guid Provider;
        [FieldOffset(42)] public byte Version;
        [FieldOffset(45)] public byte Opcode;
        [FieldOffset(80)] public ushort Cpu;
        [FieldOffset(86)] public ushort Length;
        [FieldOffset(96)] public IntPtr Data;
    }
    // x64 EVENT_TRACE_LOGFILEW from evntrace.h: CurrentEvent at 32 (88 bytes),
    // TRACE_LOGFILE_HEADER at 120 (280 bytes), EventRecordCallback at 424.
    [StructLayout(LayoutKind.Explicit, Size = 448)]
    struct Logfile
    {
        [FieldOffset(0)] public IntPtr Filename;
        [FieldOffset(28)] public uint Mode;
        [FieldOffset(136)] public long EndTime;
        [FieldOffset(168)] public uint HeaderEventsLost;
        [FieldOffset(376)] public long Frequency;
        [FieldOffset(384)] public long StartTime;
        [FieldOffset(392)] public uint ClockType;
        [FieldOffset(396)] public uint BuffersLost;
        [FieldOffset(416)] public uint ConsumerEventsLost;
        [FieldOffset(424)] public IntPtr Callback;
    }
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]
    delegate void Callback(IntPtr p);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern ulong OpenTraceW(ref Logfile log);
    [DllImport("advapi32.dll")]
    static extern uint ProcessTrace(ulong[] handles, uint count, IntPtr begin, IntPtr end);
    [DllImport("advapi32.dll")]
    static extern uint CloseTrace(ulong handle);

    static readonly Guid ThreadProvider = new Guid("3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c");
    static readonly Guid ProfileProvider = new Guid("ce1dbfb4-137e-4da6-87b0-3f59aa102cbc");
    static readonly Guid StackProvider = new Guid("def2fe46-7bd6-4b80-bd94-f57fe20d0ce3");
    static readonly Guid ImageProvider = new Guid("2cb15d1d-5fc1-11d2-abe1-00a0c911f518");
    static readonly Guid ProcessProvider = new Guid("3d6fa8d0-fe05-11d0-9dda-00c04fd7ba7c");
    static uint target;
    static HashSet<uint> tids = new HashSet<uint>();
    static Dictionary<string,long> shapes = new Dictionary<string,long>();
    static Dictionary<string,string> examples = new Dictionary<string,string>();
    static JavaScriptSerializer json = new JavaScriptSerializer {MaxJsonLength=int.MaxValue};
    static List<object> clocks = new List<object>();
    static StreamWriter writer;
    static Exception failure;
    static bool raw;
    static long selected, ordinal;
    static void Receive(IntPtr pointer)
    {
        if (failure != null) return;
        try
        {
            Record* e = (Record*)pointer;
            byte* p = (byte*)e->Data;
            bool stack=e->Provider==StackProvider, profile=e->Provider==ProfileProvider,
                 thread=e->Provider==ThreadProvider, image=e->Provider==ImageProvider,
                 process=e->Provider==ProcessProvider;
            if (!stack && !profile && !thread && !image && !process) return;
            string shape=e->Provider+"/"+e->Opcode+"/v"+e->Version+"/len"+e->Length;
            if (raw) {
                shapes[shape]=shapes.ContainsKey(shape)?shapes[shape]+1:1;
                if(!examples.ContainsKey(shape)) {
                    byte[] example=new byte[e->Length]; Marshal.Copy(e->Data,example,0,example.Length);
                    examples[shape]=Convert.ToBase64String(example);
                }
            }
            bool keep=false;
            if(stack && e->Opcode==32 && e->Length>=16) keep=*(uint*)(p+8)==target;
            else if(profile && e->Opcode==46 && e->Length>=16 && (e->Flags&0x40)!=0) keep=tids.Contains(*(uint*)(p+8));
            else if(profile && e->Opcode!=46) keep=true; // interval changes/rundown, shapes retained
            else if(thread && e->Opcode==36 && e->Length>=24) keep=tids.Contains(*(uint*)p)||tids.Contains(*(uint*)(p+4));
            else if(thread && e->Opcode==50 && e->Length==8) keep=tids.Contains(*(uint*)p);
            else if(thread && e->Opcode>=1 && e->Opcode<=4 && e->Length>=8) keep=*(uint*)p==target;
            else if(image && (e->Version==2||e->Version==3) && e->Length>=58 && (e->Flags&0x40)!=0)
                keep=*(uint*)(p+16)==target || *(uint*)(p+16)==0 || *(uint*)(p+16)==4;
            else if(process && e->Version==4 && e->Length>=24 && (e->Flags&0x40)!=0)
                keep=*(uint*)(p+8)==target || *(uint*)(p+12)==target;
            if(!keep) return;
            if(ordinal%100==0) {
                if(raw) clocks.Add(new Dictionary<string,object>{{"ordinal",ordinal},{"qpc",e->Time},{"provider",e->Provider.ToString()},{"opcode",e->Opcode}});
                else {
                    var clock=(Dictionary<string,object>)clocks[(int)(ordinal/100)];
                    if((string)clock["provider"]!=e->Provider.ToString() || Convert.ToByte(clock["opcode"])!=e->Opcode) throw new Exception("Clock pass mismatch");
                    clock["filetime_100ns"]=e->Time;
                }
            }
            ordinal++;
            if(!raw) return;
            byte[] payload=new byte[e->Length]; Marshal.Copy(e->Data,payload,0,payload.Length);
            writer.WriteLine(json.Serialize(new {qpc=e->Time,cpu=e->Cpu,header_pid=e->Pid,header_tid=e->Tid,
                flags=e->Flags,provider=e->Provider.ToString(),opcode=e->Opcode,version=e->Version,payload=Convert.ToBase64String(payload)}));
        }
        catch(Exception error) {failure=error;}
    }
    static Logfile Read(string path,bool rawMode) {
        raw=rawMode; ordinal=0;
        Callback callback=Receive;
        var log=new Logfile {Filename=Marshal.StringToHGlobalUni(path),Mode=0x10000000U|(raw?0x1000U:0U),Callback=Marshal.GetFunctionPointerForDelegate(callback)};
        ulong handle=OpenTraceW(ref log);
        if(handle==ulong.MaxValue) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        try {
            uint code=ProcessTrace(new ulong[]{handle},1,IntPtr.Zero,IntPtr.Zero);
            if(code!=0) throw new Exception("ProcessTrace "+code);
            if(failure!=null) throw failure;
        } finally {CloseTrace(handle);Marshal.FreeHGlobal(log.Filename);GC.KeepAlive(callback);}
        if(raw) selected=ordinal;
        else if(ordinal!=selected) throw new Exception("Pass count mismatch");
        return log;
    }
    public static int Main(string[] args) {
        if(IntPtr.Size!=8||args.Length!=4) throw new Exception("existing.etl pid tid,tid,... new-output-directory");
        target=uint.Parse(args[1]); foreach(string tid in args[2].Split(',')) tids.Add(uint.Parse(tid));
        if(Directory.Exists(args[3])) throw new Exception("Preserve output");
        Directory.CreateDirectory(args[3]);
        Logfile h;
        using(writer=new StreamWriter(Path.Combine(args[3],"events.jsonl"))) h=Read(args[0],true);
        Read(args[0],false);
        File.WriteAllText(Path.Combine(args[3],"metadata.json"),json.Serialize(new {
            target_pid=target,event_count=selected,shapes=shapes,examples=examples,clock_samples=clocks,
            qpc_frequency=h.Frequency,clock_type=h.ClockType,trace_start_filetime_100ns=h.StartTime,
            header_events_lost=h.HeaderEventsLost,buffers_lost=h.BuffersLost,consumer_events_lost=h.ConsumerEventsLost}));
        Console.WriteLine("Selected "+selected);
        return 0;
    }
}
