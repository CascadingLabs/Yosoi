# Direct HTTP TLS fixture

`cert.der` and `key.der` are a test-only self-signed certificate and PKCS#8 private key for `localhost` and `127.0.0.1`. The private key is intentionally public test material and must never be used outside deterministic local tests.

The certificate is valid from 2026-09-06 through 2036-09-03. Regenerate both files with OpenSSL when the fixture expires:

```bash
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout /tmp/yosoi-direct-http-key.pem \
  -out /tmp/yosoi-direct-http-cert.pem \
  -days 3650 -subj '/CN=localhost' \
  -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1'
openssl x509 -in /tmp/yosoi-direct-http-cert.pem -outform DER -out cert.der
openssl pkcs8 -topk8 -nocrypt -in /tmp/yosoi-direct-http-key.pem -outform DER -out key.der
rm /tmp/yosoi-direct-http-key.pem /tmp/yosoi-direct-http-cert.pem
```

Tests pin `cert.der` explicitly and never modify the host trust store.
