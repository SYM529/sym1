$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class CredMan2 {
  [DllImport("advapi32.dll", EntryPoint="CredReadW", CharSet=CharSet.Unicode, SetLastError=true)]
  static extern bool CredRead(string target, int type, int reserved, out IntPtr credPtr);

  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  struct CREDENTIAL {
    public int Flags;
    public int Type;
    public string TargetName;
    public string Comment;
    public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
    public int CredentialBlobSize;
    public IntPtr CredentialBlob;
    public int Persist;
    public int AttributeCount;
    public IntPtr Attributes;
    public string TargetAlias;
    public string UserName;
  }

  public static string GetSecret(string target) {
    IntPtr ptr;
    if (!CredRead(target, 1, 0, out ptr)) return null;
    CREDENTIAL c = (CREDENTIAL)Marshal.PtrToStructure(ptr, typeof(CREDENTIAL));
    byte[] buf = new byte[c.CredentialBlobSize];
    Marshal.Copy(c.CredentialBlob, buf, 0, c.CredentialBlobSize);
    string s = System.Text.Encoding.UTF8.GetString(buf).Replace("\0", "");
    if (s.Length == 0 || s[0] > 0x7F) s = System.Text.Encoding.Unicode.GetString(buf).Replace("\0", "");
    return s.Trim();
  }
}
"@

$token = [CredMan2]::GetSecret("git:https://github.com")
if (-not $token) { Write-Host "FAIL no cred"; exit 1 }
Write-Host "OK cred loaded (len $($token.Length), hidden)"

$headers = @{
  Authorization = "Bearer $token"
  Accept        = "application/vnd.github+json"
  "User-Agent"  = "sym-resume"
}

# 描述用英文标点 + 中文，整体以 UTF-8 字节发送
$descJson = '{"description":"LLM Agent 服务：LangChain + FastAPI + Vue3，混合检索 RAG 带引用溯源，ReAct 双架构实测择优（98.5% vs 89.7%），语义缓存零误命中，158 条评测 + CI 回归门禁，Docker 公网部署"}'

try {
  $r1 = Invoke-RestMethod -Method Patch -Uri "https://api.github.com/repos/SYM529/myAgent" `
    -Headers $headers -Body ([System.Text.Encoding]::UTF8.GetBytes($descJson)) `
    -ContentType "application/json; charset=utf-8"
  Write-Host "OK desc: $($r1.description)"
} catch {
  Write-Host "FAIL desc: $($_.Exception.Message)"
}
