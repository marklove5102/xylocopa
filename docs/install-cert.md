# Installing the CA Certificate on Other Devices

These instructions are run on the **client device** (the machine or phone you browse from), not the server. First, copy the certificate from the server to your device:

```bash
scp user@server-ip:~/xylocopa-main/certs/selfsigned.crt ~/xylocopa.crt
```

> **Tip:** If you're unsure how to install certificates on your OS, paste the relevant section below into Claude or another AI assistant, it can walk you through the steps interactively.

> **Migrating from AgentHive?** Existing `agenthive.crt` / `agenthive-ca.crt` installations remain trusted, no action needed. Newly issued certs use the `xylocopa.crt` filename.

## Android

1. Transfer `xylocopa.crt` to the device (the file you scp'd above)
2. **Settings > Security > Encryption & credentials > Install a certificate > CA certificate**
3. Select the file and confirm

## macOS

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain xylocopa.crt
```

## Windows

```powershell
certutil -addstore "Root" xylocopa.crt
```

## Linux

```bash
sudo cp xylocopa.crt /usr/local/share/ca-certificates/xylocopa.crt
sudo update-ca-certificates
```

---

Restart your browser after installing.
