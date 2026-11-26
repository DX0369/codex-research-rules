using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

static class CodexVsCode
{
    [StructLayout(LayoutKind.Sequential)]
    struct StartupInfo
    {
        public int Size;
        public IntPtr Reserved, Desktop, Title;
        public int X, Y, Width, Height, Columns, Lines, FillAttribute, Flags;
        public short ShowWindow, ReservedBytes;
        public IntPtr ReservedBuffer, Input, Output, Error;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct ProcessInfo
    {
        public IntPtr Process, Thread;
        public int ProcessId, ThreadId;
    }

    [DllImport("kernel32.dll")]
    static extern IntPtr GetStdHandle(int handle);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CreateProcessW(string application, StringBuilder command,
        IntPtr processAttributes, IntPtr threadAttributes, bool inheritHandles, uint flags,
        IntPtr environment, string directory, ref StartupInfo startup, out ProcessInfo process);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern uint WaitForSingleObject(IntPtr handle, uint timeout);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetExitCodeProcess(IntPtr process, out uint code);

    [DllImport("kernel32.dll")]
    static extern bool CloseHandle(IntPtr handle);

    static string OnPath(string directory)
    {
        directory = directory.Trim().Trim('"');
        if (directory.Length == 0)
            return null;
        string candidate = Path.Combine(directory, "codex.exe");
        return File.Exists(candidate) ? candidate : null;
    }

    static string FindCodex()
    {
        string[] directories = (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';');
        // The extension appends its bundled binary directory when spawning Codex.
        string bundled = OnPath(directories[directories.Length - 1]);
        if (bundled != null)
            return bundled;

        foreach (string directory in directories)
        {
            string candidate = OnPath(directory);
            if (candidate != null)
                return candidate;
        }
        return null;
    }

    static string QuoteArgument(string argument)
    {
        var quoted = new StringBuilder("\"");
        int backslashes = 0;
        foreach (char ch in argument)
        {
            if (ch == '\\')
            {
                backslashes++;
                continue;
            }
            quoted.Append('\\', ch == '"' ? backslashes * 2 + 1 : backslashes);
            quoted.Append(ch);
            backslashes = 0;
        }
        return quoted.Append('\\', backslashes * 2).Append('"').ToString();
    }

    static int Main(string[] args)
    {
        try
        {
            string executable = FindCodex();
            if (executable == null)
            {
                Console.Error.WriteLine("codex-vscode: codex.exe was not found on PATH");
                return 127;
            }
            // Preserve the editor's JSONL pipes even when the child has no console.
            var start = new StartupInfo
            {
                Size = Marshal.SizeOf(typeof(StartupInfo)),
                Flags = 0x100, // STARTF_USESTDHANDLES
                Input = GetStdHandle(-10),
                Output = GetStdHandle(-11),
                Error = GetStdHandle(-12)
            };
            var command = new StringBuilder(QuoteArgument(executable));
            foreach (var argument in args)
                command.Append(' ').Append(QuoteArgument(argument));
            ProcessInfo child;
            if (!CreateProcessW(executable, command, IntPtr.Zero, IntPtr.Zero, true,
                    0x08000000, IntPtr.Zero, null, ref start, out child)) // CREATE_NO_WINDOW
                throw new Win32Exception(Marshal.GetLastWin32Error());
            CloseHandle(child.Thread);
            try
            {
                uint code;
                if (WaitForSingleObject(child.Process, uint.MaxValue) != 0
                    || !GetExitCodeProcess(child.Process, out code))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                return unchecked((int)code);
            }
            finally
            {
                CloseHandle(child.Process);
            }
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("codex-vscode: " + error.Message);
            return 1;
        }
    }
}
