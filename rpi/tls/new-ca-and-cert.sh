# the created certiticate for the authority is available in ~/own/development/an-dr-eas-k.ca-root-certificate/*
# rm ca.*
# npx mkcert create-ca --organization "an.dr.eas.k Root CA" --country-code DE --state Bavaria --locality Munich --validity 30000

rm cert.*
npx mkcert create-cert --validity 30000 --domains "the-alarm-clock" "the-alarm-clock.fritz.box"
