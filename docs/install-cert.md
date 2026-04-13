# Installing the CA Certificate on Other Devices

Copy `certs/selfsigned.crt` from the server to your device, then follow the instructions for your platform.

```bash
scp user@server-ip:~/agenthive/certs/selfsigned.crt ~/agenthive.crt
```

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
