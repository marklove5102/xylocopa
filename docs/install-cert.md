# Installing the CA Certificate on Other Devices

These instructions are run on the **client device** (the machine or phone you browse from), not the server. First, copy the certificate from the server to your device:

```bash
scp user@server-ip:~/agenthive/certs/selfsigned.crt ~/agenthive.crt
```

> **Tip:** If you're unsure how to install certificates on your OS, paste the relevant section below into Claude or another AI assistant — it can walk you through the steps interactively.

## Android

1. Transfer `selfsigned.crt` to the device
2. **Settings > Security > Encryption & credentials > Install a certificate > CA certificate**
3. Select the file and confirm

## macOS

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain agenthive.crt
```

## Windows

```powershell
certutil -addstore "Root" agenthive.crt
```

## Linux

```bash
sudo cp agenthive.crt /usr/local/share/ca-certificates/agenthive.crt
sudo update-ca-certificates
```

---

Restart your browser after installing.
