using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;

internal static class AskpassProbe
{
    private static int Main(string[] arguments)
    {
        string prompt = string.Join(" ", arguments ?? new string[0]);
        string kind = Classify(prompt);
        string logPath = Environment.GetEnvironmentVariable("SERVEROPS_ASKPASS_LOG");
        if (string.IsNullOrEmpty(logPath))
        {
            return 2;
        }

        string digest;
        using (SHA256 sha256 = SHA256.Create())
        {
            byte[] bytes = Encoding.UTF8.GetBytes(prompt);
            digest = BitConverter.ToString(sha256.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }
        File.AppendAllText(
            logPath,
            kind + "\t" + prompt.Length.ToString() + "\t" + digest + Environment.NewLine,
            new UTF8Encoding(false)
        );

        string response;
        if (kind == "host_key")
        {
            response = "yes";
        }
        else if (kind == "password")
        {
            response = Environment.GetEnvironmentVariable("SERVEROPS_ASKPASS_PASSWORD");
        }
        else if (kind == "key_passphrase")
        {
            response = Environment.GetEnvironmentVariable("SERVEROPS_ASKPASS_KEY_PASSPHRASE");
        }
        else
        {
            return 3;
        }
        if (response == null || response.IndexOfAny(new[] { '\r', '\n' }) >= 0)
        {
            return 4;
        }
        Console.Out.WriteLine(response);
        return 0;
    }

    private static string Classify(string prompt)
    {
        string value = prompt.ToLowerInvariant();
        if (value.Contains("continue connecting") || value.Contains("authenticity of host"))
        {
            return "host_key";
        }
        if (value.Contains("passphrase") && value.Contains("key"))
        {
            return "key_passphrase";
        }
        if (value.Contains("password"))
        {
            return "password";
        }
        return "unknown";
    }
}

