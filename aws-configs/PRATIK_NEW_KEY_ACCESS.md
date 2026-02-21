# Pratik - New Key Access Instructions

## Instance Details

- **Instance Name**: liquidation_papertrading
- **Instance ID**: i-0b31e9a3c6ad62814
- **IP Address**: 13.236.143.201 (Elastic IP - Permanent)
- **Region**: ap-southeast-2 (Sydney)
- **Username**: ubuntu
- **Instance Type**: t3.micro (2 vCPUs, 1 GB RAM)
- **Disk Size**: 16 GB (recently increased from 8 GB)
- **Security Group**: sg-0cc48b5c62610eeb2 (launch-wizard-16)
- **✅ Security Group Updated**: IP 42.104.216.118/32 added for SSH access
- **✅ Elastic IP Assigned**: IP is now permanent (won't change on restart)

## Files to Share

1. **pratik-key-new.pem** - SSH private key (this file)
2. **PRATIK_NEW_KEY_ACCESS.md** - This documentation

---

## ✅ Public Key Status

**Good News!** The public key has already been added to the instance. You can use the key immediately after setting file permissions on your Windows machine.

---

## Ready to Connect

### ✅ PRIMARY METHOD: SSH Connection (WORKING!)

**SSH is now fully functional! Use this command:**

```bash
ssh -i pratik-key-new.pem ubuntu@13.236.143.201
```

**Connection Details:**

- **IP Address**: 13.236.143.201 (Elastic IP - Permanent)
- **Username**: ubuntu
- **Port**: 22 (SSH)
- **Key File**: pratik-key-new.pem

**Both authentication methods work:**

- ✅ SSH key authentication (recommended)
- ✅ Password authentication (for WinSCP)

---

### 🔧 Alternative: EC2 Instance Connect (If SSH is Blocked by Network)

**If your network blocks SSH (port 22), use EC2 Instance Connect instead:**

**Step-by-Step:**

1. **Direct Link**: <https://console.aws.amazon.com/ec2/v2/home?region=ap-southeast-2#Instances:instanceId=i-0b31e9a3c6ad62814>

2. Or manually:
   - Go to: AWS Console → EC2 → Instances
   - Find instance: `liquidation_papertrading` (or search IP: 13.236.143.201)
   - Select the instance → Click **"Connect"** button (top right)
   - Choose **"EC2 Instance Connect"** tab
   - Click **"Connect"**

3. **Browser terminal opens** - Full Linux shell access!

**Why This Works:**

- Uses HTTPS (port 443) - rarely blocked by networks
- Browser-based - no SSH client needed
- Bypasses all network SSH restrictions

### Windows Users - Key File Setup

#### Step 1: Fix Line Endings (if needed)

The key file should have Unix line endings (LF). If you get "invalid format" errors:

**Option A: Using PowerShell (Run as Administrator if needed)**

```powershell
$content = Get-Content pratik-key-new.pem -Raw
$content = $content -replace "`r`n", "`n" -replace "`r", "`n"
[System.IO.File]::WriteAllText("$PWD\pratik-key-new.pem", $content, [System.Text.Encoding]::ASCII)
```

**Option B: Using Notepad++**

1. Open `pratik-key-new.pem` in Notepad++
2. Edit → EOL Conversion → Unix (LF)
3. Save

#### Step 2: Set File Permissions

Windows requires proper permissions on the key file:

**Option A: Using PowerShell (Run as Administrator)**

```powershell
icacls pratik-key-new.pem /inheritance:r
icacls pratik-key-new.pem /grant:r "$env:USERNAME:(R)"
```

**Option B: Using File Properties**

1. Right-click `pratik-key-new.pem` → Properties
2. Security tab → Advanced
3. Disable inheritance → Remove all permissions
4. Add → Select your user → Allow "Read" → OK
5. Apply → OK

---

## Troubleshooting

### "Permission denied (publickey)"

- Ensure the public key was added to `~/.ssh/authorized_keys` on the instance
- Check key file permissions (should be readable only by you)
- Verify you're using the correct username (`ubuntu`)

### "Load key: invalid format"

- Fix line endings (see Windows Users section above)
- Ensure the file starts with `-----BEGIN RSA PRIVATE KEY-----`

### "SSH Hanging" or "Connection timed out"

**If SSH hangs or times out, it's likely network blocking (your router/firewall blocking port 22).**

**✅ SOLUTION: Use EC2 Instance Connect (Works from ANY network!)**

1. **Direct Link**: <https://console.aws.amazon.com/ec2/v2/home?region=ap-southeast-2#Instances:instanceId=i-0b31e9a3c6ad62814>
2. Or: AWS Console → EC2 → Instances → Find `liquidation_papertrading`
3. Click **"Connect"** → **"EC2 Instance Connect"** → **"Connect"**
4. Browser terminal opens - **full Linux shell access!**

**Why EC2 Instance Connect Works:**

- ✅ Uses HTTPS (port 443) - rarely blocked
- ✅ Browser-based - no SSH client needed
- ✅ Bypasses all network restrictions
- ✅ Works from any network, any time

**Alternative Solutions:**

- Use mobile hotspot to bypass network restrictions (for testing)
- Contact IT department if on corporate network to whitelist SSH
- Try from a different network/location

---

## Quick Test

After adding the public key, test the connection:

```bash
ssh -i pratik-key-new.pem ubuntu@13.236.143.201 "echo 'Connection successful!' && whoami && hostname"
```

---

## Summary

1. ✅ New key pair created: `pratik-key-new`
2. ✅ **Public key already added to instance** - Ready to use!
3. ✅ **SSH is working** - Both key and password authentication enabled
4. ✅ Use `pratik-key-new.pem` for SSH access
5. ✅ Instance IP: **13.236.143.201** (Elastic IP - Permanent)
6. ✅ Disk resized: 8 GB → 16 GB (backup snapshot: snap-052ac4c7fceee2ada)
7. ✅ Elastic IP assigned: IP will NOT change on restart
8. ✅ WinSCP password authentication enabled
9. ⚠️ **ACTION REQUIRED**: Set file permissions on Windows (see instructions above)
10. ⚠️ **IMPORTANT**: After connecting, extend filesystem to use full 16GB (if not done already):

   ```bash
   sudo growpart /dev/nvme0n1 1
   sudo resize2fs /dev/nvme0n1p1
   df -h  # Verify new size
   ```
