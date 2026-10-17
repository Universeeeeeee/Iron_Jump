// Offline ETL reader only. No providers, sessions, devices or target processes are started.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Web.Script.Serialization;

public unsafe class ReadSchedule
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
    static Dictionary<string, long> counts = new Dictionary<string, long>();
    static Dictionary<string, object> examples = new Dictionary<string, object>();
    static List<Dictionary<string, object>> samples = new List<Dictionary<string, object>>();
    static BinaryWriter writer;
    static StreamWriter lifecycle;
    static long ordinal, rawCount;
    static bool raw;
    static Exception failure;
    static byte[] zero = new byte[24];

    static string Hex(byte[] bytes) { return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant(); }
    static string Sha(string path)
    {
        using (var hash = SHA256.Create())
        using (var stream = File.OpenRead(path)) return Hex(hash.ComputeHash(stream));
    }
    static void Receive(IntPtr pointer)
    {
        if (failure != null) return;
        try
        {
            Record* e = (Record*)pointer;
            if (e->Provider != ThreadProvider) return;
            byte* p = (byte*)e->Data;
            if (e->Opcode == 36 || e->Opcode == 50)
            {
                string shape = e->Opcode + "/v" + e->Version + "/len" + e->Length;
                if (raw)
                {
                    if (!counts.ContainsKey(shape))
                    {
                        counts[shape] = 0;
                        var bytes = new byte[e->Length];
                        Marshal.Copy(e->Data, bytes, 0, bytes.Length);
                        examples[shape] = new Dictionary<string, object> {
                            {"payload_hex", Hex(bytes)}, {"header_flags", e->Flags}
                        };
                    }
                    counts[shape]++;
                    if ((e->Opcode == 36 && (e->Version < 2 || e->Length < 24)) ||
                        (e->Opcode == 50 && e->Length != 8)) throw new Exception("Unsupported payload " + shape);
                    writer.Write(e->Time); writer.Write(e->Cpu);
                    writer.Write(e->Opcode); writer.Write(e->Version);
                    writer.Write(e->Tid); writer.Write(e->Pid);
                    int length = Math.Min(24, (int)e->Length);
                    for (int i = 0; i < length; i++) writer.Write(p[i]);
                    if (length < 24) writer.Write(zero, 0, 24 - length);
                    writer.Write(e->Length); writer.Write(e->Flags);
                }
                if (ordinal % 10000 == 0)
                {
                    if (raw) samples.Add(new Dictionary<string, object> {
                        {"ordinal", ordinal}, {"qpc", e->Time}, {"cpu", e->Cpu},
                        {"opcode", e->Opcode}, {"first_u32", *(uint*)p}, {"second_u32", *(uint*)(p+4)}
                    });
                    else
                    {
                        var s = samples[(int)(ordinal / 10000)];
                        if (Convert.ToInt64(s["ordinal"]) != ordinal ||
                            Convert.ToUInt16(s["cpu"]) != e->Cpu ||
                            Convert.ToByte(s["opcode"]) != e->Opcode ||
                            Convert.ToUInt32(s["first_u32"]) != *(uint*)p ||
                            Convert.ToUInt32(s["second_u32"]) != *(uint*)(p+4))
                            throw new Exception("Raw/converted event ordering mismatch");
                        s["utc_filetime_100ns"] = e->Time;
                    }
                }
                ordinal++;
            }
            else if (raw && e->Opcode >= 1 && e->Opcode <= 4 && e->Version >= 1 && e->Length >= 8)
            {
                lifecycle.WriteLine(e->Time + "," + e->Opcode + "," + e->Version + "," + *(uint*)p + "," + *(uint*)(p+4));
            }
        }
        catch (Exception ex) { failure = ex; }
    }
    static Logfile Read(string path, bool useRaw)
    {
        raw = useRaw; ordinal = 0;
        Callback callback = Receive;
        var log = new Logfile {
            Filename = Marshal.StringToHGlobalUni(path),
            Mode = 0x10000000U | (useRaw ? 0x1000U : 0U), // EVENT_RECORD | RAW_TIMESTAMP
            Callback = Marshal.GetFunctionPointerForDelegate(callback)
        };
        ulong handle = OpenTraceW(ref log);
        if (handle == UInt64.MaxValue) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            uint code = ProcessTrace(new ulong[] { handle }, 1, IntPtr.Zero, IntPtr.Zero);
            if (code != 0) throw new Exception("ProcessTrace " + code);
            if (failure != null) throw failure;
        }
        finally
        {
            CloseTrace(handle); Marshal.FreeHGlobal(log.Filename); GC.KeepAlive(callback);
        }
        if (useRaw) rawCount = ordinal;
        else if (ordinal != rawCount) throw new Exception("Pass counts differ");
        return log;
    }
    public static int Main(string[] args)
    {
        if (IntPtr.Size != 8 || args.Length != 2) throw new Exception("Use x64 reader: ETL new-output-directory");
        string input = args[0], output = args[1];
        if (Directory.Exists(output)) throw new Exception("Preserve existing output");
        Directory.CreateDirectory(output);
        Logfile header;
        using (writer = new BinaryWriter(File.Create(Path.Combine(output, "schedule.bin"))))
        using (lifecycle = new StreamWriter(Path.Combine(output, "thread_lifecycle.csv")))
        {
            lifecycle.WriteLine("qpc,opcode,version,pid,tid");
            header = Read(input, true);
        }
        Read(input, false); // independent Windows timestamp conversion, same events
        var meta = new Dictionary<string, object> {
            {"source_etl_sha256", Sha(input)}, {"source_etl_bytes", new FileInfo(input).Length},
            {"binary_sha256", Sha(Path.Combine(output, "schedule.bin"))},
            {"record_bytes", 48}, {"record_format", "<qHBBII24sHH"},
            {"event_count", rawCount}, {"payload_shapes", counts}, {"payload_examples", examples},
            {"qpc_frequency", header.Frequency}, {"clock_type", header.ClockType},
            {"trace_start_filetime_100ns", header.StartTime}, {"trace_end_filetime_100ns", header.EndTime},
            {"header_events_lost", header.HeaderEventsLost}, {"buffers_lost", header.BuffersLost},
            {"consumer_events_lost", header.ConsumerEventsLost}, {"clock_samples", samples},
            {"scope", "Read-only ETL consumption; fixed classic CSwitch >=v2 prefix and 8-byte ReadyThread. Clock and thread CPU validation required before interpretation."}
        };
        File.WriteAllText(Path.Combine(output, "metadata.json"), new JavaScriptSerializer().Serialize(meta));
        Console.WriteLine("Read " + rawCount + " scheduling events, " + samples.Count + " clock samples");
        return 0;
    }
}
