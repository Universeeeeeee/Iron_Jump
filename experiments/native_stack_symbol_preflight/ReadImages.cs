// Consumes existing ETL only. Does not enable providers or attach to a process.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;

public unsafe class ReadImages
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
        [FieldOffset(86)] public ushort Length;
        [FieldOffset(96)] public IntPtr Data;
    }
    [StructLayout(LayoutKind.Explicit, Size = 448)]
    struct Logfile
    {
        [FieldOffset(0)] public IntPtr Filename;
        [FieldOffset(28)] public uint Mode;
        [FieldOffset(424)] public IntPtr Callback;
    }
    [UnmanagedFunctionPointer(CallingConvention.Winapi)] delegate void Callback(IntPtr p);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern ulong OpenTraceW(ref Logfile log);
    [DllImport("advapi32.dll")] static extern uint ProcessTrace(ulong[] handles, uint count, IntPtr a, IntPtr b);
    [DllImport("advapi32.dll")] static extern uint CloseTrace(ulong handle);
    static readonly Guid ProcessProvider = new Guid("3d6fa8d0-fe05-11d0-9dda-00c04fd7ba7c");
    static List<object> processes = new List<object>();
    static readonly Guid ImageProvider = new Guid("2cb15d1d-5fc1-11d2-abe1-00a0c911f518");
    static uint target;
    static Exception failure;
    static List<object> images = new List<object>();
    static Dictionary<string, int> shapes = new Dictionary<string, int>();
    static void Receive(IntPtr pointer)
    {
        if (failure != null) return;
        try
        {
            Record* e = (Record*)pointer;
            if (e->Provider == ProcessProvider && e->Version == 4 && (e->Flags & 0x40) != 0 && e->Length >= 24)
            {
                byte* data = (byte*)e->Data;
                uint processPid = *(uint*)(data + 8), parent = *(uint*)(data + 12);
                if (processPid == target || parent == target)
                    processes.Add(new {qpc=e->Time, opcode=e->Opcode, version=e->Version, pid=processPid, parent_pid=parent});
                return;
            }
            if (e->Provider != ImageProvider) return;
            string shape = e->Opcode + "/v" + e->Version + "/len" + e->Length;
            shapes[shape] = shapes.ContainsKey(shape) ? shapes[shape] + 1 : 1;
            // Classic x64 Image_Load v2/v3 stable layout: FileName at byte 56.
            // Unknown shapes remain counted, never silently decoded as this prefix.
            if ((e->Version != 2 && e->Version != 3) || (e->Flags & 0x40) == 0 || e->Length < 58) return;
            byte* p = (byte*)e->Data;
            uint pid = *(uint*)(p + 16);
            byte[] payload = new byte[e->Length];
            Marshal.Copy(e->Data, payload, 0, payload.Length);
            string name = Encoding.Unicode.GetString(payload, 56, payload.Length - 56).Split('\0')[0];
            bool vendor = name.IndexOf("obsbot", StringComparison.OrdinalIgnoreCase) >= 0 ||
                          name.EndsWith("libdev.dll", StringComparison.OrdinalIgnoreCase) ||
                          name.EndsWith("w32-pthreads.dll", StringComparison.OrdinalIgnoreCase);
            if (pid != target && !vendor) return;
            images.Add(new {qpc=e->Time, opcode=e->Opcode, version=e->Version, flags=e->Flags, pid=pid,
                           image_base=*(ulong*)p, image_size=*(ulong*)(p+8), checksum=*(uint*)(p+20),
                           timestamp=*(uint*)(p+24), filename=name, payload_base64=Convert.ToBase64String(payload)});
        }
        catch (Exception error) { failure = error; }
    }
    public static int Main(string[] args)
    {
        if (args.Length != 3) throw new Exception("ReadImages existing.etl target-pid new-output.json");
        if (File.Exists(args[2])) throw new Exception("Output exists");
        target = uint.Parse(args[1]);
        Callback callback = Receive;
        Logfile file = new Logfile {Filename=Marshal.StringToHGlobalUni(args[0]), Mode=0x10001000,
                                    Callback=Marshal.GetFunctionPointerForDelegate(callback)};
        ulong trace = OpenTraceW(ref file);
        if (trace == ulong.MaxValue) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        uint result;
        try { result = ProcessTrace(new ulong[]{trace}, 1, IntPtr.Zero, IntPtr.Zero); }
        finally { CloseTrace(trace); Marshal.FreeHGlobal(file.Filename); GC.KeepAlive(callback); }
        if (failure != null) throw failure;
        if (result != 0) throw new Exception("ProcessTrace " + result);
        var json = new JavaScriptSerializer {MaxJsonLength=int.MaxValue};
        File.WriteAllText(args[2], json.Serialize(new {target_pid=target, shapes=shapes, images=images, related_processes=processes,
                          scope="Existing trace Image_Load v2/v3 x64 stable prefix only; no stacks or profiling created."}), new UTF8Encoding(false));
        Console.WriteLine("IMAGE_RECORDS " + images.Count);
        return 0;
    }
}
