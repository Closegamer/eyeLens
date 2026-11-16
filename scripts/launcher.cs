// Build with scripts/build_launcher.ps1.
// Starts run.bat from this executable's own folder, so the launcher works
// from any extraction path and stores no absolute paths.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

internal static class Program
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBox(IntPtr owner, string text, string caption, uint type);

    [STAThread]
    private static void Main()
    {
        string dir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string bat = Path.Combine(dir, "run.bat");
        if (!File.Exists(bat))
        {
            MessageBox(IntPtr.Zero, "run.bat was not found next to this launcher.",
                "eyeLens", 0x10);
            return;
        }

        // First run installs the virtual environment; let the user watch that.
        bool venvReady = File.Exists(Path.Combine(dir, @".venv\Scripts\python.exe"));
        Process.Start(new ProcessStartInfo
        {
            FileName = bat,
            WorkingDirectory = dir,
            UseShellExecute = true,
            WindowStyle = venvReady ? ProcessWindowStyle.Minimized : ProcessWindowStyle.Normal
        });
    }
}
