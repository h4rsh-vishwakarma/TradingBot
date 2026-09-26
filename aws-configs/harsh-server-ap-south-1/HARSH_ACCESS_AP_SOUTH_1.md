# Harsh - Server Access Instructions (ap-south-1)

## Instance Details

- **Instance Name**: `tradingview_webhook_bot_ap_south_1`
- **Instance ID**: `i-0440274e868b4bae9`
- **Region**: `ap-south-1` (Mumbai)
- **Public IP (Elastic IP - Fixed)**: `15.207.152.119`
- **Private IP**: `172.31.26.202`
- **Username**: `ubuntu`
- **Instance Type**: `t3.micro`
- **Disk**: 16 GB gp3 (root volume)
- **Security Group**: `harsh-launch-sg-ap-south-1` (`sg-09ee771008abba5cb`)
  - Inbound: SSH (22) from `0.0.0.0/0`
  - Inbound: HTTP (80) from `0.0.0.0/0`
- **SSM / Session Manager**: IAM instance profile `AmazonSSMRoleForInstances` attached

> This server is similar in role to Pratik’s, but hosted in **ap-south-1** (Mumbai) with a **fixed Elastic IP**.

---

## SSH key handling

The original `harsh-key-ap-south-1.pem` was exposed in Git history and must be
treated as compromised. Remove its public key from every server, generate a new
credential, and transfer the replacement through an approved private channel.

Private keys must never be stored in this repository, pasted into issues or pull
requests, or sent through public chat. Keep only these non-secret instructions in
Git. Prefer AWS Systems Manager Session Manager when possible.

---

## Primary SSH Access

### macOS / Linux

1. Save `harsh-key-ap-south-1.pem` somewhere safe, e.g.:

```bash
mkdir -p ~/harsh-server
mv ~/Downloads/harsh-key-ap-south-1.pem ~/harsh-server/
cd ~/harsh-server
chmod 400 harsh-key-ap-south-1.pem
```

2. Connect:

```bash
ssh -i harsh-key-ap-south-1.pem ubuntu@15.207.152.119
```

### Windows (PowerShell / Command Prompt)

1. Place `harsh-key-ap-south-1.pem` in a folder, e.g.:

```powershell
cd C:\Users\Harsh\
mkdir harsh-server
move .\Downloads\harsh-key-ap-south-1.pem .\harsh-server\
cd .\harsh-server
```

2. Fix key permissions (critical):

```powershell
icacls harsh-key-ap-south-1.pem /inheritance:r
icacls harsh-key-ap-south-1.pem /grant:r "$env:USERNAME:(R)"
```

3. Connect:

```powershell
ssh -i harsh-key-ap-south-1.pem ubuntu@15.207.152.119
```

---

## Alternative: AWS Systems Manager (Browser Shell)

Because the instance has the IAM profile `AmazonSSMRoleForInstances`, you (or an admin) can connect via **Session Manager** without SSH:

1. AWS Console → **EC2** → **Instances**.
2. Region selector: choose **`ap-south-1`**.
3. Find instance **`tradingview_webhook_bot_ap_south_1`** (ID `i-0440274e868b4bae9`).
4. Click **“Connect”** → **“Session Manager”** tab → **“Connect”**.

CLI equivalent:

```bash
aws ssm start-session --target i-0440274e868b4bae9 --region ap-south-1
```

---

## Quick Test

After connecting via SSH, Harsh can run:

```bash
echo "Connection successful!"; whoami; hostname; uptime
```

---

## Troubleshooting

### \"Permission denied (publickey)\"

- Ensure you are using:

```bash
ssh -i harsh-key-ap-south-1.pem ubuntu@15.207.152.119
```

- Check key permissions:
  - **Linux/macOS**: `chmod 400 harsh-key-ap-south-1.pem`
  - **Windows**: re-run the `icacls` commands above.

### \"WARNING: UNPROTECTED PRIVATE KEY FILE!\"

- Means the key file is too open.
  - Linux/macOS: `chmod 400 harsh-key-ap-south-1.pem`
  - Windows: fix via `icacls` or **Properties → Security**.

### SSH hangs or times out

- Usually a firewall / network issue on the client side.
- Try:
  - From a different network (home vs office, mobile hotspot, etc.).
  - Using **Session Manager** (see above) which goes over HTTPS (443).

