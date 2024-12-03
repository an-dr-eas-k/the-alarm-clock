npx mkcert create-ca --organization andreask --country-code DE --state Bavaria --locality Munich --validity 30000

openssl x509 -in ca.crt -out ca.pem -outform PEM
npx mkcert create-cert --validity 30000 --domains the-alarm-clock,the-alarm-clock.fritz.box,localhost

return
CANAME=ca


# generate aes encrypted private key
openssl genrsa -aes256 -out $CANAME.key 4096

# create certificate
openssl req -x509 -new -nodes -key $CANAME.key -sha256 -days 30000 -out $CANAME.crt -subj '/CN=RootCA/C=DE/ST=Bavaria/L=Munich/O=andreask'

# create certificate for service
MYCERT=cert
openssl req -new -nodes -out $MYCERT.csr -newkey rsa:4096 -keyout $MYCERT.key -subj '/CN=the-alarm-clock/C=DE/ST=Bavaria/L=Munich/O=andreask'

# create a v3 ext file for SAN properties
cat > $MYCERT.v3.ext << EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
DNS.2 = the-alarm-clock
DNS.3 = the-alarm-clock.fritz.box
EOF

openssl x509 -req -in $MYCERT.csr -CA $CANAME.crt -CAkey $CANAME.key -CAcreateserial -out $MYCERT.crt -days 30000 -sha256 -extfile $MYCERT.v3.ext